# Plan 4 Android Manual Smoke Checklist

Use this checklist for the final Plan 4 real-device validation round. The goal is to confirm the shipped `gui_android` flow works end to end against a real Android device and a real target app before tagging `android-executor-v0.4.0`.

## Current handoff

Before running this checklist, read:

```text
docs/superpowers/plans/2026-04-24-android-profile-builder-handoff.md
```

That file records the latest Qwen/Tongyi Profile Builder debugging state, recent ADB Keyboard/input-locator fixes, verification caveats, and current blockers. As of 2026-04-24, final release tagging is still blocked on a fresh real-device retest after `67e07d8 fix(android): broadcast after focused adb input`.

## Preconditions

- Device is visible in `adb devices -l`
- USB debugging is enabled
- The target app is already installed and can be opened manually on the device
- Backend env is set: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `JWT_SECRET`
- Frontend is built and served from the same backend instance

Start the backend from the worktree root:

```bash
cd /Users/b1ankj/Desktop/2026/Q2/AutoAgentTest/.worktrees/plan4-android-executor
python3.11 -m uvicorn --app-dir src autoagent.main:app --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

## Step 1: Device discovery

1. Run `adb devices -l`
2. Open `/devices` in the web UI
3. Click `Refresh`

Expected:

- At least one device is listed
- The device shows `online`
- The device shows `enabled`

## Step 2: Create an Android profile

Create a profile for the real target app. Use a Tier 1 profile first, then a Tier 2 OCR profile.

Tier 1 example:

```yaml
name: real_android_tier1
platform: android
package: com.example.app
activity: .MainActivity
serial: ""
input_method: auto
ready_check:
  type: exists
  target:
    resource_id: com.example.app:id/input
send_button_locator:
  resource_id: com.example.app:id/send
input_locator:
  resource_id: com.example.app:id/input
new_session_action:
  - action: click_locator
    target:
      resource_id: com.example.app:id/new_chat
response_extraction:
  method: ui_tree_only
  latest_bubble_match:
    kind: class
    value: android.widget.TextView
complete_detection:
  type: ui_tree_stable
  stable_sec: 1.0
  max_wait_sec: 60
```

Tier 2 example:

```yaml
name: real_android_tier2
platform: android
package: com.example.app
activity: .MainActivity
serial: ""
input_method: auto
ready_check:
  type: exists
  target:
    resource_id: com.example.app:id/input
send_button_locator:
  resource_id: com.example.app:id/send
input_locator:
  resource_id: com.example.app:id/input
new_session_action:
  - action: click_locator
    target:
      resource_id: com.example.app:id/new_chat
response_extraction:
  method: ui_tree_then_ocr
  latest_bubble_match:
    kind: class
    value: android.widget.TextView
complete_detection:
  type: pixel_stable
  stable_sec: 1.0
  max_wait_sec: 90
```

Expected:

- `校验` succeeds
- `保存` succeeds
- `连通性测试` button is enabled for both profiles

## Step 3: Tier 1 connectivity test

On the Tier 1 profile page, run `连通性测试` with prompt:

```text
hi
```

Expected:

- Request succeeds
- The app opens on the device if needed
- The response is non-empty

## Step 4: Tier 1 quick test

Go to `Tests / Quick` and run:

- Mode: `Android (GUI)`
- Profile: `real_android_tier1`
- Prompt: `hi`
- Execution: `同步`

Expected:

- Result status is `done`
- Response text is non-empty
- No device-allocation error is shown

## Step 5: Tier 1 batch

Create a JSONL file:

```jsonl
{"id":"a1","prompts":["hello"],"mode":"gui_android","target_profile":"real_android_tier1"}
{"id":"a2","prompts":["how are you"],"mode":"gui_android","target_profile":"real_android_tier1"}
{"id":"a3","prompts":["tell me a joke"],"mode":"gui_android","target_profile":"real_android_tier1"}
```

Upload it from `Batches / 新建批次`.

Expected:

- Batch starts successfully
- `BatchDetail` updates without manual refresh
- At least one sample shows `device_serial`
- Final counts match `done = 3`, `failed = 0` unless the app itself rejects a prompt

## Step 6: Tier 1 sample detail

Open one sample from the batch.

Expected:

- `运行设备` is visible
- Screenshot strip renders
- Action log renders when available
- `下载回放 JSONL` works when shown
- Metadata contains Android-related fields when applicable

## Step 7: Tier 2 OCR long-response validation

Use the Tier 2 profile against a prompt that should force a response longer than one screen.

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

## Step 8: Device disable behavior

Only run this if you have at least two queued samples or can observe a sample mid-flight.

While one Android batch is running:

1. Make the device unavailable, or disable it in the system being tested
2. Observe the in-flight sample and later samples

Expected:

- The in-flight sample on that device may fail
- Other samples should not wedge indefinitely
- Later scheduling should reflect device availability

## Report format

Reply with:

```text
1. Device discovery: 通过/失败
2. Android profile validate/save: 通过/失败
3. Tier 1 connectivity test: 通过/失败
4. Tier 1 quick test: 通过/失败
5. Tier 1 batch + SSE: 通过/失败
6. Tier 1 sample detail + replay: 通过/失败
7. Tier 2 OCR long response: 通过/失败
8. Device disable behavior: 通过/失败/未测
补充信息: 失败现象、报错、截图、使用的真实 App 名称
```

Once this checklist passes, the remaining repo actions are:

1. Mark Plan 4 complete in `README.md`, `CLAUDE.md`, and the plan/spec docs
2. Commit the final completion docs
3. Tag `android-executor-v0.4.0`
