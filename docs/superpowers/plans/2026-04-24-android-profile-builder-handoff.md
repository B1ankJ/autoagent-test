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
input_locator:
  type: xpath
  value: //*[@class="android.widget.EditText"]
new_session_action:
  - action: tap_xy
    x: 477
    y: 2094
send_button_locator:
  type: xpath
  value: //*[@bounds="[909,1291][1020,1402]"]
```

The exact coordinates can differ by device, app state, and review choice. The important rule is that `new_session_action` may use an idle-state tap target, while `input_locator` must represent the runtime editing control when available.

## Verification Commands

Targeted checks that passed after the latest fixes:

```bash
python3.11 -m pytest tests/unit/test_android_input.py -q
python3.11 -m pytest tests/unit/test_android_executor_unit.py tests/unit/test_android_input.py -q
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -k 'generate_draft' -q
```

Known caveats:

- Full `tests/integration/test_profile_builder_endpoints.py -q` has hung in later tests during recent local runs. Do not claim the full integration file is green until this is reproduced and fixed.
- `tests/unit/test_profile_builder_candidates.py::test_build_android_candidates_emits_detailed_review_item_for_ambiguous_response_hints` has a current data-contract mismatch around evidence fields (`container_locator` expectation versus current `locator` / `scroll_locator` structure). Treat this as an open cleanup item.

## Current Blockers

1. Fresh real-device retest is still pending after `67e07d8`.
2. Confirm ADB Keyboard broadcast reaches the device during Chinese input. Watch the device for the ADB Keyboard toast and check executor logs.
3. If input still fails, inspect the newest `data/profile_builder/<session_id>/connectivity_result.json`, runtime screenshots, and `data/logs/<batch_id>/<sample_id>/executor.log`.
4. Send-button candidate ranking is improved but still human-review dependent. Keep the review step; do not assume the first recommendation is always correct.
5. Response extraction review evidence is present, but the UI can still be made clearer for non-developers.
6. Resolve the `container_locator` review-evidence test mismatch before claiming the backend unit suite is fully green.
7. Investigate the full profile-builder endpoint suite hang before release tagging.

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
