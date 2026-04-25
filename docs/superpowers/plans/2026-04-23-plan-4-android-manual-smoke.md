# Plan 4 Android Manual Smoke Checklist

Use this checklist for the final Plan 4 real-device validation round. The goal is to confirm the
current shipped `gui_android` flow works end to end against a real Android device and a real target
app before tagging `android-executor-v0.4.0`.

## Current handoff

Before running this checklist, read:

```text
docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md
```

That file is the source of truth for the latest Android/Profile Builder status, recent fixes, and
open blockers. As of 2026-04-24, final release tagging is still blocked on one fresh real-device
retest after the latest Profile Builder, response extraction, and cleanup-flow changes landed.

## Preconditions

- Device is visible in `adb devices -l`
- USB debugging is enabled
- The target app is already installed and can be opened manually on the device
- Backend env is set: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `JWT_SECRET`
- Frontend is built and served from the same backend instance
- If the target app needs Chinese or non-ASCII input, `ADB Keyboard` is installed and enabled from
  `/devices`

Optional cleanup before the run:

```bash
cd /Users/b1ankj/Desktop/2026/Q2/AutoAgentTest/.worktrees/plan4-android-executor
python3.11 scripts/cleanup_runtime_artifacts.py --all --apply
```

Start the backend from the worktree root:

```bash
cd /Users/b1ankj/Desktop/2026/Q2/AutoAgentTest/.worktrees/plan4-android-executor
python3.11 -m uvicorn --app-dir src autoagent.main:app --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

## Step 1: Device discovery and IME readiness

1. Run `adb devices -l`
2. Open `/devices` in the web UI
3. Click `Refresh`
4. If needed, click `Install ADB Keyboard`
5. Ensure the target device shows the IME status needed for Builder use

Expected:

- At least one device is listed
- The device shows `online`
- The device shows `enabled`
- `ADB Keyboard` can be installed and enabled from the UI if the app/profile needs it

## Step 2: Build a draft Android profile with Profile Builder

Use `Profiles -> Build Profile`.

Capture flow:

1. Click `Start Builder Session`
2. Confirm the dialog only after:
   - you have manually sent one short test message
   - the target app is stopped on the real conversation page
   - one visible answer is already on screen
3. Capture `idle`
4. Manually focus the input so the true editing controls are visible
5. Capture `editing`
6. Click `Generate Draft`

Important current behavior:

- `Start Builder Session` enables `ADB Keyboard` once for the whole builder session
- `Capture Editing State` is manual-only and must not auto-focus the input
- `Generate Draft` restores the previous IME after draft generation
- Draft generation uses only `idle` and `editing` captures; there is no extra runtime probe

Expected:

- `capture_idle.*` and `capture_editing.*` appear in `data/profile_builder/<session_id>/`
- `draft_profile.yaml`, `candidates.json`, and `review_items.json` are created
- No unexpected Builder crash occurs during draft generation

## Step 3: Review Builder candidates

Review every surfaced item before running connectivity.

Current review rules:

- `input_focus_action`, `input_locator`, and `send_action` keep every bounded node as a candidate
- Backend recommendation only affects ordering; it must not hide other candidates
- `send_action` may include non-clickable visual send controls as tap-only candidates
- `latest_bubble_match` review is conditional; if the structural response anchor is already clear,
  this item may be skipped
- When `latest_bubble_match` is shown, treat it as selecting the latest response block, not one
  frozen bubble bounds box

What to check:

- The correct input focus target is present somewhere in the list
- The correct input locator is present somewhere in the list
- The correct send trigger is present somewhere in the list
- If `latest_bubble_match` is shown, the chosen option corresponds to the latest visible assistant
  response block rather than UI chrome or bottom chips

Expected:

- You can apply the intended choice for every required review item
- `Connectivity Test` stays disabled until required review items are confirmed
- The final applied choices are reflected in `draft_profile.yaml`

## Step 4: Draft connectivity validation

From the Builder page, run `Connectivity Test` with a short prompt such as:

```text
hello
```

Expected:

- Validation starts only after required review items are confirmed
- The app opens on the device if needed
- Input is sent through the reviewed `input_focus_action`, `input_locator`, and `send_action`
- A non-empty response is extracted
- For UI-tree extraction, the result follows the reviewed response container/latest response block
  instead of unrelated text such as bottom feature chips
- `connectivity_result.json` is written under `data/profile_builder/<session_id>/`

## Step 5: Save the reviewed profile

After a successful connectivity check, save the draft as a normal profile.

Expected:

- `保存` succeeds
- The saved profile can be reopened from the normal Profiles page
- The saved YAML reflects reviewed Builder choices rather than stale defaults

## Step 6: Tier 1 quick test with the saved profile

Go to `Tests / Quick` and run:

- Mode: `Android (GUI)`
- Profile: the just-saved Builder profile
- Prompt: `hello`
- Execution: `同步`

Expected:

- Result status is `done`
- Response text is non-empty
- No device-allocation error is shown
- Logs and screenshots are written for the run

## Step 7: Tier 1 batch and sample detail

Create a JSONL file:

```jsonl
{"id":"a1","prompts":["hello"],"mode":"gui_android","target_profile":"real_android_builder"}
{"id":"a2","prompts":["how are you"],"mode":"gui_android","target_profile":"real_android_builder"}
{"id":"a3","prompts":["tell me a joke"],"mode":"gui_android","target_profile":"real_android_builder"}
```

Upload it from `Batches / 新建批次`, then open one sample from the completed batch.

Expected:

- Batch starts successfully
- `BatchDetail` updates without manual refresh
- At least one sample shows `device_serial`
- Final counts match `done = 3`, `failed = 0` unless the app itself rejects a prompt
- `运行设备` is visible in SampleDetail
- Screenshot strip renders
- Action log renders when available
- `下载回放 JSONL` works when shown
- Metadata contains Android-related fields when applicable

## Step 8: Tier 2 OCR long-response validation

Create or reuse a Tier 2 profile with `response_extraction.method: ui_tree_then_ocr` or
`ocr_only`, then run a prompt that should force a response longer than one screen.

Suggested prompt:

```text
请输出一段超过两屏的长回答，分成 12 个编号段落，每段 2 到 3 句，不要省略，不要用表格。
```

Run it first in `Tests / Quick`, then optionally through a one-sample batch.

Expected:

- Request completes with `done`
- Response text spans more than one screen worth of content
- Final extracted text is longer than a short UI-tree-only snippet
- No obvious premature completion occurs while the app is still rendering

## Step 9: Device disable behavior

Only run this if you have at least two queued samples or can observe a sample mid-flight.

While one Android batch is running:

1. Make the device unavailable, or disable it in the system being tested
2. Observe the in-flight sample and later samples

Expected:

- The in-flight sample on that device may fail

## Step 10: LLM response extraction smoke

Use the Config page, Builder, and SampleDetail to validate the new optional LLM comparison path.

1. On `Config`, enter a bad API key and click `测试连通性`
2. Confirm the page surfaces an auth-stage error and `保存` is rejected for the same bad triple
3. Replace it with a valid `base_url` / `model` / `api_key` triple, run `测试连通性`, then `保存`
4. In `Profiles -> Build Profile`, enable `生成时注入 LLM 响应抽取配置` before `Generate Draft`
5. Save the generated draft as a normal profile and inspect the YAML
6. Run a quick Android test or one-sample batch with that profile, then open SampleDetail
7. Break the saved profile's `api_key`, rerun once, and inspect SampleDetail again

Expected:

- Bad credentials show a staged Config-page error such as `认证失败`
- Valid credentials show a success message and can be saved
- Builder-generated YAML contains `base_url`, `model`, and `api_key`
- SampleDetail shows both `规则抽取` and `LLM 抽取` when profile LLM is enabled
- If runtime LLM fails, the sample still completes and the LLM column shows the stage string via `llm_errors`
- Other samples should not wedge indefinitely
- Later scheduling should reflect device availability

Result (2026-04-25):

- Passed on a real Android device with no blocking issues.
- Config-page connectivity test correctly rejected bad credentials and accepted a valid triple.
- Builder-generated profile YAML included `base_url`, `model`, and `api_key` when LLM injection was enabled.
- Quick Test and SampleDetail both showed separate `规则提取` and `LLM 提取` outputs for LLM-enabled profiles.
- Runtime LLM failure remained non-fatal and surfaced through the LLM column as expected.

## Optional fallback: manual YAML profile

Only use this if Builder is blocked and you need to isolate whether the regression is in Builder or
the executor. The preferred final smoke path is still Builder -> review -> connectivity -> save.

Minimal Tier 1 shape:

```yaml
name: real_android_manual
platform: android
package: com.example.app
activity: .MainActivity
serial: ""
input_method: auto
ready_check:
  type: exists
  target:
    resource_id: com.example.app:id/input
input_focus_action:
  - action: tap_xy
    x: 540
    y: 1800
input_locator:
  resource_id: com.example.app:id/input
send_action:
  - action: tap_xy
    x: 980
    y: 2050
response_extraction:
  method: ui_tree_only
  response_container_locator:
    resource_id: com.example.app:id/chat_recycler_view
  latest_bubble_match:
    kind: resource_id
    value: com.example.app:id/chat_recycler_view
complete_detection:
  type: ui_tree_stable
  stable_sec: 1.0
  max_wait_sec: 60
```

## Report format

Reply with:

```text
1. Device discovery + IME readiness: 通过/失败
2. Builder draft generation: 通过/失败
3. Builder review flow: 通过/失败
4. Draft connectivity validation: 通过/失败
5. Save reviewed profile: 通过/失败
6. Tier 1 quick test: 通过/失败
7. Tier 1 batch + SampleDetail: 通过/失败
8. Tier 2 OCR long response: 通过/失败
9. Device disable behavior: 通过/失败/未测
补充信息: 失败现象、报错、截图、使用的真实 App 名称、相关 session_id / batch_id
```

Once this checklist passes, the remaining repo actions are:

1. Mark Plan 4 complete in `README.md`, `CLAUDE.md`, and the plan/spec docs
2. Commit the final completion docs
3. Tag `android-executor-v0.4.0`
