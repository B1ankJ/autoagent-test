# Builder New Session Action Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guided Builder flow that produces `new_session_action` as a confirmed multi-step `tap_xy` sequence from pre-tap captures, with AI recommendation plus manual override.

**Architecture:** Extend the existing Profile Builder session/draft pipeline with a dedicated `new_session_action` sub-state instead of mixing this feature into generic review items. The backend will persist per-step capture and recommendation state, serialize confirmed taps into draft YAML, and expose the state through the existing Builder draft/session responses. The frontend Builder page will render a separate multi-step authoring panel that captures each step, previews the recommended point, and lets the user accept or override it.

**Tech Stack:** FastAPI, Pydantic, existing Profile Builder runtime/session persistence, React, Ant Design, Vitest, pytest

---

## File Structure

**Backend**

- Modify: `src/autoagent/models/api.py`
  - Extend Profile Builder API models with `new_session_action` Builder state, step capture state, and recommendation state.
- Modify: `src/autoagent/api/profile_builder.py`
  - Persist the new-session Builder state in session artifacts, add capture/update endpoints, integrate confirmed taps into generated draft YAML, and keep runtime observability consistent.
- Create: `src/autoagent/executors/profile_builder_new_session.py`
  - Isolate single-step recommendation request/response shaping and `tap_xy` confirmation helpers so the logic does not bloat `profile_builder.py`.
- Test: `tests/integration/test_profile_builder_new_session_endpoints.py`
  - Cover the API contract, state transitions, YAML serialization, and AI-failure fallback.

**Frontend**

- Modify: `web/src/types/api.ts`
  - Add types for the new-session Builder strategy, per-step capture state, recommendation, and update payloads.
- Modify: `web/src/api/profileBuilder.ts`
  - Add hooks for per-step capture/update actions if they are implemented as dedicated endpoints.
- Modify: `web/src/pages/Profiles/Builder.tsx`
  - Render strategy selection, step count control, guided step capture cards, recommendation preview, image override interaction, and draft integration.
- Modify: `web/src/pages/Profiles/Builder.test.tsx`
  - Add UI tests for strategy toggle, step capture flow, accepting recommendations, manual override, and YAML updates.

**Docs**

- Modify: `CLAUDE.md`
  - Document the new Builder semantics for authoring `new_session_action`.
- Modify: `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md`
  - Add manual smoke steps for one-step and two-step `new_session_action` authoring.

---

### Task 1: Add backend models for Builder new-session state

**Files:**
- Create: `tests/integration/test_profile_builder_new_session_endpoints.py`
- Modify: `src/autoagent/models/api.py`

- [ ] **Step 1: Write the failing backend model contract test**

```python
def test_generate_draft_includes_empty_new_session_builder_state(client, session_id):
    response = client.post(
        f"/api/v1/profile-builder/sessions/{session_id}/draft",
        json={"draft_mode": "rule", "inject_llm": False},
    )
    body = response.json()
    assert body["new_session_strategy"] == "disabled"
    assert body["new_session_steps"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py::test_generate_draft_includes_empty_new_session_builder_state -v
```

Expected: FAIL because the response model does not yet expose `new_session_strategy` or `new_session_steps`.

- [ ] **Step 3: Extend Profile Builder API models**

Add focused Pydantic models in `src/autoagent/models/api.py` near the existing `ProfileBuilder*` types:

```python
class ProfileBuilderTapPoint(BaseModel):
    x: int
    y: int


class ProfileBuilderNewSessionRecommendation(BaseModel):
    point: ProfileBuilderTapPoint | None = None
    reason: str | None = None
    status: Literal["idle", "ready", "failed"] = "idle"


class ProfileBuilderNewSessionStep(BaseModel):
    step_index: int
    xml_artifact: str | None = None
    screenshot_artifact: str | None = None
    recommended_tap: ProfileBuilderNewSessionRecommendation = Field(
        default_factory=ProfileBuilderNewSessionRecommendation
    )
    confirmed_tap: ProfileBuilderTapPoint | None = None
    source: Literal["recommended", "manual"] | None = None


class ProfileBuilderDraftResponse(BaseModel):
    ...
    new_session_strategy: Literal["disabled", "guided_tap_sequence"] = "disabled"
    new_session_steps: list[ProfileBuilderNewSessionStep] = Field(default_factory=list)
```

Also add request models for future update endpoints:

```python
class ProfileBuilderNewSessionConfigRequest(BaseModel):
    strategy: Literal["disabled", "guided_tap_sequence"]
    step_count: int = Field(default=0, ge=0, le=3)


class ProfileBuilderNewSessionConfirmRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    source: Literal["recommended", "manual"]
```

- [ ] **Step 4: Run test to verify it still fails at serialization call sites**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py::test_generate_draft_includes_empty_new_session_builder_state -v
```

Expected: FAIL later in the request path because draft generation code does not populate the new fields yet.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/models/api.py tests/integration/test_profile_builder_new_session_endpoints.py
git commit -m "feat(profile_builder): add new session builder api models"
```

### Task 2: Persist Builder new-session state in session and draft responses

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Test: `tests/integration/test_profile_builder_new_session_endpoints.py`

- [ ] **Step 1: Add failing persistence tests**

Add tests that define the session/draft defaults and step-count changes:

```python
def test_new_session_config_initializes_requested_steps(client, session_id):
    response = client.put(
        f"/api/v1/profile-builder/sessions/{session_id}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 2},
    )
    body = response.json()
    assert body["new_session_strategy"] == "guided_tap_sequence"
    assert [step["step_index"] for step in body["new_session_steps"]] == [0, 1]


def test_new_session_config_truncates_higher_steps(client, session_id):
    client.put(
        f"/api/v1/profile-builder/sessions/{session_id}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 3},
    )
    response = client.put(
        f"/api/v1/profile-builder/sessions/{session_id}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
    )
    body = response.json()
    assert len(body["new_session_steps"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "config_initializes_requested_steps or config_truncates_higher_steps" -v
```

Expected: FAIL because the endpoints and session state do not exist.

- [ ] **Step 3: Add new-session session state helpers and config endpoint**

In `src/autoagent/api/profile_builder.py`, add small helpers:

```python
def _new_session_state(session: ProfileBuilderSessionView) -> dict[str, Any]:
    state = getattr(session, "new_session_state", None)
    if isinstance(state, dict):
        return state
    return {"strategy": "disabled", "steps": []}


def _resize_new_session_steps(steps: list[dict[str, Any]], step_count: int) -> list[dict[str, Any]]:
    next_steps = steps[:step_count]
    while len(next_steps) < step_count:
        next_steps.append(
            {
                "step_index": len(next_steps),
                "xml_artifact": None,
                "screenshot_artifact": None,
                "recommended_tap": {"point": None, "reason": None, "status": "idle"},
                "confirmed_tap": None,
                "source": None,
            }
        )
    return next_steps
```

Add endpoint:

```python
@router.put("/sessions/{session_id}/new-session/config", response_model=ProfileBuilderDraftResponse)
async def configure_new_session(session_id: str, body: ProfileBuilderNewSessionConfigRequest) -> ProfileBuilderDraftResponse:
    ...
```

When the strategy is disabled, clear steps and keep draft YAML serialization at `new_session_action: []`.

- [ ] **Step 4: Thread the state through draft responses**

When building the existing draft response body, include:

```python
"new_session_strategy": state["strategy"],
"new_session_steps": state["steps"],
```

If no draft exists yet, return the same fields from the configured session state so the UI can render the panel before final YAML is complete.

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "config_initializes_requested_steps or config_truncates_higher_steps" -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/api/profile_builder.py tests/integration/test_profile_builder_new_session_endpoints.py
git commit -m "feat(profile_builder): persist new session builder state"
```

### Task 3: Add per-step capture and recommendation backend flow

**Files:**
- Create: `src/autoagent/executors/profile_builder_new_session.py`
- Modify: `src/autoagent/api/profile_builder.py`
- Test: `tests/integration/test_profile_builder_new_session_endpoints.py`

- [ ] **Step 1: Add failing capture/recommendation tests**

```python
def test_capture_new_session_step_records_artifacts_and_recommendation(client, session_id, monkeypatch):
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_: {"x": 111, "y": 222, "reason": "plus button"},
    )
    client.put(
        f"/api/v1/profile-builder/sessions/{session_id}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
    )
    response = client.post(
        f"/api/v1/profile-builder/sessions/{session_id}/new-session/step/0/capture"
    )
    body = response.json()
    assert body["new_session_steps"][0]["screenshot_artifact"].endswith(".png")
    assert body["new_session_steps"][0]["recommended_tap"]["point"] == {"x": 111, "y": 222}
    assert body["new_session_steps"][0]["recommended_tap"]["status"] == "ready"
```

Add fallback test:

```python
def test_capture_new_session_step_handles_recommendation_failure(client, session_id, monkeypatch):
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_: (_ for _ in ()).throw(RuntimeError("vlm unavailable")),
    )
    ...
    assert body["new_session_steps"][0]["recommended_tap"]["status"] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "capture_new_session_step" -v
```

Expected: FAIL because the executor helper and capture endpoint do not exist.

- [ ] **Step 3: Add isolated step recommendation helper**

Create `src/autoagent/executors/profile_builder_new_session.py` with a small API:

```python
def recommend_tap_point(
    *,
    screenshot_path: Path,
    xml_text: str,
    step_index: int,
    step_count: int,
    vlm: VLMConfig | None,
) -> dict[str, Any]:
    if vlm is None or not (vlm.base_url and vlm.model and vlm.api_key):
        raise RuntimeError("vlm unavailable")
    return {"x": 0, "y": 0, "reason": "placeholder"}
```

The initial implementation can be thin and only shape the request/response contract used by the tests. Do not mix the logic into `profile_builder.py`.

- [ ] **Step 4: Add step capture endpoint and recommendation persistence**

In `profile_builder.py`, add:

```python
@router.post("/sessions/{session_id}/new-session/step/{step_index}/capture", response_model=ProfileBuilderDraftResponse)
async def capture_new_session_step(session_id: str, step_index: int) -> ProfileBuilderDraftResponse:
    ...
```

Implementation rules:

- capture the current Android state using the same device/session context as existing Builder capture
- write `new_session_step_{n}.xml` and `new_session_step_{n}.png`
- save those artifact names into the step record
- call `recommend_tap_point(...)`
- on success set:

```python
step["recommended_tap"] = {
    "point": {"x": rec["x"], "y": rec["y"]},
    "reason": rec["reason"],
    "status": "ready",
}
```

- on failure set:

```python
step["recommended_tap"] = {"point": None, "reason": None, "status": "failed"}
```

- clear any stale `confirmed_tap` when a step is recaptured

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "capture_new_session_step" -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/executors/profile_builder_new_session.py src/autoagent/api/profile_builder.py tests/integration/test_profile_builder_new_session_endpoints.py
git commit -m "feat(profile_builder): add new session step capture flow"
```

### Task 4: Confirm or override step taps and write them into draft YAML

**Files:**
- Modify: `src/autoagent/api/profile_builder.py`
- Test: `tests/integration/test_profile_builder_new_session_endpoints.py`

- [ ] **Step 1: Add failing confirmation and YAML tests**

```python
def test_confirm_new_session_step_writes_tap_xy_into_draft_yaml(client, session_id):
    client.put(
        f"/api/v1/profile-builder/sessions/{session_id}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
    )
    response = client.put(
        f"/api/v1/profile-builder/sessions/{session_id}/new-session/step/0/confirm",
        json={"x": 321, "y": 654, "source": "manual"},
    )
    body = response.json()
    assert body["new_session_steps"][0]["confirmed_tap"] == {"x": 321, "y": 654}
    assert "new_session_action:" in body["draft_profile_yaml"]
    assert "x: 321" in body["draft_profile_yaml"]
    assert "y: 654" in body["draft_profile_yaml"]
```

Add disable-case test:

```python
def test_disable_new_session_strategy_clears_yaml_sequence(client, session_id):
    ...
    assert "new_session_action: []" in body["draft_profile_yaml"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "confirm_new_session_step or disable_new_session_strategy" -v
```

Expected: FAIL because the confirmation endpoint and YAML integration do not exist.

- [ ] **Step 3: Add step confirmation endpoint**

In `profile_builder.py`, add:

```python
@router.put("/sessions/{session_id}/new-session/step/{step_index}/confirm", response_model=ProfileBuilderDraftResponse)
async def confirm_new_session_step(
    session_id: str,
    step_index: int,
    body: ProfileBuilderNewSessionConfirmRequest,
) -> ProfileBuilderDraftResponse:
    ...
```

Persist:

```python
step["confirmed_tap"] = {"x": body.x, "y": body.y}
step["source"] = body.source
```

- [ ] **Step 4: Extract YAML serialization helper**

Add a helper that derives the final profile field from confirmed taps:

```python
def _serialize_new_session_action(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"action": "tap_xy", "x": step["confirmed_tap"]["x"], "y": step["confirmed_tap"]["y"]}
        for step in steps
        if step.get("confirmed_tap")
    ]
```

When rewriting the draft YAML, apply:

```python
draft_profile["new_session_action"] = _serialize_new_session_action(state["steps"])
```

If the strategy is disabled, force:

```python
draft_profile["new_session_action"] = []
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "confirm_new_session_step or disable_new_session_strategy" -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/api/profile_builder.py tests/integration/test_profile_builder_new_session_endpoints.py
git commit -m "feat(profile_builder): serialize new session tap sequence"
```

### Task 5: Add frontend types and API hooks for guided new-session authoring

**Files:**
- Modify: `web/src/types/api.ts`
- Modify: `web/src/api/profileBuilder.ts`
- Test: `web/src/pages/Profiles/Builder.test.tsx`

- [ ] **Step 1: Add failing frontend API-flow test**

Add one UI test that proves the page calls the new config endpoint:

```tsx
it('configures guided new session step count before capture', async () => {
  renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
  await userEvent.click(screen.getByLabelText('配置多步新开对话'))
  await userEvent.selectOptions(screen.getByLabelText('Step Count'), '2')
  expect(configureNewSessionMock).toHaveBeenCalledWith({
    sessionId: 'pb_1',
    strategy: 'guided_tap_sequence',
    stepCount: 2,
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx -t "configures guided new session step count before capture"
```

Expected: FAIL because the types and hook do not exist.

- [ ] **Step 3: Add frontend types**

In `web/src/types/api.ts`, mirror the backend contract:

```ts
export interface ProfileBuilderTapPoint {
  x: number
  y: number
}

export interface ProfileBuilderNewSessionRecommendation {
  point: ProfileBuilderTapPoint | null
  reason: string | null
  status: 'idle' | 'ready' | 'failed'
}

export interface ProfileBuilderNewSessionStep {
  step_index: number
  xml_artifact: string | null
  screenshot_artifact: string | null
  recommended_tap: ProfileBuilderNewSessionRecommendation
  confirmed_tap: ProfileBuilderTapPoint | null
  source: 'recommended' | 'manual' | null
}
```

Extend `ProfileBuilderDraftResponse` with:

```ts
new_session_strategy: 'disabled' | 'guided_tap_sequence'
new_session_steps: ProfileBuilderNewSessionStep[]
```

- [ ] **Step 4: Add API hooks**

In `web/src/api/profileBuilder.ts`, add small wrappers:

```ts
export function useConfigureProfileBuilderNewSession() { ... }
export function useCaptureProfileBuilderNewSessionStep() { ... }
export function useConfirmProfileBuilderNewSessionStep() { ... }
```

Each should call the new backend routes and return `ProfileBuilderDraftResponse`.

- [ ] **Step 5: Run targeted test to verify the new imports compile**

Run:

```bash
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx -t "configures guided new session step count before capture"
```

Expected: FAIL later in the page logic because the UI still does not render the controls.

- [ ] **Step 6: Commit**

```bash
git add web/src/types/api.ts web/src/api/profileBuilder.ts web/src/pages/Profiles/Builder.test.tsx
git commit -m "feat(web): add new session builder api types"
```

### Task 6: Build the guided new-session panel in Builder

**Files:**
- Modify: `web/src/pages/Profiles/Builder.tsx`
- Test: `web/src/pages/Profiles/Builder.test.tsx`

- [ ] **Step 1: Add failing UI interaction tests**

Add tests for the core interactions:

```tsx
it('renders guided new session steps when strategy is enabled', async () => {
  ...
  expect(await screen.findByText('New Session Step 1')).toBeInTheDocument()
})

it('accepts the recommended tap for one step', async () => {
  ...
  await userEvent.click(screen.getByRole('button', { name: '接受推荐' }))
  expect(confirmNewSessionStepMock).toHaveBeenCalledWith({
    sessionId: 'pb_1',
    stepIndex: 0,
    x: 111,
    y: 222,
    source: 'recommended',
  })
})
```

Add manual override test:

```tsx
it('allows manual override on the step image', async () => {
  ...
  await userEvent.click(screen.getByRole('button', { name: '重新点选' }))
  await userEvent.click(stepImage, { clientX: 300, clientY: 500 })
  expect(confirmNewSessionStepMock).toHaveBeenCalledWith({
    sessionId: 'pb_1',
    stepIndex: 0,
    x: expect.any(Number),
    y: expect.any(Number),
    source: 'manual',
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx -t "guided new session|recommended tap|manual override"
```

Expected: FAIL because the panel is not yet rendered.

- [ ] **Step 3: Add local Builder state and strategy controls**

In `Builder.tsx`, add page state:

```tsx
const [newSessionStrategy, setNewSessionStrategy] = useState<'disabled' | 'guided_tap_sequence'>('disabled')
const [newSessionStepCount, setNewSessionStepCount] = useState(1)
const [manualTapStepIndex, setManualTapStepIndex] = useState<number | null>(null)
```

Render under Session Setup:

```tsx
<Radio.Group value={newSessionStrategy} onChange={...}>
  <Radio value="disabled">不配置</Radio>
  <Radio value="guided_tap_sequence">配置多步新开对话</Radio>
</Radio.Group>
```

When enabled, render a simple count selector and call `useConfigureProfileBuilderNewSession`.

- [ ] **Step 4: Render per-step cards**

For each `draft?.new_session_steps`, render:

```tsx
<Card title={`New Session Step ${step.step_index + 1}`}>
  <Button onClick={() => captureNewSessionStep.mutateAsync({ sessionId, stepIndex: step.step_index })}>
    Capture
  </Button>
  <Tag>{step.confirmed_tap ? '已确认' : '待确认'}</Tag>
  <Button onClick={() => acceptRecommended(step)} disabled={!step.recommended_tap.point}>
    接受推荐
  </Button>
  <Button onClick={() => setManualTapStepIndex(step.step_index)}>重新点选</Button>
</Card>
```

If recommendation failed, show:

```tsx
<Alert type="warning" message="需人工点选" />
```

- [ ] **Step 5: Add manual point override on the preview image**

Reuse the existing preview image area. When a step is in manual mode:

```tsx
onClick={(event) => {
  if (manualTapStepIndex == null) return
  const rect = event.currentTarget.getBoundingClientRect()
  const x = Math.round(((event.clientX - rect.left) / rect.width) * imageNaturalSize.width)
  const y = Math.round(((event.clientY - rect.top) / rect.height) * imageNaturalSize.height)
  void confirmNewSessionStep.mutateAsync({ sessionId, stepIndex: manualTapStepIndex, x, y, source: 'manual' })
}}
```

Show the confirmed point overlay with a distinct color so the user sees what will be written into YAML.

- [ ] **Step 6: Run targeted tests to verify they pass**

Run:

```bash
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx -t "guided new session|recommended tap|manual override"
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx
git commit -m "feat(web): add guided new session builder flow"
```

### Task 7: Verify YAML synchronization and final integration

**Files:**
- Modify: `web/src/pages/Profiles/Builder.test.tsx`
- Modify: `tests/integration/test_profile_builder_new_session_endpoints.py`

- [ ] **Step 1: Add final end-to-end contract tests**

Backend:

```python
def test_confirmed_steps_are_returned_in_order_in_draft_yaml(client, session_id):
    ...
    assert body["draft_profile_yaml"].count("action: tap_xy") == 2
    assert body["draft_profile_yaml"].index("x: 100") < body["draft_profile_yaml"].index("x: 200")
```

Frontend:

```tsx
it('updates Draft YAML after confirming all new session steps', async () => {
  ...
  expect(await screen.findByDisplayValue(expect.stringContaining('new_session_action:'))).toBeInTheDocument()
  expect(screen.getByDisplayValue(expect.stringContaining('x: 111'))).toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "returned_in_order_in_draft_yaml" -v
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx -t "updates Draft YAML after confirming all new session steps"
```

Expected: FAIL if any serialization or UI refresh gaps remain.

- [ ] **Step 3: Fix the minimal synchronization gaps**

Expected minimal fixes:

```python
response = {
    ...,
    "draft_profile_yaml": _write_draft_profile_yaml(session, draft_profile),
}
```

```tsx
setDraft(validatedDraftResponse)
```

Only add the missing refresh logic required to make both contract tests pass. Do not expand scope into live execution or extra review systems.

- [ ] **Step 4: Run focused tests to verify they pass**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -v
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_profile_builder_new_session_endpoints.py web/src/pages/Profiles/Builder.test.tsx src/autoagent/api/profile_builder.py web/src/pages/Profiles/Builder.tsx
git commit -m "fix(profile_builder): sync guided new session yaml state"
```

### Task 8: Update docs and run verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md`

- [ ] **Step 1: Update developer docs**

Add concise notes to `CLAUDE.md`:

```md
- Builder can author `new_session_action` through a dedicated guided tap-sequence flow.
- The flow only outputs `tap_xy`.
- Builder authoring does not execute the new-session flow; runtime still requires `sample.new_session=true`.
```

Add smoke steps to `2026-04-23-plan-4-android-manual-smoke.md`:

```md
12. New Session Action smoke
   - configure one-step flow
   - configure two-step flow
   - verify recommended point accept path
   - verify manual override path
```

- [ ] **Step 2: Run full verification**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -v
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx
pnpm --dir web lint
pnpm --dir web build
```

Expected:

- pytest: PASS
- vitest: PASS
- lint: PASS
- build: PASS

- [ ] **Step 3: Commit docs and verification-ready state**

```bash
git add CLAUDE.md docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md
git commit -m "docs: add builder new session authoring notes"
```

---

## Self-Review

### Spec coverage

- Dedicated multi-step Builder subflow: covered by Tasks 2, 3, 6
- User-declared step count: covered by Tasks 2, 5, 6
- Pre-tap captures only: covered by Task 3 and frontend flow in Task 6
- AI recommendation plus manual confirmation: covered by Tasks 3, 4, 6
- `tap_xy` only output: covered by Task 4 serialization and Task 8 docs
- Keep `new_session_action` outside generic review items: covered by Task 6 UI design
- No runtime semantic change: covered by Task 8 docs and explicit non-goals in tasks

### Placeholder scan

- No `TODO`/`TBD` placeholders remain
- Each task names exact files
- Each code-changing step includes concrete snippets or signatures
- Each verification step includes exact commands

### Type consistency

- Backend contract consistently uses `new_session_strategy` and `new_session_steps`
- Per-step output consistently uses `recommended_tap`, `confirmed_tap`, and `source`
- Frontend types mirror backend names exactly
- Final serialized runtime field remains `new_session_action`
