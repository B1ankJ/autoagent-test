# Agent Executor (agent_pc + agent_android) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

## Current Status

Status snapshot as of 2026-05-06 after implementation and verification:

- Completed: Task 1 `Profile Schema`, Task 2 `Device Abstraction + PC Device`, Task 3 `Android Device`, Task 4 `Model Client + Action Parser`, Task 5 `Agent Loop + Prompts`, Task 6 `Screenshot Response Extractor`, Task 7 `AgentPcExecutor`, Task 8 `AgentAndroidExecutor`, Task 9 `Executor Registration`.
- Verification: `python3.11 -m pytest -q -m "not playwright and not android and not slow"` => `363 passed, 1 skipped, 18 deselected`; targeted new-module suite => `19 passed`; targeted `ruff check` on changed files => clean.
- Follow-up refactor: the original implementation now runs on a unified `agent_core` runtime split into `parser.py`, `result.py`, `runtime.py`, `handlers/`, and `devices/`, while `AgentPcExecutor` and `AgentAndroidExecutor` keep the same outer API and artifact layout.
- Reference alignment: the runtime semantics were tightened against the mature action/device patterns in `/Users/b1ankj/Desktop/2026/q2/apa_llm/` and `/Users/b1ankj/Desktop/2026/q2/Open-AutoGLM/`, but only for the AutoAgent action subset needed by `agent_pc` and `agent_android`.
- Current verification after the unification refactor: `python3.11 -m pytest -q -m "not playwright and not android and not slow"` => `408 passed, 1 skipped, 18 deselected`; targeted unified-agent suite => `74 passed`; targeted `ruff check` on unified runtime files => clean.

Implementation deviations already present in the repo:

- `src/autoagent/executors/agent_core/model_client.py` uses synchronous `httpx.post(...)` against `/chat/completions` instead of the `openai` SDK wrapper shown below.
- `src/autoagent/executors/agent_core/action_parser.py` currently parses `Action: click(...)`-style outputs instead of the `<answer>do(...)` protocol in the original draft plan.
- `tests/unit/test_android_device.py` exists and covers `AndroidDevice`, even though it is not listed in the original file table.

Execution notes:

- Finish the feature against the code as it actually exists in this branch.
- Preserve working completed pieces unless a later integration step proves they must change.
- Update this status section and the task checkboxes when follow-up fixes land.

**Goal:** Add `agent_pc` and `agent_android` executor modes that use a VLM-driven agent loop to automate any desktop app or Android app without pre-annotated selectors.

**Architecture:** A shared `agent_core` module holds the device abstraction, model client, action parser, and agent loop. `AgentPcExecutor` and `AgentAndroidExecutor` each wrap the loop in an async executor, then call a screenshot-based LLM extractor to read the response text. Both executors are registered in `_deps.py` alongside the existing three modes.

**Tech Stack:** Python 3.11, `openai` SDK (already in deps), `mss` + `pyautogui` (new, PC only), `subprocess`/`adb` (Android), `httpx` (already in deps), pytest.

---

## Files Created / Modified

| Path | Action | Purpose |
|---|---|---|
| `src/autoagent/profiles/schemas.py` | Modify | Add `AgentPcProfile`, `AgentAndroidProfile`, extend `Profile` union |
| `src/autoagent/models/api.py` | Modify | Extend `Mode` literal |
| `src/autoagent/executors/agent_core/__init__.py` | Create | Package marker |
| `src/autoagent/executors/agent_core/device.py` | Create | Abstract `Device` + `Screenshot` dataclass |
| `src/autoagent/executors/agent_core/pc_device.py` | Create | PC device: `mss` screenshot + `pyautogui` actions |
| `src/autoagent/executors/agent_core/android_device.py` | Create | Android device: `adb` screenshot + `adb shell input` actions |
| `src/autoagent/executors/agent_core/model_client.py` | Create | OpenAI-compatible VLM client (synchronous) |
| `src/autoagent/executors/agent_core/action_parser.py` | Create | Parse VLM output → action dict |
| `src/autoagent/executors/agent_core/agent_loop.py` | Create | Unified agent loop (screenshot → VLM → parse → execute) |
| `src/autoagent/executors/agent_core/prompts.py` | Create | System prompts for PC and Android |
| `src/autoagent/executors/agent_screenshot_extractor.py` | Create | Screenshot-based LLM response extractor |
| `src/autoagent/executors/agent_pc_executor.py` | Create | `AgentPcExecutor(Executor)` |
| `src/autoagent/executors/agent_android_executor.py` | Create | `AgentAndroidExecutor(Executor)` |
| `src/autoagent/api/_deps.py` | Modify | Register `agent_pc` and `agent_android` modes |
| `pyproject.toml` | Modify | Add `mss`, `pyautogui` dependencies |
| `tests/unit/test_agent_profile_schema.py` | Create | Schema parse + discriminator tests |
| `tests/unit/test_action_parser.py` | Create | Action parsing tests |
| `tests/unit/test_agent_loop.py` | Create | Agent loop unit tests (mocked device + VLM) |

---

### Task 1: Profile Schema — AgentPcProfile + AgentAndroidProfile

**Files:**
- Modify: `src/autoagent/profiles/schemas.py`
- Modify: `src/autoagent/models/api.py`
- Create: `tests/unit/test_agent_profile_schema.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/test_agent_profile_schema.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from autoagent.profiles.schemas import AgentAndroidProfile, AgentPcProfile, parse_profile


def test_agent_pc_profile_defaults():
    p = AgentPcProfile.model_validate({
        "name": "test", "platform": "agent_pc",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "type '{prompt}'", "response_hint": "latest reply",
    })
    assert p.max_steps == 20
    assert p.new_session_task_template is None


def test_agent_pc_task_template_format():
    p = AgentPcProfile.model_validate({
        "name": "test", "platform": "agent_pc",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "type '{prompt}' and send", "response_hint": "reply",
    })
    assert p.task_template.format(prompt="hello") == "type 'hello' and send"


def test_agent_android_profile_defaults():
    p = AgentAndroidProfile.model_validate({
        "name": "test", "platform": "agent_android",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "tap '{prompt}'", "response_hint": "reply",
        "serial": "emulator-5554",
    })
    assert p.serial == "emulator-5554"
    assert p.max_steps == 30


def test_parse_profile_dispatches_agent_pc():
    p = parse_profile({
        "name": "test", "platform": "agent_pc",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "do '{prompt}'", "response_hint": "reply",
    })
    assert isinstance(p, AgentPcProfile)


def test_parse_profile_dispatches_agent_android():
    p = parse_profile({
        "name": "test", "platform": "agent_android",
        "base_url": "http://x", "model": "m", "api_key": "k",
        "task_template": "do '{prompt}'", "response_hint": "reply",
    })
    assert isinstance(p, AgentAndroidProfile)


def test_agent_pc_missing_response_hint_raises():
    with pytest.raises(ValidationError):
        AgentPcProfile.model_validate({
            "name": "test", "platform": "agent_pc",
            "base_url": "http://x", "model": "m", "api_key": "k",
            "task_template": "do '{prompt}'",
        })


def test_agent_pc_missing_task_template_raises():
    with pytest.raises(ValidationError):
        AgentPcProfile.model_validate({
            "name": "test", "platform": "agent_pc",
            "base_url": "http://x", "model": "m", "api_key": "k",
            "response_hint": "reply",
        })
```

- [x] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_agent_profile_schema.py -v
```
Expected: ImportError or collection errors — `AgentPcProfile` not defined yet.

- [x] **Step 3: Add profiles to `schemas.py`**

Open `src/autoagent/profiles/schemas.py`. After the `AndroidProfile` class and before the `# ---- Union + parser ----` comment, add:

```python
# ---- Agent PC profile ----


class AgentPcProfile(BaseModel):
    name: str
    platform: Literal["agent_pc"]
    base_url: str
    model: str
    api_key: str
    task_template: str
    new_session_task_template: str | None = None
    response_hint: str
    max_steps: int = 20


# ---- Agent Android profile ----


class AgentAndroidProfile(BaseModel):
    name: str
    platform: Literal["agent_android"]
    serial: str | None = None
    base_url: str
    model: str
    api_key: str
    task_template: str
    new_session_task_template: str | None = None
    response_hint: str
    max_steps: int = 30
```

Then update the `Profile` union (replace the existing one):

```python
Profile = Annotated[
    ApiProfile | WebProfile | AndroidProfile | AgentPcProfile | AgentAndroidProfile,
    Field(discriminator="platform"),
]

_profile_adapter: TypeAdapter[Profile] = TypeAdapter(Profile)
```

- [x] **Step 4: Extend `Mode` in `models/api.py`**

In `src/autoagent/models/api.py`, change:

```python
Mode = Literal["api", "gui_pc_web", "gui_android"]
```

to:

```python
Mode = Literal["api", "gui_pc_web", "gui_android", "agent_pc", "agent_android"]
```

- [x] **Step 5: Run tests to verify they pass**

```bash
python3.11 -m pytest tests/unit/test_agent_profile_schema.py -v
```
Expected: 7 passed.

- [x] **Step 6: Run full fast suite to check no regressions**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```
Expected: all previously passing tests still pass.

- [x] **Step 7: Commit**

```bash
git add src/autoagent/profiles/schemas.py src/autoagent/models/api.py tests/unit/test_agent_profile_schema.py
git commit -m "feat: add AgentPcProfile and AgentAndroidProfile schemas"
```

---

### Task 2: agent_core — Device Abstraction + PC Device

**Files:**
- Create: `src/autoagent/executors/agent_core/__init__.py`
- Create: `src/autoagent/executors/agent_core/device.py`
- Create: `src/autoagent/executors/agent_core/pc_device.py`
- Modify: `pyproject.toml`

- [x] **Step 1: Add new dependencies to `pyproject.toml`**

In `pyproject.toml`, inside the `dependencies` list, add after `"rapidocr_onnxruntime>=1.4,<2.0",`:

```toml
  "mss>=9.0",
  "pyautogui>=0.9.54",
```

Then install:

```bash
uv pip install mss pyautogui
```

- [x] **Step 2: Create package init**

```bash
mkdir -p src/autoagent/executors/agent_core
```

Create `src/autoagent/executors/agent_core/__init__.py` with empty content:

```python
```

- [x] **Step 3: Create `device.py`**

```python
# src/autoagent/executors/agent_core/device.py
from __future__ import annotations

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
    def execute_action(self, action: dict) -> None:
        """Execute a parsed action dict. Raises on hard failure."""
```

- [x] **Step 4: Create `pc_device.py`**

```python
# src/autoagent/executors/agent_core/pc_device.py
from __future__ import annotations

import base64
import logging
import struct
from io import BytesIO

import mss
import mss.tools
import pyautogui

from .device import Device, Screenshot

_log = logging.getLogger(__name__)

pyautogui.FAILSAFE = False  # prevent corner-of-screen abort during automation


class PcDevice(Device):
    def capture(self) -> Screenshot:
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            grab = sct.grab(monitor)
            png_bytes = mss.tools.to_png(grab.rgb, grab.size)
            b64 = base64.b64encode(png_bytes).decode()
            return Screenshot(base64_data=b64, width=grab.width, height=grab.height)

    def execute_action(self, action: dict) -> None:
        t = action.get("_type")
        if t == "click":
            pyautogui.click(action["x"], action["y"])
        elif t == "type":
            pyautogui.typewrite(action["text"], interval=0.05)
        elif t == "scroll":
            if action.get("direction") == "up":
                pyautogui.scroll(300)
            else:
                pyautogui.scroll(-300)
        elif t == "press":
            pyautogui.press(action["key"])
        else:
            _log.warning("pc_device: unknown action %r", t)
```

- [x] **Step 5: Verify imports work**

```bash
python3.11 -c "from autoagent.executors.agent_core.pc_device import PcDevice; print('ok')"
```
Expected: `ok`

- [x] **Step 6: Commit**

```bash
git add pyproject.toml src/autoagent/executors/agent_core/
git commit -m "feat: add agent_core device abstraction and PcDevice"
```

---

### Task 3: agent_core — Android Device

**Files:**
- Create: `src/autoagent/executors/agent_core/android_device.py`

- [x] **Step 1: Create `android_device.py`**

```python
# src/autoagent/executors/agent_core/android_device.py
from __future__ import annotations

import base64
import logging
import struct
import subprocess
from typing import Any

from .device import Device, Screenshot

_log = logging.getLogger(__name__)


class AndroidDevice(Device):
    def __init__(self, serial: str | None = None) -> None:
        self._serial = serial
        self._adb_prefix = ["adb"] + (["-s", serial] if serial else [])

    def _run(self, cmd: list[str], *, capture: bool = False, timeout: int = 10) -> subprocess.CompletedProcess:
        return subprocess.run(
            self._adb_prefix + cmd,
            capture_output=capture,
            timeout=timeout,
        )

    def capture(self) -> Screenshot:
        result = subprocess.run(
            self._adb_prefix + ["exec-out", "screencap", "-p"],
            capture_output=True,
            timeout=15,
        )
        result.check_returncode()
        png_bytes = result.stdout
        b64 = base64.b64encode(png_bytes).decode()
        # PNG IHDR chunk: bytes 16-24 hold width and height as big-endian uint32
        w, h = struct.unpack(">II", png_bytes[16:24])
        return Screenshot(base64_data=b64, width=w, height=h)

    def execute_action(self, action: dict) -> None:
        t = action.get("_type")
        if t == "click":
            self._run(["shell", "input", "tap", str(action["x"]), str(action["y"])])
        elif t == "type":
            text = action["text"]
            # Escape shell-special chars; space → %s for adb input text
            escaped = (
                text.replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace(" ", "%s")
                .replace("&", "\\&")
            )
            self._run(["shell", "input", "text", escaped])
        elif t == "scroll":
            x1, y1 = action.get("x1", 500), action.get("y1", 500)
            x2, y2 = action.get("x2", 500), action.get("y2", 200 if action.get("direction") == "up" else 800)
            self._run(["shell", "input", "swipe",
                       str(x1), str(y1), str(x2), str(y2), "400"])
        elif t == "press":
            key = action.get("key", "").lower()
            keycode_map = {
                "back": "KEYCODE_BACK",
                "home": "KEYCODE_HOME",
                "enter": "KEYCODE_ENTER",
                "del": "KEYCODE_DEL",
            }
            keycode = keycode_map.get(key, key.upper())
            self._run(["shell", "input", "keyevent", keycode])
        else:
            _log.warning("android_device: unknown action %r", t)
```

- [x] **Step 2: Verify imports**

```bash
python3.11 -c "from autoagent.executors.agent_core.android_device import AndroidDevice; print('ok')"
```
Expected: `ok`

- [x] **Step 3: Commit**

```bash
git add src/autoagent/executors/agent_core/android_device.py
git commit -m "feat: add AndroidDevice for agent_core"
```

---

### Task 4: agent_core — Model Client + Action Parser

**Files:**
- Create: `src/autoagent/executors/agent_core/model_client.py`
- Create: `src/autoagent/executors/agent_core/action_parser.py`
- Create: `tests/unit/test_action_parser.py`

- [x] **Step 1: Write failing action parser tests**

```python
# tests/unit/test_action_parser.py
from __future__ import annotations

from autoagent.executors.agent_core.action_parser import parse_action


def test_parse_click():
    raw = '<think>need to click</think><answer>do(action="Click", element=[850, 420])</answer>'
    assert parse_action(raw) == {"_type": "click", "x": 850, "y": 420}


def test_parse_tap_android():
    raw = '<answer>do(action="Tap", element=[200, 300])</answer>'
    assert parse_action(raw) == {"_type": "click", "x": 200, "y": 300}


def test_parse_type():
    raw = '<answer>do(action="Type", text="hello world")</answer>'
    assert parse_action(raw) == {"_type": "type", "text": "hello world"}


def test_parse_finish():
    raw = '<answer>finish(message="Task done")</answer>'
    assert parse_action(raw) == {"_type": "finish", "message": "Task done"}


def test_parse_swipe_up():
    raw = '<answer>do(action="Swipe", start=[500, 800], end=[500, 200])</answer>'
    action = parse_action(raw)
    assert action["_type"] == "scroll"
    assert action["direction"] == "up"


def test_parse_swipe_down():
    raw = '<answer>do(action="Swipe", start=[500, 200], end=[500, 800])</answer>'
    action = parse_action(raw)
    assert action["_type"] == "scroll"
    assert action["direction"] == "down"


def test_parse_press_enter():
    raw = '<answer>do(action="Press", key="enter")</answer>'
    assert parse_action(raw) == {"_type": "press", "key": "enter"}


def test_parse_back():
    raw = '<answer>do(action="Back")</answer>'
    assert parse_action(raw) == {"_type": "press", "key": "back"}


def test_parse_malformed_returns_noop():
    assert parse_action("I don't know what to do") == {"_type": "noop"}


def test_parse_empty_returns_noop():
    assert parse_action("") == {"_type": "noop"}
```

- [x] **Step 2: Run to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_action_parser.py -v
```
Expected: ImportError — module not created yet.

- [x] **Step 3: Create `action_parser.py`**

```python
# src/autoagent/executors/agent_core/action_parser.py
from __future__ import annotations

import logging
import re
from typing import Any

_log = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL)


def parse_action(raw: str) -> dict[str, Any]:
    """Parse VLM text output into an action dict. Returns {"_type": "noop"} on failure."""
    if not raw:
        return {"_type": "noop"}

    text = _THINK_RE.sub("", raw).strip()

    m = _ANSWER_RE.search(text)
    if m:
        text = m.group(1).strip()

    # finish(message="...")
    m = re.search(r'finish\s*\(\s*message\s*=\s*["\']?(.*?)["\']?\s*\)', text, re.DOTALL)
    if m:
        return {"_type": "finish", "message": m.group(1).strip()}

    # do(action="...", ...)
    m = re.search(r'do\s*\(.*?action\s*=\s*["\'](\w[\w\s]*)["\']', text, re.DOTALL)
    if m:
        return _parse_do(m.group(1).strip(), text)

    _log.warning("action_parser: could not parse %r", raw[:200])
    return {"_type": "noop"}


def _parse_do(action_name: str, text: str) -> dict[str, Any]:
    name_lower = action_name.lower()

    if name_lower in ("click", "tap"):
        m = re.search(r'element\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]', text)
        if m:
            return {"_type": "click", "x": int(m.group(1)), "y": int(m.group(2))}

    elif name_lower == "type":
        m = re.search(r'text\s*=\s*"([^"]*)"', text)
        if m:
            return {"_type": "type", "text": m.group(1)}
        m = re.search(r"text\s*=\s*'([^']*)'", text)
        if m:
            return {"_type": "type", "text": m.group(1)}

    elif name_lower == "swipe":
        m = re.search(
            r'start\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*\].*?end\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]',
            text, re.DOTALL,
        )
        if m:
            x1, y1, x2, y2 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            direction = "up" if y2 < y1 else "down"
            return {"_type": "scroll", "direction": direction, "x1": x1, "y1": y1, "x2": x2, "y2": y2}

    elif name_lower in ("scroll",):
        m = re.search(r'direction\s*=\s*["\'](\w+)["\']', text)
        direction = m.group(1).lower() if m else "down"
        return {"_type": "scroll", "direction": direction}

    elif name_lower == "press":
        m = re.search(r'key\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            return {"_type": "press", "key": m.group(1).lower()}

    elif name_lower == "back":
        return {"_type": "press", "key": "back"}

    elif name_lower == "home":
        return {"_type": "press", "key": "home"}

    _log.warning("action_parser: unrecognized action %r in %r", action_name, text[:100])
    return {"_type": "noop"}
```

- [x] **Step 4: Run action parser tests**

```bash
python3.11 -m pytest tests/unit/test_action_parser.py -v
```
Expected: 10 passed.

- [x] **Step 5: Create `model_client.py`**

```python
# src/autoagent/executors/agent_core/model_client.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

_log = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    base_url: str
    model: str
    api_key: str
    timeout_sec: float = 30.0
    max_tokens: int = 1024
    temperature: float = 0.0


class ModelClient:
    def __init__(self, config: ModelConfig) -> None:
        self._config = config
        self._client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout_sec,
        )

    def call(self, messages: list[dict[str, Any]]) -> str:
        """Send messages to VLM, return raw text response. Synchronous."""
        response = self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
        )
        return response.choices[0].message.content or ""
```

- [x] **Step 6: Verify import**

```bash
python3.11 -c "from autoagent.executors.agent_core.model_client import ModelClient, ModelConfig; print('ok')"
```
Expected: `ok`

- [x] **Step 7: Commit**

```bash
git add src/autoagent/executors/agent_core/model_client.py src/autoagent/executors/agent_core/action_parser.py tests/unit/test_action_parser.py
git commit -m "feat: add agent_core model client and action parser"
```

---

### Task 5: agent_core — Agent Loop + Prompts

**Files:**
- Create: `src/autoagent/executors/agent_core/prompts.py`
- Create: `src/autoagent/executors/agent_core/agent_loop.py`
- Create: `tests/unit/test_agent_loop.py`

- [x] **Step 1: Write failing agent loop tests**

```python
# tests/unit/test_agent_loop.py
from __future__ import annotations

from unittest.mock import MagicMock

from autoagent.executors.agent_core.agent_loop import AgentLoop
from autoagent.executors.agent_core.device import Screenshot


def _screenshot() -> Screenshot:
    return Screenshot(base64_data="abc123==", width=1920, height=1080)


def test_loop_finishes_on_finish_action():
    device = MagicMock()
    device.capture.return_value = _screenshot()
    client = MagicMock()
    client.call.side_effect = [
        '<answer>do(action="Click", element=[100, 200])</answer>',
        '<answer>do(action="Type", text="hello")</answer>',
        '<answer>finish(message="done")</answer>',
    ]
    loop = AgentLoop(device, client, "sys", max_steps=10)
    result = loop.run("type hello and finish")
    assert result.finished is True
    assert result.step_count == 3
    assert result.finish_message == "done"
    assert device.execute_action.call_count == 2  # click + type, not finish


def test_loop_stops_at_max_steps():
    device = MagicMock()
    device.capture.return_value = _screenshot()
    client = MagicMock()
    client.call.return_value = '<answer>do(action="Click", element=[100, 200])</answer>'
    loop = AgentLoop(device, client, "sys", max_steps=3)
    result = loop.run("do something")
    assert result.finished is False
    assert result.step_count == 3
    assert device.execute_action.call_count == 3


def test_loop_skips_noop_but_counts_step():
    device = MagicMock()
    device.capture.return_value = _screenshot()
    client = MagicMock()
    client.call.side_effect = [
        "gibberish output",
        '<answer>finish(message="ok")</answer>',
    ]
    loop = AgentLoop(device, client, "sys", max_steps=10)
    result = loop.run("task")
    assert result.finished is True
    assert result.step_count == 2
    assert device.execute_action.call_count == 0  # noop not executed
```

- [x] **Step 2: Run to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_agent_loop.py -v
```
Expected: ImportError.

- [x] **Step 3: Create `prompts.py`**

```python
# src/autoagent/executors/agent_core/prompts.py
PC_SYSTEM_PROMPT = """你是一个桌面GUI自动化助手。你会看到当前桌面截图，以及需要完成的任务。
每次只能输出一个操作，严格遵循下方格式。

可用操作：
- do(action="Click", element=[x, y])         — 点击像素坐标 (x, y)
- do(action="Type", text="内容")              — 在当前输入框输入文本（会覆盖已有内容）
- do(action="Scroll", direction="down")       — 滚动；direction 为 "up" 或 "down"
- do(action="Press", key="enter")             — 按键盘按键（enter/escape/tab/ctrl+a 等）
- finish(message="完成说明")                   — 任务完成，结束并说明结果

输出格式（严格遵守，不得有额外内容）：
<think>简短分析</think>
<answer>do(action="...", ...)</answer>

或：
<think>简短分析</think>
<answer>finish(message="...")</answer>

注意：
1. 坐标为截图中的实际像素坐标
2. 只有任务完全完成后才调用 finish
3. 每次只输出一个操作
"""

ANDROID_SYSTEM_PROMPT = """你是一个Android手机自动化助手。你会看到手机屏幕截图，以及需要完成的任务。
每次只能输出一个操作，严格遵循下方格式。

可用操作：
- do(action="Tap", element=[x, y])                          — 点击坐标 (x, y)
- do(action="Type", text="内容")                             — 输入文本（自动清除现有内容）
- do(action="Swipe", start=[x1,y1], end=[x2,y2])            — 滑动手势
- do(action="Press", key="back")                            — 按键：back/home/enter
- do(action="Back")                                         — 返回上一页
- finish(message="完成说明")                                  — 任务完成

输出格式（严格遵守）：
<think>简短分析</think>
<answer>do(action="...", ...)</answer>

或：
<think>简短分析</think>
<answer>finish(message="...")</answer>

注意：
1. 坐标为截图实际像素坐标
2. 只有任务完全完成后才调用 finish
3. 每次只输出一个操作
"""
```

- [x] **Step 4: Create `agent_loop.py`**

```python
# src/autoagent/executors/agent_core/agent_loop.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .action_parser import parse_action
from .device import Device, Screenshot
from .model_client import ModelClient

_log = logging.getLogger(__name__)


@dataclass
class AgentResult:
    finished: bool       # True = agent called finish(); False = max_steps reached
    finish_message: str  # agent's finish message (for logging only)
    step_count: int


class AgentLoop:
    def __init__(
        self,
        device: Device,
        client: ModelClient,
        system_prompt: str,
        max_steps: int,
    ) -> None:
        self._device = device
        self._client = client
        self._system_prompt = system_prompt
        self._max_steps = max_steps

    def run(self, task: str) -> AgentResult:
        context: list[dict[str, Any]] = []
        for step in range(1, self._max_steps + 1):
            screenshot = self._device.capture()
            messages = self._build_messages(task, screenshot, context, step)
            raw = self._client.call(messages)
            _log.debug("agent_loop step=%d raw=%r", step, raw[:200])
            action = parse_action(raw)
            context.append({"step": step, "action_text": raw})
            if action["_type"] == "finish":
                return AgentResult(
                    finished=True,
                    finish_message=action.get("message", ""),
                    step_count=step,
                )
            if action["_type"] != "noop":
                self._device.execute_action(action)
        return AgentResult(
            finished=False,
            finish_message="max_steps reached",
            step_count=self._max_steps,
        )

    def _build_messages(
        self,
        task: str,
        screenshot: Screenshot,
        context: list[dict[str, Any]],
        step: int,
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
        ]
        # Inject previous assistant actions as text (no images for past steps)
        for entry in context:
            messages.append({"role": "assistant", "content": entry["action_text"]})
        # Current step: image + task text
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{screenshot.base64_data}"},
                },
                {
                    "type": "text",
                    "text": f"任务：{task}\n当前步骤：{step}/{self._max_steps}\n请决定下一步操作。",
                },
            ],
        })
        return messages
```

- [x] **Step 5: Run agent loop tests**

```bash
python3.11 -m pytest tests/unit/test_agent_loop.py -v
```
Expected: 3 passed.

- [x] **Step 6: Run full fast suite**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```
Expected: all pass.

- [x] **Step 7: Commit**

```bash
git add src/autoagent/executors/agent_core/agent_loop.py src/autoagent/executors/agent_core/prompts.py tests/unit/test_agent_loop.py
git commit -m "feat: add agent_loop and system prompts"
```

---

### Task 6: Screenshot Response Extractor

**Files:**
- Create: `src/autoagent/executors/agent_screenshot_extractor.py`

No new unit tests: this module is structurally identical to `web_response_llm_extractor.py` (same httpx call pattern, same `LLMExtractionResult` return). The web extractor tests cover the pattern.

- [x] **Step 1: Create `agent_screenshot_extractor.py`**

```python
# src/autoagent/executors/agent_screenshot_extractor.py
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from autoagent.executors.agent_core.device import Screenshot
from autoagent.executors.response_llm_extractor import LLMExtractionResult

_log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是一个截图内容提取助手。用户会给你一张屏幕截图和一段内容描述。\n"
    "你的唯一任务：从截图中找到并完整提取描述所指的文字内容，原样返回，不做任何改写或总结。\n"
    "规则：\n"
    "- 只返回目标文字，不加前缀、解释或格式符号。\n"
    "- 如果截图中找不到描述所指的内容，返回空字符串。\n"
    "- 严格按给定 JSON schema 返回。"
)

_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "screenshot_response_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"response": {"type": "string"}},
        "required": ["response"],
    },
}


async def extract_response_from_screenshot(
    *,
    screenshot: Screenshot,
    response_hint: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
) -> LLMExtractionResult:
    t0 = time.monotonic()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{screenshot.base64_data}"},
                },
                {"type": "text", "text": f"请提取以下内容的文字：{response_hint}"},
            ],
        },
    ]
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0.0,
        "response_format": {
            "type": "json_schema",
            "json_schema": _RESPONSE_SCHEMA,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        latency_ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code != 200:
            return LLMExtractionResult(
                text="", error=f"http_{resp.status_code}",
                latency_ms=latency_ms, status_code=resp.status_code,
                raw_response_text=resp.text,
            )
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return LLMExtractionResult(
            text=parsed.get("response", ""), error=None, latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.monotonic() - t0) * 1000)
        _log.debug("agent_screenshot_extractor error: %r", exc)
        return LLMExtractionResult(text="", error="connect", latency_ms=latency_ms)
```

- [x] **Step 2: Verify import**

```bash
python3.11 -c "from autoagent.executors.agent_screenshot_extractor import extract_response_from_screenshot; print('ok')"
```
Expected: `ok`

- [x] **Step 3: Commit**

```bash
git add src/autoagent/executors/agent_screenshot_extractor.py
git commit -m "feat: add agent_screenshot_extractor for VLM response extraction from screenshots"
```

---

### Task 7: AgentPcExecutor

**Files:**
- Create: `src/autoagent/executors/agent_pc_executor.py`

- [x] **Step 1: Create `agent_pc_executor.py`**

```python
# src/autoagent/executors/agent_pc_executor.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from autoagent.executors.agent_core.agent_loop import AgentLoop
from autoagent.executors.agent_core.model_client import ModelClient, ModelConfig
from autoagent.executors.agent_core.pc_device import PcDevice
from autoagent.executors.agent_core.prompts import PC_SYSTEM_PROMPT
from autoagent.executors.agent_screenshot_extractor import extract_response_from_screenshot
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AgentPcProfile

_log = logging.getLogger(__name__)


class AgentPcExecutor(Executor):
    """VLM-driven executor for `mode=agent_pc`. Works on any desktop application."""

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, AgentPcProfile):
            raise TypeError(
                f"AgentPcExecutor requires AgentPcProfile, got {type(profile).__name__}"
            )

        device = PcDevice()
        client = ModelClient(ModelConfig(
            base_url=profile.base_url,
            model=profile.model,
            api_key=profile.api_key,
        ))
        loop = AgentLoop(device, client, PC_SYSTEM_PROMPT, profile.max_steps)
        responses: list[str] = []
        ev_loop = asyncio.get_running_loop()

        for prompt in sample.prompts:
            if sample.new_session and profile.new_session_task_template:
                template = profile.new_session_task_template
            else:
                template = profile.task_template
            task = template.format(prompt=prompt)

            _log.debug("agent_pc sample=%s task=%r", sample.id, task[:100])
            await ev_loop.run_in_executor(None, loop.run, task)

            screenshot = await ev_loop.run_in_executor(None, device.capture)
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
            _log.debug(
                "agent_pc sample=%s extraction: error=%s latency_ms=%s text=%r",
                sample.id, extraction.error, extraction.latency_ms, extraction.text[:80],
            )

        return responses
```

- [x] **Step 2: Verify import**

```bash
python3.11 -c "from autoagent.executors.agent_pc_executor import AgentPcExecutor; print('ok')"
```
Expected: `ok`

- [x] **Step 3: Commit**

```bash
git add src/autoagent/executors/agent_pc_executor.py
git commit -m "feat: add AgentPcExecutor"
```

---

### Task 8: AgentAndroidExecutor

**Files:**
- Create: `src/autoagent/executors/agent_android_executor.py`

- [x] **Step 1: Create `agent_android_executor.py`**

```python
# src/autoagent/executors/agent_android_executor.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from autoagent.executors.agent_core.agent_loop import AgentLoop
from autoagent.executors.agent_core.android_device import AndroidDevice
from autoagent.executors.agent_core.model_client import ModelClient, ModelConfig
from autoagent.executors.agent_core.prompts import ANDROID_SYSTEM_PROMPT
from autoagent.executors.agent_screenshot_extractor import extract_response_from_screenshot
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AgentAndroidProfile

_log = logging.getLogger(__name__)


class AgentAndroidExecutor(Executor):
    """VLM-driven executor for `mode=agent_android`. Works on any Android app."""

    async def execute(self, sample: Sample, profile: Any, ctx: ExecutorContext) -> list[str]:
        if not isinstance(profile, AgentAndroidProfile):
            raise TypeError(
                f"AgentAndroidExecutor requires AgentAndroidProfile, got {type(profile).__name__}"
            )

        device = AndroidDevice(serial=profile.serial)
        client = ModelClient(ModelConfig(
            base_url=profile.base_url,
            model=profile.model,
            api_key=profile.api_key,
        ))
        loop = AgentLoop(device, client, ANDROID_SYSTEM_PROMPT, profile.max_steps)
        responses: list[str] = []
        ev_loop = asyncio.get_running_loop()

        for prompt in sample.prompts:
            if sample.new_session and profile.new_session_task_template:
                template = profile.new_session_task_template
            else:
                template = profile.task_template
            task = template.format(prompt=prompt)

            _log.debug("agent_android sample=%s task=%r", sample.id, task[:100])
            await ev_loop.run_in_executor(None, loop.run, task)

            screenshot = await ev_loop.run_in_executor(None, device.capture)
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
            _log.debug(
                "agent_android sample=%s extraction: error=%s latency_ms=%s text=%r",
                sample.id, extraction.error, extraction.latency_ms, extraction.text[:80],
            )

        return responses
```

- [x] **Step 2: Verify import**

```bash
python3.11 -c "from autoagent.executors.agent_android_executor import AgentAndroidExecutor; print('ok')"
```
Expected: `ok`

- [x] **Step 3: Commit**

```bash
git add src/autoagent/executors/agent_android_executor.py
git commit -m "feat: add AgentAndroidExecutor"
```

---

### Task 9: Executor Registration

**Files:**
- Modify: `src/autoagent/api/_deps.py`

`Mode` in `models/api.py` was already updated in Task 1.

- [x] **Step 1: Update `_deps.py`**

In `src/autoagent/api/_deps.py`, add imports after the existing executor imports (lines 8-11):

```python
from autoagent.executors.agent_android_executor import AgentAndroidExecutor
from autoagent.executors.agent_pc_executor import AgentPcExecutor
```

In `_build_executor()`, add two `elif` branches after the `elif mode == "gui_android":` branch:

```python
        elif mode == "agent_pc":
            _executors[mode] = AgentPcExecutor()
        elif mode == "agent_android":
            _executors[mode] = AgentAndroidExecutor()
```

The complete `_build_executor` function should read:

```python
def _build_executor(mode: str) -> Executor:
    if mode not in _executors:
        if mode == "api":
            _executors[mode] = ApiExecutor()
        elif mode == "gui_pc_web":
            _executors[mode] = WebExecutor()
        elif mode == "gui_android":
            _executors[mode] = AndroidExecutor()
        elif mode == "agent_pc":
            _executors[mode] = AgentPcExecutor()
        elif mode == "agent_android":
            _executors[mode] = AgentAndroidExecutor()
        else:
            raise ValueError(f"mode {mode} not supported in this build")
    return _executors[mode]
```

- [x] **Step 2: Run full fast suite**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```
Expected: all previously passing tests still pass (all new executor tests now included).

- [x] **Step 3: Check ruff**

```bash
python3.11 -m ruff check src/autoagent/executors/agent_core/ src/autoagent/executors/agent_pc_executor.py src/autoagent/executors/agent_android_executor.py src/autoagent/executors/agent_screenshot_extractor.py src/autoagent/api/_deps.py
```
Expected: no errors. Fix any that appear before committing.

- [x] **Step 4: Commit**

```bash
git add src/autoagent/api/_deps.py
git commit -m "feat: register agent_pc and agent_android modes in executor factory"
```

---

## Verify Full Test Count

After Task 9 completes, run:

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow and not agent_pc and not agent_android"
```

Expected: fast suite passes with ≥ 343 tests (323 baseline + 7 schema + 10 parser + 3 loop).

## Integration Testing (manual, requires real VLM + real screen/device)

These are `@pytest.mark.agent_pc` / `@pytest.mark.agent_android` — excluded from fast suite.

**agent_pc smoke:**
1. Open any chat application on the desktop
2. Create a YAML profile:
```yaml
name: smoke_pc
platform: agent_pc
base_url: http://your-vlm/v1
model: your-model
api_key: EMPTY
task_template: "在输入框中输入 '{prompt}' 并发送，等待AI回复完整出现后停止"
response_hint: "对话区域最新一条AI助手的回复消息完整文本"
max_steps: 15
```
3. Run a single-sample batch with `mode: agent_pc` and verify `responses` is non-empty.

**agent_android smoke:**
1. Connect an Android device with a chat app open
2. Create a YAML profile:
```yaml
name: smoke_android
platform: agent_android
serial: your-device-serial
base_url: http://your-vlm/v1
model: your-model
api_key: EMPTY
task_template: "在输入框中输入 '{prompt}' 并发送，等待AI回复完整出现后停止"
response_hint: "对话区域最新一条AI助手的回复消息完整文本"
max_steps: 20
```
3. Run a batch and verify `responses` is non-empty.
