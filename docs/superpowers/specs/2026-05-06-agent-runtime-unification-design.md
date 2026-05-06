# Agent Runtime Unification — Design

**Date:** 2026-05-06
**Status:** Approved

## Motivation

The current `agent_core` implementation made `agent_pc` and `agent_android` runnable inside AutoAgent, but it is still a lightweight runtime. Recent trace analysis showed the main weakness clearly:

- prompt protocol, parser, and device execution semantics drifted apart
- mature actions from the reference projects had to be re-added one by one
- finish signals from the model were weaker than the actual UI evidence
- PC and Android behavior was only partially unified

`apa_llm` and `Open-AutoGLM` already provide mature execution modules. We do **not** need their task planning or retry layers, but we should absorb their execution model instead of continuing to grow a custom minimal runtime.

## Goal

Keep AutoAgent's outer execution shell intact:

- batch API
- scheduler
- profile schema
- executor interface
- result storage
- trace and screenshot logging

Replace the current lightweight `agent_core` internals with a unified runtime derived from the mature execution layers in:

- `/Users/b1ankj/Desktop/2026/q2/apa_llm/`
- `/Users/b1ankj/Desktop/2026/q2/Open-AutoGLM/`

## Non-Goals

The following are explicitly out of scope for this refactor:

- task planning / multi-stage planning
- retry policy beyond the existing AutoAgent execution flow
- playbook caching
- state tracker / memory systems from the reference projects
- direct reuse of the reference projects' full config systems or device factories
- frontend changes

## Reference Extraction Boundary

We are **not** copying the reference repositories wholesale.

We are extracting and adapting only these layers:

- action protocol
- action parsing
- action dispatch semantics
- step loop structure
- platform-specific action handlers

We are **not** adopting:

- planner orchestration
- retry loops
- project-specific CLI / config entrypoints
- large factory abstractions that do not match AutoAgent's current structure

## Architecture

### Outer Layer: Keep AutoAgent Integration

These components remain the AutoAgent system boundary:

- `src/autoagent/executors/agent_pc_executor.py`
- `src/autoagent/executors/agent_android_executor.py`
- `src/autoagent/scheduler/batch_scheduler.py`
- `src/autoagent/executors/base.py`
- existing `SampleResult`, `ExecutorContext`, and logs/results layout

Each executor will still:

1. load the profile
2. create a runtime configuration
3. run one prompt at a time
4. persist loop traces and screenshots
5. run final screenshot-based response extraction

### Inner Layer: Replace `agent_core` Runtime

`agent_core` will be reorganized around four focused units:

1. `parser.py`
   Parses model output into a unified structured action schema modeled after the reference projects.

2. `runtime.py`
   Owns the step loop: capture, call model, parse action, execute action, record trace, and stop on finish/max-steps/error.

3. `handlers/`
   Contains platform-specific action handlers (`pc.py`, `android.py`) that interpret the unified action schema and return structured execution results.

4. `devices/`
   Contains platform-specific low-level device adapters (`pc.py`, `android.py`) that expose raw primitives such as tap, type, press, swipe, scroll, and capture.

This keeps the architecture small enough to fit the current codebase, while moving the action semantics much closer to the reference runtimes.

## Unified Action Schema

The parser and handlers will use a shared schema inspired by the reference projects:

```python
{"_metadata": "do", "action": "Tap", "element": [320, 640]}
{"_metadata": "do", "action": "Double Tap", "element": [320, 640]}
{"_metadata": "do", "action": "Long Press", "element": [320, 640], "duration_ms": 800}
{"_metadata": "do", "action": "Type", "text": "hello"}
{"_metadata": "do", "action": "Press", "key": "enter"}
{"_metadata": "do", "action": "Hotkey", "keys": ["ctrl", "c"]}
{"_metadata": "do", "action": "Swipe", "start": [500, 800], "end": [500, 200]}
{"_metadata": "do", "action": "Scroll", "direction": "down", "clicks": 3}
{"_metadata": "do", "action": "Back"}
{"_metadata": "do", "action": "Home"}
{"_metadata": "do", "action": "Wait", "duration": "1 second"}
{"_metadata": "finish", "message": "task completed"}
{"_metadata": "noop", "raw": "..."}
```

This schema becomes the contract between parser, runtime, handlers, and trace logs.

## Prompt Protocol

The default system prompts for both PC and Android will standardize on:

- `do(action="...", ...)`
- `finish(message="...")`

Legacy compatibility remains in the parser for:

- `Action: click(...)`
- `Action: click(x=..., y=...)`
- `<answer>...</answer>`

But the runtime will treat those as compatibility fallbacks, not the primary protocol.

## Runtime Loop

`runtime.py` will replace the current minimal `AgentLoop` with a handler-driven loop.

Core flow:

1. capture screenshot
2. build model messages
3. call VLM
4. parse into unified action schema
5. execute through handler
6. record step trace:
   - raw model output
   - parsed action
   - execution result
   - screenshot metadata
7. stop when:
   - parser yields `finish`
   - max steps reached
   - unrecoverable execution error occurs

The runtime will return a structured result with:

- finished flag
- finish message
- step count
- step records
- execution error summary when applicable

## Handler Responsibilities

The handler layer is where most reference behavior is intentionally reused.

### PC Handler

Backed by `pyautogui` and desktop capture. It is responsible for:

- converting normalized coordinates to absolute pixels if needed
- dispatching `Tap`, `Double Tap`, `Long Press`, `Type`, `Press`, `Hotkey`, `Swipe`, `Scroll`, `Wait`
- returning an `ActionResult` with:
  - `success`
  - `should_finish`
  - `message`

### Android Handler

Backed by ADB primitives. It is responsible for:

- touch actions
- keyboard input
- key events
- swipe / long press / wait
- Android-specific semantic aliases like `Back` and `Home`

The PC and Android handlers share the same result type and runtime contract.

## Device Responsibilities

Device adapters will stay intentionally low-level.

They should not:

- decide whether a task is complete
- parse model output
- own loop state

They should only expose raw operations such as:

- `capture()`
- `tap()`
- `double_tap()`
- `long_press()`
- `type_text()`
- `press_key()`
- `hotkey()`
- `swipe()`
- `scroll()`

This separation avoids the current situation where parser and device-specific ad hoc dict handling drift out of sync.

## Logging and Observability

The existing AutoAgent trace persistence stays in place and becomes richer, not replaced.

For each prompt run, logs continue to live under:

- `logs/<batch_id>/<sample_id>/`

Artifacts remain:

- `step_<prompt_index>_<step>.png`
- `loop_trace_<prompt_index>.json`
- `final_<prompt_index>.png`
- `extract_<prompt_index>.json`

`loop_trace_*.json` should now include:

- raw model output
- parsed unified action
- handler execution result
- finish / stop reason

This keeps the current debugging workflow while making traces closer to the reference runtimes' semantics.

## Failure Policy

The current weak point is that the model can emit `finish(...)` even when the UI evidence is poor.

This refactor improves, but does not overreach:

- runtime `finish` means the agent loop ends
- final success is still determined by the existing screenshot extraction result
- if extraction returns empty text, the sample should not silently look like a strong success

This design does **not** force a new top-level status model yet, but the runtime result should expose enough information for executors to tighten that policy next.

## Testing Strategy

The refactor should be test-driven and cover the new boundaries directly.

### Parser Tests

- `do(...)` actions for the supported action set
- `finish(...)`
- compatibility parsing for legacy `Action: ...`
- malformed outputs returning `noop`

### Handler Tests

- PC handler dispatch for tap, type, double tap, long press, hotkey, wait
- Android handler dispatch for tap, back, home, double tap, long press, wait
- execution result behavior for unknown and invalid actions

### Runtime Tests

- finish path
- max-step path
- handler error path
- trace record contents

### Executor Tests

- PC executor integration still writes artifacts
- Android executor integration still writes artifacts
- action logs and screenshot indices still populate `ExecutorContext`

## File Plan

Expected code movement:

- Create: `src/autoagent/executors/agent_core/parser.py`
- Create: `src/autoagent/executors/agent_core/runtime.py`
- Create: `src/autoagent/executors/agent_core/result.py`
- Create: `src/autoagent/executors/agent_core/handlers/pc.py`
- Create: `src/autoagent/executors/agent_core/handlers/android.py`
- Create: `src/autoagent/executors/agent_core/devices/pc.py`
- Create: `src/autoagent/executors/agent_core/devices/android.py`
- Modify: `src/autoagent/executors/agent_pc_executor.py`
- Modify: `src/autoagent/executors/agent_android_executor.py`
- Modify: `src/autoagent/executors/agent_core/prompts.py`
- Migrate or delete superseded lightweight files after behavior is preserved

The old files may remain temporarily as shims during migration, but the end state should have clear module boundaries rather than one expanding `agent_loop.py` plus dict-based `execute_action()` switches.

## Rollout Strategy

The migration should be incremental:

1. introduce unified parser/result/handler modules
2. switch tests to the new contracts
3. replace runtime loop internals
4. rewire executors to the new runtime
5. remove obsolete lightweight code once tests and traces stay green

This reduces regression risk and keeps `agent_pc` and `agent_android` runnable throughout the transition.
