# Agent Executor (agent_pc + agent_android) — Design

**Date:** 2026-05-06
**Status:** Approved

## Motivation

Current `web` and `android` executors require predefined CSS selectors or UI locators captured during a Builder session. This prevents testing apps where selectors are unavailable or unstable (non-browser desktop apps, any app without prior Builder setup). The new `agent_pc` and `agent_android` platforms replace static selectors with a VLM-driven agent loop: the model sees a screenshot, decides the next action, and repeats until the task is done. This covers any desktop application (PC) or Android app without any pre-annotation.

## Scope

- `src/autoagent/profiles/schemas.py` — add `AgentPcProfile`, `AgentAndroidProfile`
- `src/autoagent/executors/agent_core/` — new shared module: loop, model client, action parser, device abstraction
- `src/autoagent/executors/agent_pc_executor.py` — new executor
- `src/autoagent/executors/agent_android_executor.py` — new executor
- `src/autoagent/executors/agent_screenshot_extractor.py` — screenshot-based LLM response extractor
- `src/autoagent/scheduler/` — register new modes
- `tests/unit/test_agent_loop.py`, `test_action_parser.py`, `test_agent_profile_schema.py`

**Out of scope:** Builder UI for agent profiles, frontend changes, task planning / playbook caching / retry logic from reference projects (AutoAgent Test's `Executor.run()` already handles retry).

## Reference Projects

Code is extracted and unified from:
- `apa_llm` (`smartapa/`): PC agent — `mss` screenshots, `pyautogui` actions, VLM loop
- `Open-AutoGLM` (`phone_agent/`): Android agent — `adb` screenshots, `adb shell input` actions, VLM loop

Only the execution layer is copied. Task planner, playbook cache, state tracker, and retry logic from `apa_llm` are **not** included.

## 1. Profile Schema

Two new platform types added to the discriminated union in `schemas.py`:

```python
class AgentPcProfile(BaseModel):
    name: str
    platform: Literal["agent_pc"]
    base_url: str
    model: str
    api_key: str
    task_template: str               # e.g. "在输入框输入 '{prompt}' 并发送，等待AI回复完整出现"
    new_session_task_template: str | None = None  # used when sample.new_session=True
    response_hint: str               # e.g. "对话区域最新一条AI助手的回复消息完整文本"
    max_steps: int = 20


class AgentAndroidProfile(BaseModel):
    name: str
    platform: Literal["agent_android"]
    serial: str | None = None        # adb device serial; None = first connected device
    base_url: str
    model: str
    api_key: str
    task_template: str
    new_session_task_template: str | None = None
    response_hint: str
    max_steps: int = 30
```

`task_template` contains exactly one placeholder: `{prompt}`. At runtime, `.format(prompt=prompt)` is applied. No other placeholders.

YAML example:

```yaml
name: chatgpt_agent
platform: agent_pc
base_url: http://localhost:8000/v1
model: Qwen2.5-VL-7B
api_key: EMPTY
task_template: "在输入框中输入 '{prompt}' 并发送，等待AI回复完整出现后停止"
new_session_task_template: "点击新建对话，然后在输入框中输入 '{prompt}' 并发送，等待AI回复完整出现"
response_hint: "对话区域最新一条AI助手的回复消息完整文本"
max_steps: 20
```

## 2. agent_core Module

Location: `src/autoagent/executors/agent_core/`

### 2.1 Device Abstraction (`device.py`)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Screenshot:
    base64_data: str
    width: int
    height: int

class Device(ABC):
    @abstractmethod
    def capture(self) -> Screenshot: ...

    @abstractmethod
    def execute_action(self, action: dict) -> bool:
        """Execute a parsed action. Returns True on success."""
```

### 2.2 PC Device (`pc_device.py`)

- `capture()`: uses `mss` to grab the primary monitor, returns base64 PNG
- `execute_action()`: dispatches to `pyautogui` based on action type:
  - `click(x, y)` → `pyautogui.click(x, y)`
  - `type(text)` → `pyautogui.typewrite(text, interval=0.05)`
  - `scroll(direction, amount)` → `pyautogui.scroll(...)`
  - `press(key)` → `pyautogui.press(key)`
  - `finish(message)` → returns immediately (handled by loop)

### 2.3 Android Device (`android_device.py`)

- `capture()`: `adb -s {serial} exec-out screencap -p` → base64 PNG
- `execute_action()`: dispatches to `adb shell input`:
  - `click(x, y)` → `adb shell input tap x y`
  - `type(text)` → `adb shell input text '{text}'` (with ADB Keyboard for non-ASCII)
  - `scroll(direction, amount)` → `adb shell input swipe ...`
  - `press(key)` → `adb shell input keyevent KEY`
  - `finish(message)` → handled by loop

### 2.4 Model Client (`model_client.py`)

OpenAI-compatible API call with vision:

```python
@dataclass
class ModelConfig:
    base_url: str
    model: str
    api_key: str
    timeout_sec: float = 30.0

class ModelClient:
    def __init__(self, config: ModelConfig): ...
    def call(self, messages: list[dict]) -> str:
        """Send messages to VLM, return raw text response."""
```

Uses `httpx` (already a project dependency). Sends screenshot as base64 image in the user message alongside the task text and action history.

### 2.5 Action Parser (`action_parser.py`)

Parses VLM text output into a structured action dict. Expected VLM output format (from system prompt):

```
Action: click(850, 420)
Action: type("Hello world")
Action: finish("Task completed")
```

Parser extracts action name and arguments. On parse failure, returns `{"_type": "noop"}` (logged, loop continues to next step).

Action dict structure:
```python
{"_type": "click", "x": 850, "y": 420}
{"_type": "type", "text": "Hello world"}
{"_type": "scroll", "direction": "down", "amount": 3}
{"_type": "press", "key": "enter"}
{"_type": "finish", "message": "Task completed"}
{"_type": "noop"}  # parse failure fallback
```

### 2.6 Agent Loop (`agent_loop.py`)

```python
@dataclass
class AgentResult:
    finished: bool        # True = agent called finish(); False = max_steps reached
    finish_message: str   # agent's finish message (for logs only, not used as response)
    step_count: int

class AgentLoop:
    def __init__(self, device: Device, client: ModelClient,
                 system_prompt: str, max_steps: int): ...

    def run(self, task: str) -> AgentResult:
        context: list[dict] = []
        for step in range(1, self.max_steps + 1):
            screenshot = self.device.capture()
            messages = self._build_messages(task, screenshot, context, step)
            raw = self.client.call(messages)
            action = parse_action(raw)
            context.append({"step": step, "action_text": raw})
            if action["_type"] == "finish":
                return AgentResult(finished=True,
                                   finish_message=action.get("message", ""),
                                   step_count=step)
            if action["_type"] != "noop":
                self.device.execute_action(action)
        return AgentResult(finished=False, finish_message="max_steps reached",
                           step_count=self.max_steps)
```

### 2.7 System Prompts (`prompts.py`)

Two prompts (Chinese), one per platform. Each instructs the VLM to:
- Analyse the current screenshot
- Choose the single best next action
- Output exactly one `Action: <name>(args)` line
- Call `finish(message)` only when the interaction task is fully complete

PC prompt references pyautogui-style coordinates. Android prompt references touch coordinates.

## 3. Response Extraction (`agent_screenshot_extractor.py`)

After `AgentLoop.run()` returns, the executor takes a final screenshot and calls the extractor:

```python
async def extract_response_from_screenshot(
    *,
    screenshot: Screenshot,
    response_hint: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
) -> LLMExtractionResult:
    """
    Send screenshot + response_hint to VLM, return the text found.
    System prompt: "从截图中找到并完整提取以下内容的文字：{response_hint}"
    Uses the same LLMExtractionResult dataclass as web/android extractors.
    """
```

Reuses `LLMExtractionResult` from `android_response_llm_extractor`. On any exception, returns `LLMExtractionResult(text="", error="connect", latency_ms=0)`.

## 4. Executor Integration

### 4.1 AgentPcExecutor

```python
class AgentPcExecutor(Executor):
    async def execute(self, sample: Sample, profile: AgentPcProfile,
                      ctx: ExecutorContext) -> list[str]:
        device = PcDevice()
        client = ModelClient(ModelConfig(profile.base_url, profile.model, profile.api_key))
        loop = AgentLoop(device, client, PC_SYSTEM_PROMPT, profile.max_steps)
        responses: list[str] = []

        for prompt in sample.prompts:
            if sample.new_session and profile.new_session_task_template:
                template = profile.new_session_task_template
            else:
                template = profile.task_template
            task = template.format(prompt=prompt)

            # Run synchronous agent loop in thread to avoid blocking event loop
            loop_result: AgentResult = await asyncio.get_event_loop().run_in_executor(
                None, loop.run, task
            )

            # Capture final screenshot and extract response
            screenshot = await asyncio.get_event_loop().run_in_executor(None, device.capture)
            extraction = await extract_response_from_screenshot(
                screenshot=screenshot,
                response_hint=profile.response_hint,
                base_url=profile.base_url,
                model=profile.model,
                api_key=profile.api_key,
            )
            responses.append(extraction.text)
            ctx.llm_responses.append(extraction.text)
            ctx.llm_errors.append(extraction.error)

        return responses
```

`AgentAndroidExecutor` is identical, substituting `AndroidDevice(serial=profile.serial)` and `ANDROID_SYSTEM_PROMPT`.

### 4.2 Scheduler Registration

`src/autoagent/scheduler/` maps `sample.mode` to executor class. Add:

```python
"agent_pc":      AgentPcExecutor,
"agent_android": AgentAndroidExecutor,
```

`sample.mode` is derived from `profile.platform` when not explicitly set.

## 5. Dependencies

Add to `pyproject.toml`:
- `mss` — cross-platform screenshot (PC)
- `pyautogui` — PC mouse/keyboard control

`adb` is already available for Android. `httpx` already in project.

## 6. Testing

### Unit tests (no real device / VLM)

**`tests/unit/test_agent_loop.py`**
- Mock `Device` returns fixed screenshot; mock `ModelClient.call()` returns a sequence: `click(100,200)` → `type("hello")` → `finish("done")`. Assert `AgentResult.finished=True`, `step_count=3`.
- Mock returns only noop actions for `max_steps` iterations. Assert `AgentResult.finished=False`.

**`tests/unit/test_action_parser.py`**
- `"Action: click(850, 420)"` → `{"_type": "click", "x": 850, "y": 420}`
- `"Action: type(\"hello world\")"` → `{"_type": "type", "text": "hello world"}`
- `"Action: finish(\"Task done\")"` → `{"_type": "finish", "message": "Task done"}`
- Malformed output → `{"_type": "noop"}`

**`tests/unit/test_agent_profile_schema.py`**
- `AgentPcProfile` and `AgentAndroidProfile` parse from dict correctly
- `task_template.format(prompt="test")` substitution works
- Discriminated union correctly selects `AgentPcProfile` for `platform: agent_pc`
- Missing `response_hint` or `task_template` raises `ValidationError`

### Integration tests (marked, excluded from fast suite)

- `@pytest.mark.agent_pc` — real screen, real VLM
- `@pytest.mark.agent_android` — real device, real VLM
- Fast suite exclude flag: `-m "not playwright and not android and not slow and not agent_pc and not agent_android"`

## 7. Data Flow

```
Sample(prompts=["p1","p2"], new_session=False)
  └─ AgentPcExecutor.execute()
       for each prompt:
         task = task_template.format(prompt=prompt)
         AgentLoop.run(task)  [in thread executor]
           ├─ step 1: PcDevice.capture() → VLM → parse → pyautogui.click(...)
           ├─ step 2: capture → VLM → parse → pyautogui.typewrite(...)
           └─ step N: capture → VLM → parse → finish("done")
         PcDevice.capture()  [final screenshot]
         extract_response_from_screenshot(screenshot, response_hint)
           └─ VLM sees screenshot + "对话区域最新一条AI助手的回复消息完整文本"
                └─ returns extracted text
         responses.append(text)
  └─ SampleResult(responses=[...], llm_responses=[...])
```
