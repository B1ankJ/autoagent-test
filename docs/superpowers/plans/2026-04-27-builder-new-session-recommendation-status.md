# Builder New Session Recommendation Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Builder new-session panel clearly distinguish `VLM` unavailable, recommendation failure, and recommendation ready states, while preserving manual point selection and the existing `tap_xy` flow.

**Architecture:** Add an explicit recommendation state to each guided new-session step, populate it during capture on the backend, and render it directly in the Builder UI. The backend remains the source of truth for whether recommendation is unavailable or failed; the frontend only renders the status and keeps manual override available whenever a screenshot exists.

**Tech Stack:** FastAPI, Pydantic, SQLite storage, React, TypeScript, Ant Design, Vitest, pytest.

**Status (2026-04-27):** Complete. Backend recommendation states, Builder UI rendering, tests, and smoke notes are implemented. Commits: `f353f1d`, `d4065fe`, `d93549b7`.

---

### Task 1: Add explicit recommendation state to new-session step models and backend capture flow

**Files:**
- Modify: `src/autoagent/models/api.py:153-203`
- Modify: `src/autoagent/executors/profile_builder_new_session.py:1-140`
- Modify: `src/autoagent/api/profile_builder.py:160-220, 1120-1215`
- Test: `tests/integration/test_profile_builder_new_session_endpoints.py`

- [x] **Step 1: Write the failing backend tests**

Add three focused integration tests that assert the new recommendation states:

```python
async def test_new_session_capture_marks_unavailable_without_vlm(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    response = await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    step = body["new_session_steps"][0]
    assert step["recommended_tap"]["status"] == "unavailable"
    assert step["recommendation_error"] == "vlm_unavailable"
```

```python
async def test_new_session_capture_marks_failed_on_provider_error(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_kwargs: (_ for _ in ()).throw(
            profile_builder_new_session.RecommendationProviderError("auth failed")
        ),
    )
    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    step = body["new_session_steps"][0]
    assert step["recommended_tap"]["status"] == "failed"
    assert step["recommendation_error"] == "auth_error"
```

```python
async def test_new_session_capture_marks_ready_on_success(client, monkeypatch):
    headers, session = await _create_builder_session_with_captures(client, monkeypatch)
    await client.put(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/config",
        json={"strategy": "guided_tap_sequence", "step_count": 1},
        headers=headers,
    )
    monkeypatch.setattr(
        "autoagent.executors.profile_builder_new_session.recommend_tap_point",
        lambda **_kwargs: {"x": 111, "y": 222, "reason": "plus button"},
    )
    response = await client.post(
        f"/api/v1/profile-builder/sessions/{session['id']}/new-session/step/0/capture",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    step = body["new_session_steps"][0]
    assert step["recommended_tap"]["status"] == "ready"
    assert step["recommended_tap"]["point"] == {"x": 111, "y": 222}
    assert step["recommended_tap"]["reason"] == "plus button"
    assert step["recommendation_error"] is None
```

- [x] **Step 2: Run the focused backend tests and confirm they fail on the current coarse state**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "new_session_capture" -v
```

Expected:
- the tests fail because the current state only distinguishes `idle`, `ready`, and `failed`
- the backend has no explicit `recommendation_error` field yet

- [x] **Step 3: Implement the minimal backend state changes**

Update the model and capture flow so each step carries a stable recommendation state:

```python
class ProfileBuilderNewSessionRecommendation(BaseModel):
    point: ProfileBuilderTapPoint | None = None
    reason: str | None = None
    status: Literal["idle", "ready", "unavailable", "failed"] = "idle"
    error: str | None = None
```

```python
def _classify_recommendation_error(message: str) -> str:
    lower = message.lower()
    if "401" in lower or "403" in lower or "auth" in lower:
        return "auth_error"
    if "timeout" in lower:
        return "connect_error"
    if "404" in lower or "model" in lower:
        return "model_error"
    return "response_shape_error"
```

```python
if not _has_vlm_config(vlm):
    step["recommended_tap"] = {
        "point": None,
        "reason": None,
        "status": "unavailable",
        "error": "vlm_unavailable",
    }
else:
    try:
        recommendation = await asyncio.to_thread(
            profile_builder_new_session.recommend_tap_point,
            screenshot_path=captured.screenshot_path,
            xml_text=xml_text,
            step_index=step_index,
            step_count=step_count,
            vlm=vlm,
        )
    except profile_builder_new_session.RecommendationProviderError as exc:
        step["recommended_tap"] = {
            "point": None,
            "reason": None,
            "status": "failed",
            "error": _classify_recommendation_error(str(exc)),
        }
    else:
        step["recommended_tap"] = {
            "point": {"x": recommendation["x"], "y": recommendation["y"]},
            "reason": recommendation["reason"],
            "status": "ready",
            "error": None,
        }
```

- [x] **Step 4: Run the backend tests again and verify the new recommendation states pass**

Run:

```bash
uv run pytest tests/integration/test_profile_builder_new_session_endpoints.py -k "new_session_capture" -v
```

Expected:
- `unavailable`, `failed`, and `ready` assertions pass
- existing manual confirmation tests still serialize `new_session_action`

- [x] **Step 5: Commit**

```bash
git add src/autoagent/models/api.py src/autoagent/executors/profile_builder_new_session.py src/autoagent/api/profile_builder.py tests/integration/test_profile_builder_new_session_endpoints.py
git commit -m "feat(profile-builder): add new session recommendation states"
```

### Task 2: Render recommendation availability and failure reasons in the Builder UI

**Files:**
- Modify: `web/src/pages/Profiles/Builder.tsx:230-1010`
- Modify: `web/src/pages/Profiles/Builder.test.tsx:1640-1835`
- Modify: `web/src/types/api.ts:158-188`

- [x] **Step 1: Write the failing frontend tests**

Add two focused UI tests that assert the new messages and button behavior:

```tsx
it('shows unavailable when VLM is missing', async () => {
  useVlmMock.mockImplementation(
    () => ({ data: { base_url: null, model: null, api_key: null } } as never),
  )
  const draftBase = {
    session: {
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: [],
      captures: [],
    },
    candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
    review_items: [],
    draft_profile_yaml: '',
    draft_mode: 'rule',
    requires_manual_review: true,
    applied_review_choices: {},
    pending_review_fields: [],
    auto_review_source: 'manual',
  }
  configureNewSessionMock.mockResolvedValue({
    ...draftBase,
    new_session_strategy: 'guided_tap_sequence',
    new_session_steps: [
      {
        step_index: 0,
        xml_artifact: null,
        screenshot_artifact: 'new_session_step_0.png',
        recommended_tap: { point: null, reason: null, status: 'unavailable', error: 'vlm_unavailable' },
        confirmed_tap: null,
        source: null,
        recommendation_error: 'vlm_unavailable',
      },
    ],
  })

  renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
  await userEvent.click(screen.getByRole('combobox'))
  await userEvent.click(await screen.findByText('Pixel 8'))
  await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
  await userEvent.click(await screen.findByLabelText('配置多步新开对话'))

  expect(await screen.findByText('当前未配置 VLM，仅支持人工点选')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '接受推荐' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '重新点选' })).toBeEnabled()
})
```

```tsx
it('shows recommendation failure reason when provider fails', async () => {
  const draftBase = {
    session: {
      id: 'pb_1',
      platform: 'android',
      device_serial: 'serial-1',
      name: 'qwen_android',
      status: 'draft',
      steps: ['idle', 'editing'],
      artifact_dir: '/tmp/pb_1',
      artifacts: [],
      captures: [],
    },
    candidates: { input_locator: [], input_focus_action: [], send_action: [], latest_bubble_match: [] },
    review_items: [],
    draft_profile_yaml: '',
    draft_mode: 'rule',
    requires_manual_review: true,
    applied_review_choices: {},
    pending_review_fields: [],
    auto_review_source: 'manual',
  }
  configureNewSessionMock.mockResolvedValue({
    ...draftBase,
    new_session_strategy: 'guided_tap_sequence',
    new_session_steps: [
      {
        step_index: 0,
        xml_artifact: null,
        screenshot_artifact: 'new_session_step_0.png',
        recommended_tap: { point: null, reason: null, status: 'failed', error: 'auth_error' },
        confirmed_tap: null,
        source: null,
        recommendation_error: 'auth_error',
      },
    ],
  })

  renderWithProviders(<Builder />, { initialPath: '/profiles/builder' })
  await userEvent.click(screen.getByRole('combobox'))
  await userEvent.click(await screen.findByText('Pixel 8'))
  await userEvent.click(screen.getByRole('button', { name: /Start Builder Session/ }))
  await userEvent.click(await screen.findByLabelText('配置多步新开对话'))

  expect(await screen.findByText('推荐请求失败：认证失败')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '接受推荐' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '重新点选' })).toBeEnabled()
})
```

- [x] **Step 2: Run the focused frontend tests and confirm the current UI still only understands the coarse status**

Run:

```bash
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx -t "new session"
```

Expected:
- the tests fail until the Builder step card can render `unavailable` and the error reason

- [x] **Step 3: Implement the minimal UI state rendering**

Update the step card rendering so it uses both `recommended_tap.status` and `recommended_tap.error`:

```tsx
function formatRecommendationError(error?: string | null) {
  switch (error) {
    case 'vlm_unavailable':
      return 'VLM 未配置'
    case 'auth_error':
      return '认证失败'
    case 'connect_error':
      return '连接失败'
    case 'model_error':
      return '模型不可用'
    case 'response_shape_error':
      return '返回格式异常'
    default:
      return error || '未知错误'
  }
}
```

```tsx
const recommendationMessage =
  step.recommended_tap.status === 'unavailable'
    ? '当前未配置 VLM，仅支持人工点选'
    : step.recommended_tap.status === 'failed'
      ? `推荐请求失败：${formatRecommendationError(step.recommended_tap.error)}`
      : step.recommended_tap.status === 'ready'
        ? `推荐点: (${step.recommended_tap.point?.x}, ${step.recommended_tap.point?.y})${step.recommended_tap.reason ? ` — ${step.recommended_tap.reason}` : ''}`
        : '尚未 Capture，暂无推荐'
```

```tsx
<Button
  size="small"
  disabled={step.recommended_tap.status !== 'ready' || !step.recommended_tap.point}
  onClick={() => void handleAcceptRecommendedTap(step)}
>
  接受推荐
</Button>
```

```tsx
<Button
  size="small"
  onClick={() => setManualTapStepIndex(
    manualTapStepIndex === step.step_index ? null : step.step_index
  )}
  disabled={!step.screenshot_artifact}
>
  {manualTapStepIndex === step.step_index ? '取消点选' : '重新点选'}
</Button>
```

- [x] **Step 4: Run the frontend tests and build**

Run:

```bash
pnpm --dir web exec vitest run src/pages/Profiles/Builder.test.tsx
pnpm --dir web lint
pnpm --dir web build
```

Expected:
- Builder tests pass
- lint passes
- build passes

- [x] **Step 5: Commit**

```bash
git add web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/Builder.test.tsx web/src/types/api.ts
git commit -m "feat(web): clarify new session recommendation states"
```

### Task 3: Refresh plan notes and smoke guidance to match the new recommendation states

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md`

- [x] **Step 1: Update the smoke guide with the new UI expectations**

Add the following note to the manual smoke doc:

```md
- If `VLM` is not configured, the new-session step should show `当前未配置 VLM，仅支持人工点选`.
- If recommendation fails, the step should show `推荐请求失败：<reason>`.
- In both states, manual point selection must still work when the screenshot exists.
```

- [x] **Step 2: Update the working notes in CLAUDE.md**

Add a short note that the new-session panel now distinguishes `unavailable` and `failed` recommendation states, and that users should not need to click `重新点选` just to discover missing configuration.

- [x] **Step 3: Commit the documentation updates**

```bash
git add CLAUDE.md docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md
git commit -m "docs: update new session recommendation notes"
```
