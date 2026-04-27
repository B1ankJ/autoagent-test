# Profile Builder Runtime Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime observability to the Android Profile Builder so operators can see live step status and key screenshots for capture and connectivity validation.

**Architecture:** Persist a builder-scoped `runtime.json` alongside existing profile-builder artifacts, expose it through a dedicated backend endpoint, and have the Builder page poll that runtime snapshot while work is active. Capture and validate flows update the runtime snapshot and write a small fixed set of key screenshots, which the frontend renders as a status/timeline/screenshot panel.

**Tech Stack:** FastAPI, Pydantic, existing profile-builder backend modules, React, TypeScript, Ant Design, TanStack Query, Vitest, pytest, Ruff

---

## File Structure

- Modify: `src/autoagent/models/api.py`
  - Add runtime response models for builder observability.
- Modify: `src/autoagent/api/profile_builder.py`
  - Add runtime persistence helpers, runtime GET endpoint, and runtime updates during capture/review/validate.
- Modify: `src/autoagent/executors/android_executor.py`
  - Reuse existing validate screenshot moments if needed, or keep current behavior unchanged if the builder route can capture enough state itself.
- Create: `tests/unit/test_profile_builder_runtime.py`
  - Backend unit tests for runtime helpers and snapshot persistence.
- Modify: `tests/integration/test_profile_builder_endpoints.py`
  - Integration coverage for runtime endpoint and validate screenshot/runtime updates.
- Modify: `web/src/types/api.ts`
  - Add builder runtime types.
- Create: `web/src/api/profileBuilderRuntime.ts`
  - Typed runtime polling helper.
- Modify: `web/src/pages/Profiles/Builder.tsx`
  - Add top status bar, step timeline, screenshot preview panel, and automatic runtime refresh.
- Modify: `web/src/pages/Profiles/Builder.test.tsx`
  - Add frontend runtime rendering tests.

This split keeps backend runtime/state work separate from frontend polling/rendering work.

---

### Task 1: Add backend runtime snapshot models and persistence helpers

**Files:**
- Modify: `src/autoagent/models/api.py`
- Modify: `src/autoagent/api/profile_builder.py`
- Create: `tests/unit/test_profile_builder_runtime.py`

- [ ] **Step 1: Write the failing runtime unit test**

`tests/unit/test_profile_builder_runtime.py`

```python
from pathlib import Path

from autoagent.api.profile_builder import (
    _load_runtime_from_disk,
    _runtime_json_path,
    _store_runtime,
)


def test_store_runtime_persists_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "autoagent.api.profile_builder._session_dir",
        lambda session_id: tmp_path / session_id,
    )

    runtime = {
        "session_id": "pb_123",
        "session_status": "draft",
        "current_step": "capture_idle",
        "step_state": "running",
        "last_error": None,
        "captures": [],
        "connectivity": {
            "status": "idle",
            "result_status": None,
            "result_summary": None,
            "screens": [],
        },
        "recent_screens": [],
    }

    stored = _store_runtime("pb_123", runtime)

    assert stored["current_step"] == "capture_idle"
    assert _runtime_json_path("pb_123").exists()
    assert _load_runtime_from_disk("pb_123")["step_state"] == "running"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_runtime.py -v
```

Expected: FAIL with import or attribute errors for missing runtime helpers.

- [ ] **Step 3: Add runtime models and persistence helpers**

`src/autoagent/models/api.py`

```python
class ProfileBuilderRuntimeScreen(BaseModel):
    step: str
    label: str
    path: str
    taken_at: datetime


class ProfileBuilderRuntimeCapture(BaseModel):
    step: str
    status: Literal["pending", "running", "done", "failed"]
    screenshot: str | None = None
    updated_at: datetime | None = None


class ProfileBuilderRuntimeConnectivity(BaseModel):
    status: Literal["idle", "running", "done", "failed"] = "idle"
    result_status: SampleStatus | None = None
    result_summary: str | None = None
    screens: list[ProfileBuilderRuntimeScreen] = Field(default_factory=list)


class ProfileBuilderRuntimeView(BaseModel):
    session_id: str
    session_status: Literal["draft", "ready", "validating", "validated", "failed"]
    current_step: str
    step_state: Literal["idle", "running", "done", "failed"]
    last_error: str | None = None
    captures: list[ProfileBuilderRuntimeCapture] = Field(default_factory=list)
    connectivity: ProfileBuilderRuntimeConnectivity = Field(
        default_factory=ProfileBuilderRuntimeConnectivity
    )
    recent_screens: list[ProfileBuilderRuntimeScreen] = Field(default_factory=list)
```

`src/autoagent/api/profile_builder.py`

```python
def _runtime_json_path(session_id: str) -> Path:
    return _session_dir(session_id) / "runtime.json"


def _default_runtime(session: ProfileBuilderSessionView) -> ProfileBuilderRuntimeView:
    return ProfileBuilderRuntimeView(
        session_id=session.id,
        session_status=session.status,
        current_step="idle",
        step_state="idle",
        captures=[
            ProfileBuilderRuntimeCapture(step=step, status="pending") for step in session.steps
        ],
    )


def _load_runtime_from_disk(session_id: str) -> dict | None:
    path = _runtime_json_path(session_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _store_runtime(session_id: str, runtime: dict) -> dict:
    path = _runtime_json_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(runtime, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return runtime
```

- [ ] **Step 4: Run the runtime unit test**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_runtime.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/models/api.py src/autoagent/api/profile_builder.py tests/unit/test_profile_builder_runtime.py
git commit -m "feat(profile-builder): add runtime snapshot persistence"
```

---

### Task 2: Expose the runtime API and update capture state transitions

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Modify: `tests/integration/test_profile_builder_endpoints.py`

- [ ] **Step 1: Write the failing integration test for runtime fetch**

Add to `tests/integration/test_profile_builder_endpoints.py`:

```python
async def test_profile_builder_runtime_endpoint_reflects_capture_progress(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()

    device = MagicMock()
    device.dump_hierarchy.return_value = "<hierarchy><node text='发消息'/></hierarchy>"
    device.app_current.return_value = {
        "package": "com.aliyun.tongyi",
        "activity": ".BrowserActivity",
    }
    device.screenshot.return_value = b"png-bytes"
    monkeypatch.setattr("autoagent.api.profile_builder.u2.connect", lambda serial: device)

    capture = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/capture/idle",
        headers=headers,
    )
    assert capture.status_code == 200

    runtime = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}/runtime",
        headers=headers,
    )
    assert runtime.status_code == 200
    body = runtime.json()
    assert body["current_step"] == "capture_idle"
    assert body["captures"][0]["status"] == "done"
    assert body["captures"][0]["screenshot"] == "capture_idle.png"
```

- [ ] **Step 2: Run the integration test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -k runtime_endpoint_reflects_capture_progress -v
```

Expected: FAIL with `404` for `/runtime`.

- [ ] **Step 3: Add runtime endpoint and capture updates**

`src/autoagent/api/profile_builder.py`

```python
@router.get("/sessions/{session_id}/runtime", response_model=ProfileBuilderRuntimeView)
async def get_runtime(session_id: str) -> ProfileBuilderRuntimeView:
    session = _get_session_or_404(session_id)
    runtime = _load_runtime_from_disk(session_id)
    if runtime is None:
        runtime = _default_runtime(session).model_dump(mode="json")
        _store_runtime(session_id, runtime)
    return ProfileBuilderRuntimeView.model_validate(runtime)
```

Inside `capture_session_step()` update runtime before and after capture:

```python
runtime = _load_runtime_from_disk(session_id) or _default_runtime(session).model_dump(mode="json")
runtime["current_step"] = f"capture_{step}"
runtime["step_state"] = "running"
_store_runtime(session_id, runtime)
```

After capture succeeds:

```python
runtime = _load_runtime_from_disk(session_id) or _default_runtime(current_session).model_dump(mode="json")
runtime["current_step"] = f"capture_{step}"
runtime["step_state"] = "done"
for item in runtime["captures"]:
    if item["step"] == step:
        item["status"] = "done"
        item["screenshot"] = capture_record.screenshot_artifact
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
runtime["recent_screens"] = [
    {
        "step": step,
        "label": f"capture_{step}",
        "path": capture_record.screenshot_artifact,
        "taken_at": datetime.now(timezone.utc).isoformat(),
    }
]
_store_runtime(session_id, runtime)
```

- [ ] **Step 4: Run the targeted integration test**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -k runtime_endpoint_reflects_capture_progress -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/api/profile_builder.py tests/integration/test_profile_builder_endpoints.py
git commit -m "feat(profile-builder): expose runtime capture state"
```

---

### Task 3: Track connectivity runtime and persist key validation screenshots

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Modify: `tests/integration/test_profile_builder_endpoints.py`

- [ ] **Step 1: Write the failing validation runtime test**

Add to `tests/integration/test_profile_builder_endpoints.py`:

```python
async def test_profile_builder_validate_updates_runtime_and_screens(client, monkeypatch):
    headers = await _h(client)
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )
    session = create.json()
    artifact_dir = get_settings().data_root / "profile_builder" / session["id"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "draft_profile.yaml").write_text("name: qwen\nplatform: android\npackage: demo\n", encoding="utf-8")

    async def _run_sync(sample):
        for name in (
            "validate_before_input.png",
            "validate_after_input.png",
            "validate_after_send.png",
            "validate_after_result.png",
        ):
            (artifact_dir / name).write_bytes(b"png")
        return SampleResult(
            id=sample.id,
            status="done",
            prompts_sent=["hello"],
            responses=["pong"],
            mode=sample.mode,
            target_profile=sample.target_profile,
        )

    monkeypatch.setattr("autoagent.api.profile_builder.execute_sync_test", _run_sync)

    validate = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/validate",
        headers=headers,
    )
    assert validate.status_code == 200

    runtime = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}/runtime",
        headers=headers,
    )
    assert runtime.status_code == 200
    body = runtime.json()
    assert body["session_status"] == "validated"
    assert body["connectivity"]["status"] == "done"
    assert body["connectivity"]["result_summary"] == "pong"
    assert len(body["connectivity"]["screens"]) >= 1
```

- [ ] **Step 2: Run the validation runtime test to verify it fails**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -k validate_updates_runtime_and_screens -v
```

Expected: FAIL because runtime connectivity fields are not populated.

- [ ] **Step 3: Update validation flow and register key screenshots**

In `src/autoagent/api/profile_builder.py`, add helper:

```python
def _runtime_screens_for_validation(session: ProfileBuilderSessionView) -> list[dict]:
    artifact_dir = Path(session.artifact_dir)
    names = [
        "validate_before_input.png",
        "validate_after_input.png",
        "validate_after_send.png",
        "validate_after_result.png",
        "validate_on_error.png",
    ]
    screens = []
    for name in names:
        path = artifact_dir / name
        if path.exists():
            screens.append(
                {
                    "step": "connectivity",
                    "label": path.stem,
                    "path": name,
                    "taken_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    return screens
```

Update `validate_draft()`:

```python
runtime = _load_runtime_from_disk(session_id) or _default_runtime(session).model_dump(mode="json")
runtime["session_status"] = "validating"
runtime["current_step"] = "connectivity"
runtime["step_state"] = "running"
runtime["last_error"] = None
_store_runtime(session_id, runtime)
```

After execution:

```python
runtime = _load_runtime_from_disk(session_id) or _default_runtime(session).model_dump(mode="json")
runtime["session_status"] = "validated" if result.status == "done" else "ready"
runtime["current_step"] = "connectivity"
runtime["step_state"] = "done" if result.status == "done" else "failed"
runtime["connectivity"] = {
    "status": "done" if result.status == "done" else "failed",
    "result_status": result.status,
    "result_summary": (result.responses[0] if result.responses else result.error),
    "screens": _runtime_screens_for_validation(session),
}
runtime["recent_screens"] = runtime["connectivity"]["screens"][-3:]
_store_runtime(session_id, runtime)
```

- [ ] **Step 4: Run the validation runtime test**

Run:
```bash
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -k validate_updates_runtime_and_screens -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/api/profile_builder.py tests/integration/test_profile_builder_endpoints.py
git commit -m "feat(profile-builder): track connectivity runtime screens"
```

---

### Task 4: Add frontend runtime types and polling helper

**Files:**
- Modify: `web/src/types/api.ts`
- Create: `web/src/api/profileBuilderRuntime.ts`

- [ ] **Step 1: Write the failing runtime API helper test**

Create `web/src/api/profileBuilderRuntime.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'

import { client } from './client'
import { fetchProfileBuilderRuntime } from './profileBuilderRuntime'

describe('profileBuilderRuntime api', () => {
  it('fetches runtime by session id', async () => {
    vi.spyOn(client, 'get').mockResolvedValueOnce({
      data: { session_id: 'pb_1', current_step: 'capture_idle' },
    } as never)

    const data = await fetchProfileBuilderRuntime('pb_1')

    expect(client.get).toHaveBeenCalledWith('/profile-builder/sessions/pb_1/runtime')
    expect(data.session_id).toBe('pb_1')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd web && pnpm test -- profileBuilderRuntime.test.ts
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Add runtime types and polling helper**

`web/src/types/api.ts`

```ts
export interface ProfileBuilderRuntimeScreen {
  step: string
  label: string
  path: string
  taken_at: string
}

export interface ProfileBuilderRuntimeCapture {
  step: string
  status: 'pending' | 'running' | 'done' | 'failed'
  screenshot: string | null
  updated_at: string | null
}

export interface ProfileBuilderRuntimeConnectivity {
  status: 'idle' | 'running' | 'done' | 'failed'
  result_status: SampleStatus | null
  result_summary: string | null
  screens: ProfileBuilderRuntimeScreen[]
}

export interface ProfileBuilderRuntimeView {
  session_id: string
  session_status: 'draft' | 'ready' | 'validating' | 'validated' | 'failed'
  current_step: string
  step_state: 'idle' | 'running' | 'done' | 'failed'
  last_error: string | null
  captures: ProfileBuilderRuntimeCapture[]
  connectivity: ProfileBuilderRuntimeConnectivity
  recent_screens: ProfileBuilderRuntimeScreen[]
}
```

`web/src/api/profileBuilderRuntime.ts`

```ts
import { useQuery } from '@tanstack/react-query'

import { ProfileBuilderRuntimeView } from '../types/api'
import { client } from './client'

export async function fetchProfileBuilderRuntime(sessionId: string) {
  return (
    await client.get<ProfileBuilderRuntimeView>(`/profile-builder/sessions/${sessionId}/runtime`)
  ).data
}

export function useProfileBuilderRuntime(sessionId: string | undefined, active: boolean) {
  return useQuery({
    queryKey: ['profile-builder-runtime', sessionId],
    queryFn: () => fetchProfileBuilderRuntime(sessionId as string),
    enabled: !!sessionId,
    refetchInterval: active ? 1500 : 4000,
  })
}
```

- [ ] **Step 4: Run the helper test**

Run:
```bash
cd web && pnpm test -- profileBuilderRuntime.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/types/api.ts web/src/api/profileBuilderRuntime.ts web/src/api/profileBuilderRuntime.test.ts
git commit -m "feat(profile-builder): add runtime polling client"
```

---

### Task 5: Render top status, step timeline, and screenshot preview in Builder

**Files:**
- Modify: `web/src/pages/Profiles/Builder.tsx`
- Modify: `web/src/pages/Profiles/Builder.test.tsx`

- [ ] **Step 1: Write the failing Builder runtime test**

Extend `web/src/pages/Profiles/Builder.test.tsx`:

```tsx
it('renders runtime status and screenshot previews', async () => {
  renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })

  expect(await screen.findByText('Current Step')).toBeInTheDocument()
  expect(screen.getByText('capture_editing')).toBeInTheDocument()
  expect(screen.getByText('Recent Screens')).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the Builder test to verify it fails**

Run:
```bash
cd web && pnpm test -- Builder.test.tsx
```

Expected: FAIL because the runtime panel does not exist.

- [ ] **Step 3: Add runtime polling and render the observability UI**

In `web/src/pages/Profiles/Builder.tsx`:

```tsx
const runtime = useProfileBuilderRuntime(
  session?.id,
  !!session && ['running', 'validating'].includes(session.status),
)
```

Render a top status card:

```tsx
<Card title="Runtime Status">
  <Descriptions column={1} size="small">
    <Descriptions.Item label="Current Step">
      {runtime.data?.current_step ?? '-'}
    </Descriptions.Item>
    <Descriptions.Item label="Step State">
      {runtime.data?.step_state ?? '-'}
    </Descriptions.Item>
    <Descriptions.Item label="Session Status">
      {runtime.data?.session_status ?? '-'}
    </Descriptions.Item>
  </Descriptions>
  {runtime.data?.last_error ? (
    <Alert type="error" message={runtime.data.last_error} />
  ) : null}
</Card>
```

Render step timeline:

```tsx
<Card title="Step Timeline">
  <Steps
    direction="vertical"
    items={[
      ...runtime.data?.captures.map((capture) => ({
        title: `Capture ${capture.step}`,
        description: capture.status,
        status:
          capture.status === 'done'
            ? 'finish'
            : capture.status === 'failed'
              ? 'error'
              : capture.status === 'running'
                ? 'process'
                : 'wait',
      })) ?? [],
      {
        title: 'Run Connectivity Test',
        description: runtime.data?.connectivity.status ?? 'idle',
        status:
          runtime.data?.connectivity.status === 'done'
            ? 'finish'
            : runtime.data?.connectivity.status === 'failed'
              ? 'error'
              : runtime.data?.connectivity.status === 'running'
                ? 'process'
                : 'wait',
      },
    ]}
  />
</Card>
```

Render current screenshot and recent history:

```tsx
<Card title="Recent Screens">
  {runtime.data?.recent_screens.length ? (
    <Space direction="vertical" style={{ width: '100%' }}>
      {runtime.data.recent_screens.map((screen) => (
        <Card key={`${screen.step}-${screen.label}`} size="small">
          <Typography.Text strong>{screen.label}</Typography.Text>
          <div>{screen.step}</div>
          <div>{screen.path}</div>
        </Card>
      ))}
    </Space>
  ) : (
    <Empty description="No runtime screens yet" />
  )}
</Card>
```

- [ ] **Step 4: Run the Builder test**

Run:
```bash
cd web && pnpm test -- Builder.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx
git commit -m "feat(profile-builder): render runtime observability panel"
```

---

### Task 6: Verify the observability MVP end to end

**Files:**
- Modify: `README.md` if operator notes need a follow-up line for runtime visibility
- No new production files required if docs remain sufficient

- [ ] **Step 1: Run backend observability tests**

Run:
```bash
python3.11 -m pytest tests/unit/test_profile_builder_runtime.py tests/integration/test_profile_builder_endpoints.py -v
```

Expected: PASS.

- [ ] **Step 2: Run frontend Builder tests**

Run:
```bash
cd web && pnpm test -- Builder.test.tsx profileBuilderRuntime.test.ts
```

Expected: PASS.

- [ ] **Step 3: Run lint and build**

Run:
```bash
python3.11 -m ruff check src/autoagent/api/profile_builder.py src/autoagent/models/api.py
cd web && pnpm build
```

Expected: both commands exit 0.

- [ ] **Step 4: Commit any final doc or polish changes**

```bash
git add README.md src/autoagent/models/api.py src/autoagent/api/profile_builder.py tests/unit/test_profile_builder_runtime.py tests/integration/test_profile_builder_endpoints.py web/src/types/api.ts web/src/api/profileBuilderRuntime.ts web/src/api/profileBuilderRuntime.test.ts web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx
git commit -m "feat(profile-builder): add runtime observability"
```

---

## Self-Review

Spec coverage:

- runtime snapshot artifact: Task 1
- runtime GET endpoint: Task 2
- capture step visibility: Task 2
- connectivity state and key screenshots: Task 3
- frontend polling and display: Tasks 4 to 5
- final verification: Task 6

Placeholder scan:

- no `TODO` or `TBD` placeholders remain
- each task includes concrete files, code, commands, and expected outcomes

Type consistency:

- backend uses `ProfileBuilderRuntimeView` across persistence and endpoint response
- frontend uses `ProfileBuilderRuntimeView` for polling and rendering
- builder endpoint path stays `/api/v1/profile-builder/sessions/{id}/runtime`
