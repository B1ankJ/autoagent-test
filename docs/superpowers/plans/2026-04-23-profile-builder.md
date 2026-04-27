# Profile Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a human-in-the-loop Android Profile Builder that captures app states, generates a draft profile plus review items, and validates the draft with a connectivity test before saving.

**Architecture:** The builder is a guided capture and draft-generation pipeline layered on top of the existing Android device, executor, and profile APIs. Server-side code captures XML, screenshots, and foreground metadata, reduces them into candidate locators and review items, then optionally enriches the draft with an LLM-backed generator. Frontend code drives the guided flow, renders review decisions, previews the draft YAML, and runs the existing connectivity flow before persisting the profile.

**Tech Stack:** Python 3.11 · FastAPI · Pydantic · existing Android adb/uiautomator2 stack · React 18 · TanStack Query v5 · Ant Design · pytest · Vitest

**Spec reference:** `docs/superpowers/specs/2026-04-23-profile-builder-design.md`.

---

## File Structure

```text
src/autoagent/
  api/
    profile_builder.py
    profiles.py
  executors/
    profile_builder_capture.py
    profile_builder_candidates.py
    profile_builder_generator.py
  models/
    api.py
  config/
    settings.py

tests/
  unit/
    test_profile_builder_capture.py
    test_profile_builder_candidates.py
    test_profile_builder_generator.py
  integration/
    test_profile_builder_endpoints.py

web/src/
  api/
    profileBuilder.ts
  pages/
    Profiles/Builder.tsx
    Profiles/Builder.test.tsx
    Profiles/List.tsx
  types/
    api.ts
```

## Task 1: Add profile-builder API and data contracts

**Files:**
- Modify: `src/autoagent/models/api.py`
- Modify: `src/autoagent/api/__init__.py`
- Modify: `src/autoagent/main.py`
- Create: `src/autoagent/api/profile_builder.py`
- Test: `tests/integration/test_profile_builder_endpoints.py`

- [ ] **Step 1: Write the failing endpoint contract test**

`tests/integration/test_profile_builder_endpoints.py`

```python
from httpx import ASGITransport, AsyncClient

from autoagent.main import app


async def test_profile_builder_session_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "data"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create = await client.post(
            "/api/v1/profile-builder/sessions",
            json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        )

        assert create.status_code == 201
        session = create.json()
        assert session["platform"] == "android"
        assert session["status"] == "draft"
        assert session["steps"] == ["idle", "editing", "response"]

        fetched = await client.get(f"/api/v1/profile-builder/sessions/{session['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["id"] == session["id"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -v
```
Expected: FAIL with `404 Not Found` for `/api/v1/profile-builder/sessions`.

- [ ] **Step 3: Add API schemas to `src/autoagent/models/api.py`**

Add minimal Pydantic models:

```python
class ProfileBuilderSessionCreate(BaseModel):
    platform: Literal["android"]
    device_serial: str
    name: str


class ProfileBuilderSessionView(BaseModel):
    id: str
    platform: Literal["android"]
    device_serial: str
    name: str
    status: Literal["draft", "ready", "validated"]
    steps: list[str]
    artifact_dir: str
```

- [ ] **Step 4: Add the router in `src/autoagent/api/profile_builder.py`**

Create:

```python
from fastapi import APIRouter, status

from autoagent.models.api import (
    ProfileBuilderSessionCreate,
    ProfileBuilderSessionView,
)

router = APIRouter(prefix="/api/v1/profile-builder", tags=["profile-builder"])


@router.post("/sessions", response_model=ProfileBuilderSessionView, status_code=status.HTTP_201_CREATED)
async def create_session(payload: ProfileBuilderSessionCreate) -> ProfileBuilderSessionView:
    return ProfileBuilderSessionView(
        id="pb_demo",
        platform=payload.platform,
        device_serial=payload.device_serial,
        name=payload.name,
        status="draft",
        steps=["idle", "editing", "response"],
        artifact_dir="data/profile_builder/pb_demo",
    )


@router.get("/sessions/{session_id}", response_model=ProfileBuilderSessionView)
async def get_session(session_id: str) -> ProfileBuilderSessionView:
    return ProfileBuilderSessionView(
        id=session_id,
        platform="android",
        device_serial="serial-1",
        name="qwen",
        status="draft",
        steps=["idle", "editing", "response"],
        artifact_dir=f"data/profile_builder/{session_id}",
    )
```

- [ ] **Step 5: Wire the router into `src/autoagent/main.py`**

Add:

```python
from autoagent.api import profile_builder

app.include_router(profile_builder.router)
```

- [ ] **Step 6: Run the integration test to verify it passes**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/models/api.py src/autoagent/api/profile_builder.py src/autoagent/main.py tests/integration/test_profile_builder_endpoints.py
git commit -m "feat(profile-builder): add session API contracts"
```

---

## Task 2: Add guided Android capture and artifact persistence

**Files:**
- Create: `src/autoagent/executors/profile_builder_capture.py`
- Modify: `src/autoagent/api/profile_builder.py`
- Test: `tests/unit/test_profile_builder_capture.py`
- Test: `tests/integration/test_profile_builder_endpoints.py`

- [ ] **Step 1: Write the failing capture unit test**

`tests/unit/test_profile_builder_capture.py`

```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from autoagent.executors.profile_builder_capture import capture_android_state


@pytest.mark.asyncio
async def test_capture_android_state_writes_expected_artifacts(tmp_path: Path):
    device = MagicMock()
    device.dump_hierarchy.return_value = "<hierarchy><node text='发消息'/></hierarchy>"
    device.app_current.return_value = {"package": "com.aliyun.tongyi", "activity": ".BrowserActivity"}
    device.screenshot.return_value = b"png-bytes"

    result = await capture_android_state(
        device=device,
        session_dir=tmp_path,
        step="idle",
    )

    assert result.package == "com.aliyun.tongyi"
    assert result.activity == ".BrowserActivity"
    assert (tmp_path / "capture_idle.xml").read_text(encoding="utf-8").startswith("<hierarchy>")
    assert (tmp_path / "capture_idle.png").read_bytes() == b"png-bytes"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_capture.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `capture_android_state`**

Create `src/autoagent/executors/profile_builder_capture.py`:

```python
from dataclasses import dataclass
from pathlib import Path
import asyncio


@dataclass
class CapturedState:
    step: str
    package: str
    activity: str | None
    xml_path: Path
    screenshot_path: Path


async def capture_android_state(device, session_dir: Path, step: str) -> CapturedState:
    session_dir.mkdir(parents=True, exist_ok=True)
    xml = await asyncio.to_thread(device.dump_hierarchy, compressed=False)
    current = await asyncio.to_thread(device.app_current)
    screenshot = await asyncio.to_thread(device.screenshot, format="pillow")

    xml_path = session_dir / f"capture_{step}.xml"
    png_path = session_dir / f"capture_{step}.png"
    xml_path.write_text(xml, encoding="utf-8")
    screenshot.save(png_path)

    return CapturedState(
        step=step,
        package=current.get("package", ""),
        activity=current.get("activity"),
        xml_path=xml_path,
        screenshot_path=png_path,
    )
```

- [ ] **Step 4: Expose `POST /api/v1/profile-builder/sessions/{id}/capture/{step}`**

In `src/autoagent/api/profile_builder.py`, add:

```python
@router.post("/sessions/{session_id}/capture/{step}", response_model=ProfileBuilderSessionView)
async def capture_session_step(session_id: str, step: str) -> ProfileBuilderSessionView:
    ...
```

For the first pass, resolve the device with `u2.connect`, call `capture_android_state`, and return the updated session view.

- [ ] **Step 5: Extend the integration test to capture `idle`**

Add:

```python
capture = await client.post(f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle")
assert capture.status_code == 200
assert "capture_idle.xml" in capture.json()["artifacts"]
```

- [ ] **Step 6: Run unit and integration tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_capture.py tests/integration/test_profile_builder_endpoints.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/executors/profile_builder_capture.py src/autoagent/api/profile_builder.py tests/unit/test_profile_builder_capture.py tests/integration/test_profile_builder_endpoints.py
git commit -m "feat(profile-builder): add android capture artifacts"
```

---

## Task 3: Add candidate extraction and review-item generation

**Files:**
- Create: `src/autoagent/executors/profile_builder_candidates.py`
- Modify: `src/autoagent/api/profile_builder.py`
- Test: `tests/unit/test_profile_builder_candidates.py`

- [ ] **Step 1: Write the failing candidate extractor test**

`tests/unit/test_profile_builder_candidates.py`

```python
from autoagent.executors.profile_builder_candidates import build_android_candidates


def test_build_android_candidates_finds_input_send_and_response_hints(tmp_path):
    idle_xml = """<hierarchy><node text="发消息或按住说话..." class="android.widget.TextView" bounds="[177,2066][777,2123]" /></hierarchy>"""
    editing_xml = """<hierarchy><node text="你好" class="android.widget.EditText" bounds="[36,1882][1032,2002]" /><node class="android.widget.FrameLayout" bounds="[909,2009][1020,2120]" clickable="true" /></hierarchy>"""
    response_xml = """<hierarchy><node text="你好" class="android.widget.EditText" /><node text="当然可以" class="android.widget.TextView" /></hierarchy>"""

    draft = build_android_candidates(idle_xml=idle_xml, editing_xml=editing_xml, response_xml=response_xml)

    assert draft.input_candidates[0]["locator"]["value"] == '//*[@class="android.widget.EditText"]'
    assert draft.send_candidates[0]["locator"]["value"] == '//*[@bounds="[909,2009][1020,2120]"]'
    assert draft.review_items[0]["field"] in {"input_locator", "send_button_locator", "latest_bubble_match"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_candidates.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `build_android_candidates`**

Create a focused extractor that:

- parses XML with `ElementTree`
- prefers `EditText` nodes in editing state for `input_locator`
- prefers rightmost clickable nodes near the bottom in editing state for `send_button_locator`
- uses large repeated `TextView` containers in response state for response hints
- emits `review_items` whenever multiple candidates exist

Minimal return structure:

```python
@dataclass
class AndroidCandidateDraft:
    input_candidates: list[dict]
    send_candidates: list[dict]
    response_candidates: list[dict]
    review_items: list[dict]
```

- [ ] **Step 4: Add draft generation to the session API**

In `src/autoagent/api/profile_builder.py`, after all required captures exist, add:

```python
@router.post("/sessions/{session_id}/draft")
async def generate_draft(session_id: str) -> dict:
    ...
```

Persist:

- `candidates.json`
- `review_items.json`
- `draft_profile.yaml`

For the first pass, generate YAML from rules only.

- [ ] **Step 5: Run the unit test**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_candidates.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/executors/profile_builder_candidates.py src/autoagent/api/profile_builder.py tests/unit/test_profile_builder_candidates.py
git commit -m "feat(profile-builder): add rule-based candidate extraction"
```

---

## Task 4: Add optional LLM draft enrichment with strict structured output

**Files:**
- Create: `src/autoagent/executors/profile_builder_generator.py`
- Modify: `src/autoagent/config/settings.py`
- Modify: `src/autoagent/api/profile_builder.py`
- Test: `tests/unit/test_profile_builder_generator.py`

- [ ] **Step 1: Write the failing generator test**

`tests/unit/test_profile_builder_generator.py`

```python
import pytest

from autoagent.executors.profile_builder_generator import merge_llm_draft


def test_merge_llm_draft_prefers_rule_candidates_when_llm_field_is_missing():
    rule_draft = {
        "input_locator": {"type": "xpath", "value": '//*[@class="android.widget.EditText"]'},
        "send_button_locator": {"type": "xpath", "value": '//*[@bounds="[909,2009][1020,2120]"]'},
    }
    llm_output = {
        "input_locator": {"type": "xpath", "value": '//*[@class="android.widget.EditText"]'},
    }

    merged = merge_llm_draft(rule_draft, llm_output)

    assert merged["input_locator"]["value"] == '//*[@class="android.widget.EditText"]'
    assert merged["send_button_locator"]["value"] == '//*[@bounds="[909,2009][1020,2120]"]'
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_generator.py -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Add generator settings**

In `src/autoagent/config/settings.py`, add:

```python
profile_builder_llm_base_url: str | None = None
profile_builder_llm_model: str | None = None
profile_builder_llm_api_key: str | None = None
profile_builder_llm_timeout_sec: float = 30.0
```

- [ ] **Step 4: Implement the generator merge helper**

Create `src/autoagent/executors/profile_builder_generator.py`:

```python
def merge_llm_draft(rule_draft: dict, llm_output: dict | None) -> dict:
    if not llm_output:
        return rule_draft
    merged = dict(rule_draft)
    for key, value in llm_output.items():
        if value:
            merged[key] = value
    return merged
```

Keep networked LLM calls behind a single function so the MVP can ship with rule-only mode enabled by default.

- [ ] **Step 5: Integrate optional enrichment in `/draft`**

In `src/autoagent/api/profile_builder.py`, wrap enrichment like:

```python
if settings.profile_builder_llm_base_url and settings.profile_builder_llm_model:
    llm_output = await maybe_generate_llm_draft(...)
    final_draft = merge_llm_draft(rule_draft, llm_output)
else:
    final_draft = rule_draft
```

- [ ] **Step 6: Run the unit test**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_generator.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/executors/profile_builder_generator.py src/autoagent/config/settings.py src/autoagent/api/profile_builder.py tests/unit/test_profile_builder_generator.py
git commit -m "feat(profile-builder): add optional llm draft enrichment"
```

---

## Task 5: Add frontend guided builder flow

**Files:**
- Create: `web/src/api/profileBuilder.ts`
- Create: `web/src/pages/Profiles/Builder.tsx`
- Create: `web/src/pages/Profiles/Builder.test.tsx`
- Modify: `web/src/pages/Profiles/List.tsx`
- Modify: `web/src/types/api.ts`

- [ ] **Step 1: Write the failing page test**

`web/src/pages/Profiles/Builder.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

import Builder from "./Builder";

test("renders guided builder steps", async () => {
  render(
    <MemoryRouter initialEntries={["/profiles/builder"]}>
      <Routes>
        <Route path="/profiles/builder" element={<Builder />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByText("Build Profile")).toBeInTheDocument();
  expect(screen.getByText("Capture Idle State")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd web && pnpm test -- Builder.test.tsx
```
Expected: FAIL because `Builder.tsx` does not exist.

- [ ] **Step 3: Add typed API helpers**

Create `web/src/api/profileBuilder.ts`:

```ts
import { api } from "./client";

export async function createProfileBuilderSession(payload: {
  platform: "android";
  device_serial: string;
  name: string;
}) {
  return api.post("/api/v1/profile-builder/sessions", payload);
}
```

Add matching response types to `web/src/types/api.ts`.

- [ ] **Step 4: Build the guided page**

Create `web/src/pages/Profiles/Builder.tsx` with:

```tsx
export default function Builder() {
  return (
    <div>
      <h1>Build Profile</h1>
      <h2>Capture Idle State</h2>
      <h2>Capture Editing State</h2>
      <h2>Capture Response State</h2>
    </div>
  );
}
```

Then expand it to:

- select device
- start session
- capture steps
- show review items
- preview YAML
- run connectivity test

- [ ] **Step 5: Link from Profiles list**

In `web/src/pages/Profiles/List.tsx`, add a primary action:

```tsx
<Button type="primary" onClick={() => navigate("/profiles/builder")}>
  Build Profile
</Button>
```

- [ ] **Step 6: Run the frontend test**

Run:
```bash
cd web && pnpm test -- Builder.test.tsx Profiles/List.test.tsx
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/api/profileBuilder.ts web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx web/src/pages/Profiles/List.tsx web/src/types/api.ts
git commit -m "feat(profile-builder): add guided builder UI"
```

---

## Task 6: Add review resolution and connectivity validation loop

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Modify: `src/autoagent/api/tests.py`
- Modify: `web/src/pages/Profiles/Builder.tsx`
- Test: `tests/integration/test_profile_builder_endpoints.py`
- Test: `web/src/pages/Profiles/Builder.test.tsx`

- [ ] **Step 1: Write the failing review-and-validate API test**

Extend `tests/integration/test_profile_builder_endpoints.py`:

```python
review = await client.post(
    f"/api/v1/profile-builder/sessions/{session_id}/review",
    json={"send_button_locator": {"type": "xpath", "value": '//*[@bounds="[909,2009][1020,2120]"]'}},
)
assert review.status_code == 200

validate = await client.post(f"/api/v1/profile-builder/sessions/{session_id}/validate")
assert validate.status_code == 200
assert validate.json()["status"] in {"ready", "validated"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -v
```
Expected: FAIL with `404` for `/review` or `/validate`.

- [ ] **Step 3: Add review and validation endpoints**

In `src/autoagent/api/profile_builder.py`, add:

```python
@router.post("/sessions/{session_id}/review")
async def apply_review(session_id: str, payload: dict) -> dict:
    ...


@router.post("/sessions/{session_id}/validate")
async def validate_draft(session_id: str) -> dict:
    ...
```

Validation should call the existing sync connectivity path with the generated draft profile, then persist:

- `connectivity_result.json`
- last generated YAML
- updated session status

- [ ] **Step 4: Render review UI and validation action**

In `web/src/pages/Profiles/Builder.tsx`, add:

- review cards for uncertain fields
- recommended option first
- `Run Connectivity Test` button
- result summary panel

- [ ] **Step 5: Run backend and frontend tests**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -v
cd web && pnpm test -- Builder.test.tsx
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/api/profile_builder.py src/autoagent/api/tests.py tests/integration/test_profile_builder_endpoints.py web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx
git commit -m "feat(profile-builder): add review and connectivity loop"
```

---

## Task 7: Document the builder and verify the end-to-end MVP

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-04-23-profile-builder-design.md`

- [ ] **Step 1: Add operator docs to `README.md`**

Document:

- where to launch the builder
- Android state capture expectations
- what `review_items` mean
- optional LLM configuration env vars

Suggested block:

```md
### Profile Builder (Android MVP)

Use Profiles → Build Profile to generate a draft Android profile from guided captures.
The builder captures idle, editing, and response states, proposes locators, asks for confirmation on low-confidence fields, then runs connectivity before save.

Optional LLM settings:

    export PROFILE_BUILDER_LLM_BASE_URL=...
    export PROFILE_BUILDER_LLM_MODEL=...
    export PROFILE_BUILDER_LLM_API_KEY=...
```

- [ ] **Step 2: Add developer notes to `CLAUDE.md`**

Add:

```md
- Profile Builder stores artifacts under `data/profile_builder/<session_id>/`.
- Rule-only draft generation must work without LLM config.
- Builder connectivity must reuse the existing profile test path rather than duplicating executor logic.
```

- [ ] **Step 3: Run the MVP verification commands**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_capture.py tests/unit/test_profile_builder_candidates.py tests/unit/test_profile_builder_generator.py tests/integration/test_profile_builder_endpoints.py -v
cd web && pnpm test -- Builder.test.tsx
cd web && pnpm build
python3.11 -m ruff check src/autoagent/api/profile_builder.py src/autoagent/executors/profile_builder_capture.py src/autoagent/executors/profile_builder_candidates.py src/autoagent/executors/profile_builder_generator.py
```
Expected: all commands exit 0.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md docs/superpowers/specs/2026-04-23-profile-builder-design.md
git commit -m "docs(profile-builder): document android builder mvp"
```

---

## Self-Review

Spec coverage check:

- guided Android capture: Tasks 1 to 2
- rule-based candidate extraction: Task 3
- optional LLM enrichment: Task 4
- human review UI: Tasks 5 to 6
- connectivity validation loop: Task 6
- docs and operator flow: Task 7

Placeholder scan:

- no `TODO`, `TBD`, or “implement later” markers remain
- each task names exact files and concrete commands

Type consistency:

- session contracts stay under `ProfileBuilderSessionCreate` / `ProfileBuilderSessionView`
- builder endpoints consistently use `/api/v1/profile-builder/...`
- draft artifacts consistently use `capture_<step>.*`, `candidates.json`, `review_items.json`, `draft_profile.yaml`
