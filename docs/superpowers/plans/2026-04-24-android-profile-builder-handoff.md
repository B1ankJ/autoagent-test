# Android Profile Builder Handoff - 2026-04-24

This is the current handoff note for Plan 4 Android/Profile Builder work. New sessions should read this file before changing Android executor or Profile Builder behavior.

## Scope

- Worktree: `/Users/b1ankj/Desktop/2026/Q2/AutoAgentTest/.worktrees/plan4-android-executor`
- Branch: `plan4-android-executor`
- Real-device target used during debugging: `24108eff`
- Real app used during debugging: `com.aliyun.tongyi/com.ucpro.BrowserActivity`
- Main UI entry point: `/profiles/builder`

## Latest State

Plan 4 Android and Profile Builder implementation is in the repo, but final release tagging is blocked on a fresh real-device validation pass. The most recent work focused on Qwen/Tongyi Profile Builder connectivity failures caused by unstable input locators and ADB Keyboard focus timing.

Recent important commits:

- `67e07d8 fix(android): broadcast after focused adb input`
  ADB Keyboard input no longer fails just because the second/refocus click cannot resolve the input locator. If the entry action already focused the field, the executor continues to broadcast through ADB Keyboard.
- `5a76312 fix(profile-builder): keep runtime input locator`
  Draft generation no longer overwrites the runtime `EditText` input locator with the idle placeholder locator. Idle placeholder taps are kept only as `new_session_action`.
- `f49e5ef fix(profile-builder): keep review choices editable`
  Review choices remain visible/editable after applying a recommendation, and generated drafts can be saved or overwritten as normal profiles from the builder.

Current untagged workspace changes after those commits:

- Android execution keeps ADB Keyboard active for the whole sample when that input path is selected, instead of switching only around `set_text()`.
- Profile Builder now enables ADB Keyboard once at `Start Builder Session` time and restores the previous IME after `Generate Draft`.
- `Capture Editing State` is now manual-only. The user must focus the input first; the backend no longer auto-taps into editing and no longer expects the ADB Keyboard toast to appear inside `capture_editing.png`.
- Draft generation now uses only the manual `idle` and `editing` captures. The extra `runtime_probe_editing.*` artifact path has been removed.
- Android profile draft semantics are corrected so `new_session_action` means "start a new conversation", input focusing lives in `input_focus_action`, and send triggering can live in `send_action`.
- Builder review gating now blocks `Run Connectivity Test` until all generated review items are confirmed, and the UI can show all evidence boxes for a review item at once.

## How To Resume

Start from the active worktree:

```bash
cd /Users/b1ankj/Desktop/2026/Q2/AutoAgentTest/.worktrees/plan4-android-executor
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=admin_pw_1234
export JWT_SECRET=0123456789abcdef0123456789abcdef
python3.11 -m uvicorn --app-dir src autoagent.main:app --port 8000
```

Open:

```text
http://127.0.0.1:8000/profiles/builder
```

Use a fresh builder session after restarting the backend. Do not treat older failed sessions such as `pb_c618d070b477` or `pb_e44a0e2b489c` as current behavior unless you are reading them only as historical evidence.

## Current Real-Device Debug Trail

### `pb_c618d070b477`

Failure before `5a76312`:

```text
set_text start: method=adb_keyboard locator=xpath://*[contains(@text, "发消息")]
XPathElementNotFoundError: #(XPath('//*[contains(@text, "发消息")]'))
```

Root cause: draft generation used the idle placeholder as `input_locator`. That placeholder exists before editing, but can disappear once the app enters runtime input state.

Fix: `5a76312` keeps runtime input locator separate from idle entry action.

### `pb_e44a0e2b489c`

Failure before `67e07d8`:

```text
set_text start: method=adb_keyboard locator=xpath://*[@class="android.widget.EditText"]
XPathElementNotFoundError: #(XPath('//*[@class="android.widget.EditText"]'))
```

Observed screenshots showed the field had already been focused by `new_session_action`, but the second click attempted by ADB input could not resolve `EditText`, so the ADB Keyboard broadcast was never reached. The user also did not see the ADB Keyboard toast, matching this failure point.

Fix: `67e07d8` makes the refocus click best-effort and continues the broadcast path when focus was already established by the entry action.

## Expected Draft Shape For Qwen/Tongyi

The generated profile should keep separate responsibilities:

```yaml
new_session_action: []
input_focus_action:
  - action: tap_xy
    x: 477
    y: 2094
send_action:
  - action: tap_xy
    x: 964
    y: 2064
input_locator:
  type: xpath
  value: //*[@class="android.widget.EditText"]
send_button_locator:
  type: xpath
  value: //*[@bounds="[909,2009][1020,2120]"]
```

The exact coordinates can differ by device, app state, and review choice. The important rule is:

- `new_session_action` is reserved for real "new chat / reset conversation" steps.
- `input_focus_action` is the place for tapping or clicking into the input area before text entry.
- `input_locator` should represent the runtime control used by the input subsystem when possible.
- `send_action` is preferred for actually triggering send because it can capture either `tap_xy` or `click_locator`; `send_button_locator` remains useful as fallback evidence.

## Verification Commands

Targeted checks that passed after the latest fixes:

```bash
python3.11 -m pytest tests/unit/test_android_input.py -q
python3.11 -m pytest tests/unit/test_android_executor_unit.py tests/unit/test_android_input.py tests/unit/test_profile_builder_candidates.py tests/unit/test_profile_builder_capture.py -q
python3.11 -m pytest tests/unit/test_profile_builder_generator.py tests/unit/test_profiles.py -q
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py::test_profile_builder_generate_draft_persists_rule_artifacts tests/integration/test_profile_builder_endpoints.py::test_profile_builder_generate_draft_keeps_manual_editing_send_locator tests/integration/test_profile_builder_endpoints.py::test_profile_builder_review_and_validate_flow tests/integration/test_profile_builder_endpoints.py::test_profile_builder_review_updates_input_focus_action_field tests/integration/test_profile_builder_endpoints.py::test_profile_builder_validate_updates_runtime_and_screens -q
cd web && pnpm exec vitest run src/pages/Profiles/Builder.test.tsx
cd web && pnpm exec tsc --noEmit
```

Known caveats:

- Full `tests/integration/test_profile_builder_endpoints.py -q` can still feel slow in this environment; use the targeted command set above for confidence before real-device retest.

## Current Blockers

1. Fresh real-device retest is still pending after the latest manual-editing capture flow and review-evidence changes.
2. Confirm session-scoped ADB Keyboard activation behaves correctly on the real device during Chinese input. The IME toast is only expected near `Start Builder Session`; do not require it to appear in `capture_editing.png`.
3. Confirm builder-captured idle/editing states now match runtime well enough for Qwen/Tongyi on a fresh session with no extra runtime probe.
4. If connectivity still fails, inspect the newest `data/profile_builder/<session_id>/connectivity_result.json`, manual capture screenshots, and `data/logs/<batch_id>/<sample_id>/executor.log`.
5. `new_session_action` is still not auto-derived for apps like Qwen that need "open menu -> new chat"; that remains a manual review / draft-edit step.
6. Response extraction review evidence is present, but the UI can still be made clearer for non-developers.

## Useful Artifact Paths

Profile Builder artifacts:

```text
data/profile_builder/<session_id>/
```

Execution logs:

```text
data/logs/<batch_id>/<sample_or_connection_id>/executor.log
```

Recent historical examples:

```text
data/profile_builder/pb_c618d070b477
data/profile_builder/pb_e44a0e2b489c
data/logs/b_1776997363_c3c4f9/pb-validate-pb_e44a0e2b489c
```

These paths are runtime artifacts and should not be committed.
