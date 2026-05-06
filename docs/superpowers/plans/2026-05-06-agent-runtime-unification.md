# Agent Runtime Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the lightweight `agent_core` internals with a unified runtime derived from the mature execution modules in `apa_llm` and `Open-AutoGLM`, while keeping AutoAgent's existing executors, scheduler, logging, and response extraction flow intact.

**Architecture:** The refactor introduces a unified action schema and splits `agent_core` into focused modules: `parser.py`, `result.py`, `runtime.py`, `handlers/`, and `devices/`. `AgentPcExecutor` and `AgentAndroidExecutor` remain the outer system boundary, but they will call the new runtime and persist the same artifacts under `logs/<batch>/<sample>/`.

Latest follow-up status:
- The shared runtime now preserves text-only conversation context across steps instead of replaying only raw action strings.
- Each new step includes recent-step summaries, basic screen metadata, and repeated-action warnings so the model can detect when `Type`/`Wait` loops are unproductive.
- Executor traces now persist `conversation` alongside `steps`, `execution`, and `stop_reason` for post-run diagnosis.
- The shared PC/Android handlers now interpret `element` / `start` / `end` coordinates using the same 0-1000 relative coordinate contract used by `apa_llm` and `Open-AutoGLM`, then convert them to absolute screen pixels with `screen_width` / `screen_height`.
- Runtime conversation storage also avoids double-wrapping existing `<answer>...</answer>` outputs, so replayed assistant context stays clean.
- The system prompts now explicitly tell the model that `element` / `start` / `end` must use 0-1000 relative coordinates rather than raw pixels, so the model-side coordinate contract matches the handler-side conversion.
- The PC `Type` implementation now follows the reference desktop runtimes more closely: clipboard copy plus system paste shortcut, instead of `pyautogui.typewrite()`, so non-ASCII text entry is reliable.
- The shared runtime can now use a multimodal response observer before accepting `finish(...)` after send-like actions, so agent runs do not stop merely because the policy model claims the message was sent; they stop only after the screenshot-based verifier sees a reply matching `response_hint`.

**Tech Stack:** Python 3.11, `httpx`, `mss`, `pyautogui`, `adb`, `pytest`, `ruff`.

---

## Files

- Create: `src/autoagent/executors/agent_core/result.py`
- Create: `src/autoagent/executors/agent_core/parser.py`
- Create: `src/autoagent/executors/agent_core/runtime.py`
- Create: `src/autoagent/executors/agent_core/devices/__init__.py`
- Create: `src/autoagent/executors/agent_core/devices/pc.py`
- Create: `src/autoagent/executors/agent_core/devices/android.py`
- Create: `src/autoagent/executors/agent_core/handlers/__init__.py`
- Create: `src/autoagent/executors/agent_core/handlers/pc.py`
- Create: `src/autoagent/executors/agent_core/handlers/android.py`
- Modify: `src/autoagent/executors/agent_core/prompts.py`
- Modify: `src/autoagent/executors/agent_pc_executor.py`
- Modify: `src/autoagent/executors/agent_android_executor.py`
- Modify: `tests/unit/test_action_parser.py`
- Create: `tests/unit/test_agent_handlers.py`
- Modify: `tests/unit/test_agent_loop.py`
- Modify: `tests/unit/test_agent_mode_executors.py`
- Keep temporarily as compatibility shims until final cleanup:
  - `src/autoagent/executors/agent_core/action_parser.py`
  - `src/autoagent/executors/agent_core/agent_loop.py`
  - `src/autoagent/executors/agent_core/pc_device.py`
  - `src/autoagent/executors/agent_core/android_device.py`

### Task 1: Define Unified Action Contract

**Files:**
- Create: `src/autoagent/executors/agent_core/result.py`
- Create: `src/autoagent/executors/agent_core/parser.py`
- Modify: `tests/unit/test_action_parser.py`

- [x] **Step 1: Rewrite parser tests against the new schema**

Replace the old `_type`-centric expectations in `tests/unit/test_action_parser.py` with unified action metadata checks like:

```python
from autoagent.executors.agent_core.parser import parse_action


def test_parse_do_tap():
    result = parse_action('do(action="Tap", element=[320, 640])')
    assert result == {"_metadata": "do", "action": "Tap", "element": [320, 640]}


def test_parse_do_wait():
    result = parse_action('do(action="Wait", duration="3 seconds")')
    assert result == {"_metadata": "do", "action": "Wait", "duration": "3 seconds"}


def test_parse_finish():
    result = parse_action('finish(message="done")')
    assert result == {"_metadata": "finish", "message": "done"}


def test_parse_legacy_action_click_named_args():
    result = parse_action("Action: click(x=387, y=480)")
    assert result == {"_metadata": "do", "action": "Tap", "element": [387, 480]}


def test_parse_invalid_action_returns_noop():
    result = parse_action("nonsense")
    assert result == {"_metadata": "noop", "raw": "nonsense"}
```

- [x] **Step 2: Run parser tests to verify the current implementation fails**

Run:

```bash
python3.11 -m pytest tests/unit/test_action_parser.py -q
```

Expected: failures because the current parser returns `_type` dictionaries instead of the new unified schema.

- [x] **Step 3: Create `result.py` with shared dataclasses**

Add:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autoagent.executors.agent_core.device import Screenshot


@dataclass
class ActionResult:
    success: bool
    should_finish: bool
    message: str | None = None


@dataclass
class AgentStepRecord:
    step: int
    raw: str
    action: dict[str, Any]
    execution: ActionResult | None
    screenshot: Screenshot

    def to_metadata(self) -> dict[str, Any]:
        payload = {"step": self.step, "raw": self.raw, "action": self.action}
        if self.execution is not None:
            payload["execution"] = {
                "success": self.execution.success,
                "should_finish": self.execution.should_finish,
                "message": self.execution.message,
            }
        return payload


@dataclass
class AgentRunResult:
    finished: bool
    finish_message: str
    step_count: int
    stop_reason: str
    steps: list[AgentStepRecord] = field(default_factory=list)
```

- [x] **Step 4: Create `parser.py` with unified and compatibility parsing**

Implement `parse_action()` so it supports:

```python
def parse_action(text: str) -> dict:
    # finish(message="...")
    # do(action="Tap", ...)
    # do(action="Back")
    # Action: click(...)
    # Action: click(x=..., y=...)
    # Action: type("...")
    # Action: press(enter)
    # malformed -> {"_metadata": "noop", "raw": original}
```

Minimum conversion rules:

```python
"Action: click(100, 200)" -> {"_metadata": "do", "action": "Tap", "element": [100, 200]}
"Action: click(x=100, y=200)" -> {"_metadata": "do", "action": "Tap", "element": [100, 200]}
"Action: press(back)" -> {"_metadata": "do", "action": "Back"}
"Action: press(home)" -> {"_metadata": "do", "action": "Home"}
"Action: press(enter)" -> {"_metadata": "do", "action": "Press", "key": "enter"}
"Action: scroll(down, 3)" -> {"_metadata": "do", "action": "Scroll", "direction": "down", "clicks": 3}
```

- [x] **Step 5: Keep compatibility shim exports**

Replace `src/autoagent/executors/agent_core/action_parser.py` with:

```python
from autoagent.executors.agent_core.parser import parse_action

__all__ = ["parse_action"]
```

This lets existing imports survive while the rest of the migration lands.

- [x] **Step 6: Run parser tests to verify they pass**

Run:

```bash
python3.11 -m pytest tests/unit/test_action_parser.py -q
```

Expected: all parser tests pass.

- [x] **Step 7: Commit**

Run:

```bash
git add src/autoagent/executors/agent_core/result.py \
  src/autoagent/executors/agent_core/parser.py \
  src/autoagent/executors/agent_core/action_parser.py \
  tests/unit/test_action_parser.py
git commit -m "refactor: define unified agent action schema"
```

### Task 2: Move Platform Semantics into Handlers and Device Adapters

**Files:**
- Create: `src/autoagent/executors/agent_core/devices/__init__.py`
- Create: `src/autoagent/executors/agent_core/devices/pc.py`
- Create: `src/autoagent/executors/agent_core/devices/android.py`
- Create: `src/autoagent/executors/agent_core/handlers/__init__.py`
- Create: `src/autoagent/executors/agent_core/handlers/pc.py`
- Create: `src/autoagent/executors/agent_core/handlers/android.py`
- Create: `tests/unit/test_agent_handlers.py`
- Modify: `tests/unit/test_pc_device.py`
- Modify: `tests/unit/test_android_device.py`

- [x] **Step 1: Write handler tests before implementation**

Create `tests/unit/test_agent_handlers.py`:

```python
from __future__ import annotations

from unittest.mock import Mock

from autoagent.executors.agent_core.handlers.android import AndroidActionHandler
from autoagent.executors.agent_core.handlers.pc import PcActionHandler


def test_pc_handler_executes_tap():
    device = Mock()
    handler = PcActionHandler(device=device)
    result = handler.execute({"_metadata": "do", "action": "Tap", "element": [100, 200]}, 1920, 1080)
    device.tap.assert_called_once_with(100, 200)
    assert result.success is True


def test_pc_handler_executes_hotkey():
    device = Mock()
    handler = PcActionHandler(device=device)
    result = handler.execute({"_metadata": "do", "action": "Hotkey", "keys": ["ctrl", "c"]}, 1920, 1080)
    device.hotkey.assert_called_once_with("ctrl", "c")
    assert result.success is True


def test_android_handler_executes_back():
    device = Mock()
    handler = AndroidActionHandler(device=device)
    result = handler.execute({"_metadata": "do", "action": "Back"}, 1080, 2400)
    device.press_key.assert_called_once_with("back")
    assert result.success is True


def test_android_handler_executes_long_press():
    device = Mock()
    handler = AndroidActionHandler(device=device)
    result = handler.execute(
        {"_metadata": "do", "action": "Long Press", "element": [300, 500], "duration_ms": 800},
        1080,
        2400,
    )
    device.long_press.assert_called_once_with(300, 500, duration_ms=800)
    assert result.success is True
```

- [x] **Step 2: Run handler tests to verify they fail**

Run:

```bash
python3.11 -m pytest tests/unit/test_agent_handlers.py -q
```

Expected: import errors because handlers do not exist yet.

- [x] **Step 3: Create low-level device adapters**

In `devices/pc.py`, expose methods like:

```python
class PcDeviceAdapter(Device):
    def capture(self) -> Screenshot: ...
    def tap(self, x: int, y: int) -> None: ...
    def double_tap(self, x: int, y: int) -> None: ...
    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None: ...
    def type_text(self, text: str) -> None: ...
    def press_key(self, key: str) -> None: ...
    def hotkey(self, *keys: str) -> None: ...
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None: ...
    def scroll(self, direction: str, clicks: int) -> None: ...
```

In `devices/android.py`, expose the same conceptual API backed by ADB:

```python
class AndroidDeviceAdapter(Device):
    def capture(self) -> Screenshot: ...
    def tap(self, x: int, y: int) -> None: ...
    def double_tap(self, x: int, y: int) -> None: ...
    def long_press(self, x: int, y: int, duration_ms: int = 800) -> None: ...
    def type_text(self, text: str) -> None: ...
    def press_key(self, key: str) -> None: ...
    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None: ...
    def scroll(self, direction: str, clicks: int) -> None: ...
```

- [x] **Step 4: Create platform handlers**

Implement handlers around the reference semantics:

```python
class PcActionHandler:
    def __init__(self, device: PcDeviceAdapter) -> None: ...
    def execute(self, action: dict, screen_width: int, screen_height: int) -> ActionResult: ...


class AndroidActionHandler:
    def __init__(self, device: AndroidDeviceAdapter) -> None: ...
    def execute(self, action: dict, screen_width: int, screen_height: int) -> ActionResult: ...
```

Required action coverage:

- `Tap`
- `Type`
- `Swipe`
- `Scroll`
- `Press`
- `Back`
- `Home`
- `Double Tap`
- `Long Press`
- `Hotkey` for PC only
- `Wait`

- [x] **Step 5: Convert old device modules into shims**

Replace:

```python
# src/autoagent/executors/agent_core/pc_device.py
from autoagent.executors.agent_core.devices.pc import PcDeviceAdapter as PcDevice

__all__ = ["PcDevice"]
```

and:

```python
# src/autoagent/executors/agent_core/android_device.py
from autoagent.executors.agent_core.devices.android import AndroidDeviceAdapter as AndroidDevice

__all__ = ["AndroidDevice"]
```

This preserves existing imports in executors and tests while the runtime is switched over.

- [x] **Step 6: Update device tests to the new adapter methods**

Adjust `tests/unit/test_pc_device.py` and `tests/unit/test_android_device.py` so they instantiate the shim classes and assert on:

```python
PcDevice().double_tap(...)
PcDevice().long_press(...)
PcDevice().hotkey(...)
PcDevice().scroll("down", 3)

AndroidDevice().double_tap(...)
AndroidDevice().long_press(...)
AndroidDevice().press_key("back")
AndroidDevice().scroll("up", 2)
```

These tests should stop calling `execute_action()` directly, because that responsibility moves into the handler layer.

- [x] **Step 7: Run handler and device tests**

Run:

```bash
python3.11 -m pytest tests/unit/test_agent_handlers.py tests/unit/test_pc_device.py tests/unit/test_android_device.py -q
```

Expected: all tests pass.

- [x] **Step 8: Commit**

Run:

```bash
git add src/autoagent/executors/agent_core/devices \
  src/autoagent/executors/agent_core/handlers \
  src/autoagent/executors/agent_core/pc_device.py \
  src/autoagent/executors/agent_core/android_device.py \
  tests/unit/test_agent_handlers.py \
  tests/unit/test_pc_device.py \
  tests/unit/test_android_device.py
git commit -m "refactor: split agent devices and action handlers"
```

### Task 3: Replace the Loop with a Handler-Driven Runtime

**Files:**
- Create: `src/autoagent/executors/agent_core/runtime.py`
- Modify: `tests/unit/test_agent_loop.py`
- Modify: `src/autoagent/executors/agent_core/agent_loop.py`

- [x] **Step 1: Rewrite loop tests around runtime behavior**

Update `tests/unit/test_agent_loop.py` to verify execution result metadata, not just raw action dicts:

```python
from autoagent.executors.agent_core.result import ActionResult
from autoagent.executors.agent_core.runtime import AgentRuntime


def test_runtime_stops_on_finish():
    device = FakeDevice()
    client = FakeClient(['finish(message="done")'])
    handler = FakeHandler([ActionResult(success=True, should_finish=True, message="done")])
    runtime = AgentRuntime(device=device, client=client, handler=handler, system_prompt="x", max_steps=3)
    result = runtime.run("task")
    assert result.finished is True
    assert result.stop_reason == "finish"
    assert result.step_count == 1


def test_runtime_records_execution_result():
    device = FakeDevice()
    client = FakeClient(['do(action="Tap", element=[100, 200])', 'finish(message="done")'])
    handler = FakeHandler([
        ActionResult(success=True, should_finish=False),
        ActionResult(success=True, should_finish=True, message="done"),
    ])
    runtime = AgentRuntime(device=device, client=client, handler=handler, system_prompt="x", max_steps=3)
    result = runtime.run("task")
    assert result.steps[0].execution.success is True
    assert result.steps[0].action["action"] == "Tap"
```

- [x] **Step 2: Run loop tests to verify they fail**

Run:

```bash
python3.11 -m pytest tests/unit/test_agent_loop.py -q
```

Expected: failures because `AgentRuntime` does not exist yet and `AgentLoop` does not record execution results.

- [x] **Step 3: Implement `runtime.py`**

Add:

```python
class AgentRuntime:
    def __init__(self, device, client, handler, system_prompt: str, max_steps: int) -> None: ...

    def run(self, task: str) -> AgentRunResult:
        context = []
        steps = []
        for step in range(1, self._max_steps + 1):
            screenshot = self._device.capture()
            messages = self._build_messages(task, screenshot, context, step)
            raw = self._client.call(messages)
            action = parse_action(raw)
            execution = None

            if action.get("_metadata") == "finish":
                record = AgentStepRecord(step=step, raw=raw, action=action, execution=None, screenshot=screenshot)
                steps.append(record)
                return AgentRunResult(True, action.get("message", ""), step, "finish", steps)

            if action.get("_metadata") == "do":
                execution = self._handler.execute(action, screenshot.width, screenshot.height)
                record = AgentStepRecord(step=step, raw=raw, action=action, execution=execution, screenshot=screenshot)
                steps.append(record)
                if execution.should_finish:
                    return AgentRunResult(True, execution.message or "", step, "handler_finish", steps)
            else:
                record = AgentStepRecord(step=step, raw=raw, action=action, execution=None, screenshot=screenshot)
                steps.append(record)

            context.append({"step": step, "action_text": raw})

        return AgentRunResult(False, "max_steps reached", self._max_steps, "max_steps", steps)
```

- [x] **Step 4: Keep `agent_loop.py` as a runtime shim**

Replace `src/autoagent/executors/agent_core/agent_loop.py` with:

```python
from autoagent.executors.agent_core.runtime import AgentRuntime, AgentRunResult, AgentStepRecord

AgentLoop = AgentRuntime
AgentResult = AgentRunResult

__all__ = ["AgentLoop", "AgentResult", "AgentStepRecord"]
```

This avoids a wide import churn during the transition.

- [x] **Step 5: Run loop tests**

Run:

```bash
python3.11 -m pytest tests/unit/test_agent_loop.py -q
```

Expected: loop tests pass.

- [x] **Step 6: Commit**

Run:

```bash
git add src/autoagent/executors/agent_core/runtime.py \
  src/autoagent/executors/agent_core/agent_loop.py \
  tests/unit/test_agent_loop.py
git commit -m "refactor: replace agent loop with unified runtime"
```

### Task 4: Rewire Executors to the New Runtime and Preserve Artifacts

**Files:**
- Modify: `src/autoagent/executors/agent_pc_executor.py`
- Modify: `src/autoagent/executors/agent_android_executor.py`
- Modify: `src/autoagent/executors/agent_core/prompts.py`
- Modify: `tests/unit/test_agent_mode_executors.py`

- [x] **Step 1: Extend executor tests for handler-driven traces**

Update `tests/unit/test_agent_mode_executors.py` so the loop trace assertions include execution metadata:

```python
trace = json.loads(trace_path.read_text(encoding="utf-8"))
assert trace["steps"][0]["action"]["action"] == "Tap"
assert trace["steps"][0]["execution"]["success"] is True
assert trace["stop_reason"] in {"finish", "handler_finish", "max_steps"}
```

- [x] **Step 2: Run executor tests to verify they fail**

Run:

```bash
python3.11 -m pytest tests/unit/test_agent_mode_executors.py -q
```

Expected: failures because the executors currently instantiate only `device + client + loop` and do not provide handlers or stop reasons.

- [x] **Step 3: Update prompts to the unified protocol**

`src/autoagent/executors/agent_core/prompts.py` should instruct the model to return only:

```text
do(action="Tap", element=[x, y])
do(action="Type", text="...")
do(action="Back")
do(action="Home")
do(action="Wait", duration="1 second")
finish(message="...")
```

The prompt must explicitly say:

- one action per response
- no explanation text
- prefer `do(...)`
- use `finish(...)` only when the interaction is complete

- [x] **Step 4: Rewire `AgentPcExecutor`**

Change executor setup from:

```python
device = PcDevice()
agent_loop = AgentLoop(device, client, PC_SYSTEM_PROMPT, profile.max_steps)
```

to:

```python
device = PcDevice()
handler = PcActionHandler(device=device)
runtime = AgentLoop(device=device, client=client, handler=handler, system_prompt=PC_SYSTEM_PROMPT, max_steps=profile.max_steps)
```

Then update trace payloads to include:

```python
trace_payload = {
    "task": task,
    "finished": loop_result.finished,
    "finish_message": loop_result.finish_message,
    "step_count": loop_result.step_count,
    "stop_reason": loop_result.stop_reason,
    "steps": [step.to_metadata() for step in loop_result.steps],
}
```

- [x] **Step 5: Rewire `AgentAndroidExecutor`**

Mirror the PC executor changes using:

```python
device = AndroidDevice(serial=serial)
handler = AndroidActionHandler(device=device)
runtime = AgentLoop(device=device, client=client, handler=handler, system_prompt=ANDROID_SYSTEM_PROMPT, max_steps=profile.max_steps)
```

- [x] **Step 6: Run focused executor and extractor tests**

Run:

```bash
python3.11 -m pytest tests/unit/test_agent_mode_executors.py tests/unit/test_agent_screenshot_extractor.py -q
```

Expected: tests pass and artifact assertions still hold.

- [x] **Step 7: Run the full targeted agent suite**

Run:

```bash
python3.11 -m pytest \
  tests/unit/test_action_parser.py \
  tests/unit/test_agent_handlers.py \
  tests/unit/test_agent_loop.py \
  tests/unit/test_agent_mode_executors.py \
  tests/unit/test_agent_screenshot_extractor.py \
  tests/unit/test_pc_device.py \
  tests/unit/test_android_device.py -q
```

Expected: all tests pass.

- [x] **Step 8: Commit**

Run:

```bash
git add src/autoagent/executors/agent_core/prompts.py \
  src/autoagent/executors/agent_pc_executor.py \
  src/autoagent/executors/agent_android_executor.py \
  tests/unit/test_agent_mode_executors.py
git commit -m "refactor: wire executors to unified agent runtime"
```

### Task 5: Cleanup, Compatibility Check, and Final Verification

**Files:**
- Modify or delete after behavior is preserved:
  - `src/autoagent/executors/agent_core/action_parser.py`
  - `src/autoagent/executors/agent_core/agent_loop.py`
  - `src/autoagent/executors/agent_core/pc_device.py`
  - `src/autoagent/executors/agent_core/android_device.py`
- Optional plan status sync:
  - `docs/superpowers/plans/2026-05-06-agent-executor.md`

- [x] **Step 1: Remove dead code paths only after passing tests**

If the shims no longer add value, delete them and update imports directly to:

```python
from autoagent.executors.agent_core.parser import parse_action
from autoagent.executors.agent_core.runtime import AgentRuntime
from autoagent.executors.agent_core.devices.pc import PcDeviceAdapter
from autoagent.executors.agent_core.devices.android import AndroidDeviceAdapter
```

If the shims are still useful for compatibility, keep them but ensure they stay one-line re-exports only.

- [x] **Step 2: Run fast regression suite**

Run:

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

Expected: the existing fast suite stays green.

- [x] **Step 3: Run `ruff` on the changed files**

Run:

```bash
python3.11 -m ruff check \
  src/autoagent/executors/agent_core \
  src/autoagent/executors/agent_pc_executor.py \
  src/autoagent/executors/agent_android_executor.py \
  tests/unit/test_action_parser.py \
  tests/unit/test_agent_handlers.py \
  tests/unit/test_agent_loop.py \
  tests/unit/test_agent_mode_executors.py \
  tests/unit/test_pc_device.py \
  tests/unit/test_android_device.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Do one real `agent_pc` smoke run and inspect traces**

Current status: still pending. The refactor has passed fast regression, targeted unified-agent tests, and `ruff`, but a fresh live `agent_pc` smoke run after unification still needs an opt-in interactive desktop session because it will drive the current GUI and call the configured remote VLM profile.

Run a real batch after the test suite passes, then inspect:

```bash
ls -R logs/<batch_id>/<sample_id>
cat logs/<batch_id>/<sample_id>/loop_trace_1.json
cat logs/<batch_id>/<sample_id>/extract_1.json
```

Expected evidence:

- step screenshots exist
- `loop_trace_1.json` includes `action`, `execution`, and `stop_reason`
- the model output prefers `do(...)`

- [x] **Step 5: Sync the existing plan status**

Update `docs/superpowers/plans/2026-05-06-agent-executor.md` so its status section mentions that the original plan was implemented first and then internally refactored into a unified runtime derived from the reference projects.

- [x] **Step 6: Commit**

Run:

```bash
git add src/autoagent/executors/agent_core \
  src/autoagent/executors/agent_pc_executor.py \
  src/autoagent/executors/agent_android_executor.py \
  tests/unit/test_action_parser.py \
  tests/unit/test_agent_handlers.py \
  tests/unit/test_agent_loop.py \
  tests/unit/test_agent_mode_executors.py \
  tests/unit/test_pc_device.py \
  tests/unit/test_android_device.py \
  docs/superpowers/plans/2026-05-06-agent-executor.md
git commit -m "refactor: unify agent runtime around reference execution model"
```

## Self-Review

- Spec coverage: parser, runtime, handlers, devices, executors, logging, testing, and migration order are all covered by explicit tasks.
- Placeholder scan: no `TODO`, `TBD`, or “implement later” placeholders remain.
- Type consistency: the plan consistently uses `_metadata`/`action` schema, `ActionResult`, `AgentStepRecord`, and `AgentRunResult` across parser, runtime, handlers, and tests.
