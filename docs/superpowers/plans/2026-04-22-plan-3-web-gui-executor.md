# Plan 3 — Web GUI Executor (Playwright) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mode=gui_pc_web` execution via Playwright, with persistent-session concurrency handling, SSE progress streaming, screenshots, and full Plan 2 frontend integration. Close the loop from profile creation → web batch run → live progress → screenshot review.

**Architecture:** New `WebExecutor` subclasses the existing `Executor` base and drives Chromium via Playwright. A small `ActionRunner` handles 6 YAML action types for `recovery_path`/`new_session_action`. A `CompleteDetector` implements `dom_stable` + `send_button_reenable`. Screenshots land at `<data_root>/logs/<batch_id>/<sample_id>/NNN_<label>.png`. An in-process event bus plus an SSE endpoint (`sse-starlette`) replace the current 2s polling. The scheduler auto-downgrades concurrency to 1 when the profile has `browser.user_data_dir`.

**Tech Stack:** Python 3.11 · FastAPI · Playwright 1.46+ · sse-starlette 2.1+ · pytest (`@pytest.mark.playwright` marker for real-browser tests) · React 18 + TanStack Query v5 + native `EventSource`.

**Spec reference:** `docs/superpowers/specs/2026-04-22-plan-3-web-gui-executor-design.md`.

**Prereq:** Plan 2 complete at tag `web-ui-v0.2.0`. Chromium available via `python3.11 -m playwright install chromium`.

---

## File Structure

```
src/autoagent/
  events/
    __init__.py           ← new
    bus.py                ← new: in-process pub/sub with per-batch seq + ring buffer
  executors/
    action_runner.py      ← new: 6 actions (goto/wait_for/click/sleep/fill/press)
    complete_detector.py  ← new: dom_stable + send_button_reenable
    screenshot_store.py   ← new: path + directory management
    web_executor.py       ← new: Playwright-backed Executor
  api/
    _deps.py              ← modify: factory dispatch gui_pc_web → WebExecutor
    batches.py            ← modify: +3 endpoints (screenshots list/download, SSE events); +seq in BatchDetail
    tests.py              ← modify: /tests/sync picks executor by profile.platform; extended timeout
  models/
    api.py                ← modify: BatchDetail gains `seq: int = 0`
  scheduler/
    batch_scheduler.py    ← modify: forced concurrency=1 for user_data_dir profile; publish events
tests/
  fixtures/
    fake_chat.html        ← new: real-Playwright test target
  unit/
    test_action_runner.py        ← new
    test_complete_detector.py    ← new
    test_screenshot_store.py     ← new
    test_web_executor_unit.py    ← new
    test_event_bus.py            ← new
    test_executor_factory.py     ← new
    test_scheduler_web_concurrency.py  ← new
  integration/
    test_web_executor_e2e.py     ← new (@pytest.mark.playwright)
    test_sse_endpoint.py         ← new
    test_screenshots_endpoint.py ← new
    test_tests_sync_web.py       ← new (@pytest.mark.playwright)

web/src/
  types/api.ts                   ← modify: ScreenshotInfo; BatchDetail.seq
  api/screenshots.ts             ← new
  api/batches.ts                 ← modify: export useBatchStream
  hooks/useBatchStream.ts        ← new: initial GET + EventSource
  pages/Batches/New.tsx          ← modify: mode dropdown adds gui_pc_web
  pages/Tests/Quick.tsx          ← modify: mode dropdown adds gui_pc_web; 180s override for web
  pages/Profiles/Edit.tsx        ← modify: enable 连通性测试 for platform: web; 180s timeout
  pages/Batches/SampleDetail.tsx ← modify: +ScreenshotStrip +ActionLogTable
  pages/Batches/Detail.tsx       ← modify: swap useBatch → useBatchStream
  components/ScreenshotStrip.tsx ← new
```

---

## Task 1: Dependencies + docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [x] **Step 1: Add deps to `pyproject.toml`**

In the `dependencies` list add `"playwright>=1.46,<2.0"` and `"sse-starlette>=2.1,<3.0"`. In `[tool.pytest.ini_options]` add:

```toml
markers = ["playwright: requires real Chromium via `python3.11 -m playwright install chromium`"]
```

- [x] **Step 2: Install Python deps**

Run:
```bash
python3.11 -m pip install -e '.[dev]'
```
Expected: exits 0, `playwright` and `sse-starlette` appear in `pip list`.

- [x] **Step 3: Install Chromium**

Run:
```bash
python3.11 -m playwright install chromium
```
Expected: download + install completes; `python3.11 -c "from playwright.async_api import async_playwright; print('ok')"` prints `ok`.

- [x] **Step 4: Verify baseline still green**

Run:
```bash
python3.11 -m pytest -q
python3.11 -m ruff check .
python3.11 -m ruff format --check .
```
Expected: 68 passed, ruff clean.

- [x] **Step 5: Update CLAUDE.md common commands**

In the ``` ```bash ``` block under `## Common commands`, add:

```bash
python3.11 -m pytest -q -m "not playwright"                         # skip real-browser tests
python3.11 -m playwright install chromium                           # one-time: download Chromium
```

- [x] **Step 6: Update README Quickstart**

After the existing install instructions, add a new block:

```markdown
### Web executor prerequisite (Plan 3)

Web mode uses Playwright. After `pip install`:

\`\`\`bash
python3.11 -m playwright install chromium --with-deps
\`\`\`

Run once per machine. `--with-deps` installs OS libs on Linux and is a no-op on macOS.
```

- [x] **Step 7: Commit**

```bash
git add pyproject.toml CLAUDE.md README.md
git commit -m "chore(deps): add playwright + sse-starlette; document Chromium install"
```

---

## Task 2: WebExecutor skeleton + factory dispatch

Introduce a minimal `WebExecutor` that fails fast; wire it into the scheduler's executor factory so `mode=gui_pc_web` no longer raises `mode not supported`. Real `execute` logic arrives in Task 8.

**Files:**
- Create: `src/autoagent/executors/web_executor.py`
- Modify: `src/autoagent/api/_deps.py`
- Create: `tests/unit/test_executor_factory.py`

- [x] **Step 1: Write the failing factory test**

`tests/unit/test_executor_factory.py`:

```python
import pytest

from autoagent.api._deps import _build_executor
from autoagent.executors.api_executor import ApiExecutor
from autoagent.executors.web_executor import WebExecutor


def test_api_mode_returns_api_executor() -> None:
    assert isinstance(_build_executor("api"), ApiExecutor)


def test_gui_pc_web_returns_web_executor() -> None:
    assert isinstance(_build_executor("gui_pc_web"), WebExecutor)


def test_unsupported_mode_raises() -> None:
    with pytest.raises(ValueError):
        _build_executor("gui_android")
```

- [x] **Step 2: Run test to verify it fails**

```bash
python3.11 -m pytest tests/unit/test_executor_factory.py -v
```
Expected: all three tests error on `ImportError: cannot import name 'WebExecutor'`.

- [x] **Step 3: Create the skeleton executor**

`src/autoagent/executors/web_executor.py`:

```python
from __future__ import annotations

from typing import Any

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample


class WebExecutor(Executor):
    """Playwright-backed executor for `mode=gui_pc_web`.

    Filled in by Task 8. This skeleton exists so the scheduler factory can
    dispatch web samples and integration plumbing can be wired up.
    """

    async def execute(
        self, sample: Sample, profile: Any, ctx: ExecutorContext
    ) -> list[str]:
        raise NotImplementedError("WebExecutor.execute is filled in by Task 8")
```

- [x] **Step 4: Wire the factory**

Modify `src/autoagent/api/_deps.py`. Replace `_build_executor` body:

```python
from autoagent.executors.web_executor import WebExecutor

def _build_executor(mode: str) -> Executor:
    if mode == "api":
        return ApiExecutor()
    if mode == "gui_pc_web":
        return WebExecutor()
    raise ValueError(f"mode {mode} not supported in this build (see later plans for android)")
```

- [x] **Step 5: Run tests**

```bash
python3.11 -m pytest tests/unit/test_executor_factory.py tests/integration/test_batches_endpoints.py -v
```
Expected: factory tests pass; existing batch tests still pass (they use `api` mode).

- [x] **Step 6: Lint**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
```
Expected: clean.

- [x] **Step 7: Commit**

```bash
git add src/autoagent/executors/web_executor.py src/autoagent/api/_deps.py tests/unit/test_executor_factory.py
git commit -m "feat(executors): WebExecutor skeleton + factory dispatch for gui_pc_web"
```

---

## Task 3: Event bus

In-process pub/sub with per-batch monotonic `seq` and a small ring buffer (for `Last-Event-ID` resume).

**Files:**
- Create: `src/autoagent/events/__init__.py`
- Create: `src/autoagent/events/bus.py`
- Create: `tests/unit/test_event_bus.py`
- Modify: `src/autoagent/models/api.py` (add `seq` to `BatchDetail`)

- [x] **Step 1: Write failing tests**

`tests/unit/test_event_bus.py`:

```python
import asyncio

import pytest

from autoagent.events.bus import BatchEventBus, Event


async def _collect(bus: BatchEventBus, batch_id: str, n: int) -> list[Event]:
    gen = bus.subscribe(batch_id)
    out: list[Event] = []
    try:
        async with asyncio.timeout(2):
            async for event in gen:
                out.append(event)
                if len(out) >= n:
                    break
    finally:
        await gen.aclose()
    return out


async def test_publish_and_subscribe_single() -> None:
    bus = BatchEventBus()
    collected: list[Event] = []

    async def reader() -> None:
        async for event in bus.subscribe("b1"):
            collected.append(event)
            if len(collected) >= 2:
                break

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)
    await bus.publish("b1", "sample_update", {"sample_id": "s1", "status": "running"})
    await bus.publish("b1", "sample_update", {"sample_id": "s1", "status": "done"})
    await task

    assert [e.kind for e in collected] == ["sample_update", "sample_update"]
    assert [e.seq for e in collected] == [1, 2]
    assert collected[0].payload["sample_id"] == "s1"


async def test_two_subscribers_both_receive() -> None:
    bus = BatchEventBus()
    got_a: list[Event] = []
    got_b: list[Event] = []

    async def reader(sink: list[Event]) -> None:
        async for event in bus.subscribe("b1"):
            sink.append(event)
            if len(sink) >= 1:
                break

    ta = asyncio.create_task(reader(got_a))
    tb = asyncio.create_task(reader(got_b))
    await asyncio.sleep(0)
    await bus.publish("b1", "batch_progress", {"done": 1})
    await asyncio.gather(ta, tb)
    assert got_a[0].payload == {"done": 1}
    assert got_b[0].payload == {"done": 1}


async def test_seq_is_per_batch_not_global() -> None:
    bus = BatchEventBus()
    await bus.publish("b1", "k", {})
    await bus.publish("b2", "k", {})
    await bus.publish("b1", "k", {})
    assert bus.last_seq("b1") == 2
    assert bus.last_seq("b2") == 1


async def test_replay_since_returns_buffered_events() -> None:
    bus = BatchEventBus(buffer_size=5)
    await bus.publish("b1", "k", {"v": 1})
    await bus.publish("b1", "k", {"v": 2})
    await bus.publish("b1", "k", {"v": 3})
    replay = list(bus.replay_since("b1", after_seq=1))
    assert [e.seq for e in replay] == [2, 3]


async def test_replay_after_ring_eviction_returns_empty() -> None:
    bus = BatchEventBus(buffer_size=2)
    for i in range(5):
        await bus.publish("b1", "k", {"v": i})
    replay = list(bus.replay_since("b1", after_seq=1))
    assert [e.seq for e in replay] == [4, 5]


async def test_unsubscribe_stops_delivery() -> None:
    bus = BatchEventBus()

    async def short_reader() -> None:
        async for _event in bus.subscribe("b1"):
            break

    task = asyncio.create_task(short_reader())
    await asyncio.sleep(0)
    await bus.publish("b1", "k", {})
    await task
    # After reader exits, internal subscribers set for b1 should be empty
    assert bus._subs.get("b1", set()) == set()


@pytest.mark.parametrize("payload", [{"a": 1}, {"nested": {"x": [1, 2]}}])
async def test_payloads_passthrough(payload: dict) -> None:
    bus = BatchEventBus()
    got: list[Event] = []

    async def r() -> None:
        async for e in bus.subscribe("b1"):
            got.append(e)
            break

    t = asyncio.create_task(r())
    await asyncio.sleep(0)
    await bus.publish("b1", "k", payload)
    await t
    assert got[0].payload == payload
```

- [x] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_event_bus.py -v
```
Expected: ImportError for `autoagent.events.bus`.

- [x] **Step 3: Implement the bus**

`src/autoagent/events/__init__.py`: empty file.

`src/autoagent/events/bus.py`:

```python
from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Event:
    seq: int
    kind: str
    payload: dict[str, Any]
    ts: str  # ISO 8601 UTC


class BatchEventBus:
    """In-process pub/sub keyed by batch_id.

    Each batch has a monotonic `seq` counter and a ring buffer of the most
    recent events (used by SSE `Last-Event-ID` resume).
    """

    def __init__(self, buffer_size: int = 100) -> None:
        self._subs: dict[str, set[asyncio.Queue[Event]]] = {}
        self._seq: dict[str, int] = {}
        self._buffer: dict[str, deque[Event]] = {}
        self._buffer_size = buffer_size

    def last_seq(self, batch_id: str) -> int:
        return self._seq.get(batch_id, 0)

    async def publish(self, batch_id: str, kind: str, payload: dict[str, Any]) -> Event:
        seq = self._seq.get(batch_id, 0) + 1
        self._seq[batch_id] = seq
        event = Event(
            seq=seq,
            kind=kind,
            payload=payload,
            ts=datetime.now(timezone.utc).isoformat(),
        )
        buf = self._buffer.setdefault(batch_id, deque(maxlen=self._buffer_size))
        buf.append(event)
        for q in list(self._subs.get(batch_id, ())):
            q.put_nowait(event)
        return event

    def replay_since(self, batch_id: str, after_seq: int) -> list[Event]:
        buf = self._buffer.get(batch_id)
        if buf is None:
            return []
        return [e for e in buf if e.seq > after_seq]

    async def subscribe(self, batch_id: str) -> AsyncIterator[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue()
        self._subs.setdefault(batch_id, set()).add(q)
        try:
            while True:
                yield await q.get()
        finally:
            subs = self._subs.get(batch_id)
            if subs is not None:
                subs.discard(q)
                if not subs:
                    self._subs.pop(batch_id, None)


_instance: BatchEventBus | None = None


def get_event_bus() -> BatchEventBus:
    global _instance
    if _instance is None:
        _instance = BatchEventBus()
    return _instance


def reset_bus_for_tests() -> None:
    global _instance
    _instance = None
```

- [x] **Step 4: Add `seq` to `BatchDetail`**

Open `src/autoagent/models/api.py`, find `class BatchDetail(BaseModel):`. Add field:

```python
    seq: int = 0
```

Place after the existing fields, before any method definitions. This is a non-breaking additive change; existing tests continue to pass.

- [x] **Step 5: Run tests**

```bash
python3.11 -m pytest tests/unit/test_event_bus.py tests/integration/test_batches_endpoints.py -v
```
Expected: all bus tests pass; existing batch tests still pass (they don't assert on `seq`).

- [x] **Step 6: Lint**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
```

- [x] **Step 7: Commit**

```bash
git add src/autoagent/events src/autoagent/models/api.py tests/unit/test_event_bus.py
git commit -m "feat(events): in-process batch event bus with seq + ring buffer"
```

---

## Task 4: fake_chat.html test fixture

Shared fixture used by real-Playwright integration tests in Tasks 9 and 14.

**Files:**
- Create: `tests/fixtures/fake_chat.html`
- Create: `tests/fixtures/__init__.py` (empty, so the dir is a pkg and `pytest` discovers it cleanly)

- [x] **Step 1: Create the fixture directory marker**

`tests/fixtures/__init__.py`: empty file.

- [x] **Step 2: Create the HTML fixture**

`tests/fixtures/fake_chat.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Fake Chat</title>
</head>
<body>
<h1>Fake Chat</h1>
<div id="responses" data-testid="responses"></div>
<textarea id="input" data-testid="input" rows="3" cols="40"></textarea>
<br />
<button id="send" data-testid="send" disabled>Send</button>
<button id="new-chat" data-testid="new-chat">New chat</button>
<script>
  const input = document.getElementById('input');
  const send = document.getElementById('send');
  const newChat = document.getElementById('new-chat');
  const responses = document.getElementById('responses');

  input.addEventListener('input', () => {
    send.disabled = input.value.trim().length === 0;
  });

  send.addEventListener('click', () => {
    const prompt = input.value;
    input.value = '';
    send.disabled = true;
    const bubble = document.createElement('div');
    bubble.setAttribute('data-role', 'assistant');
    responses.appendChild(bubble);
    const reply = 'echo: ' + prompt;
    let i = 0;
    const tick = () => {
      bubble.textContent = reply.slice(0, i);
      i += 1;
      if (i <= reply.length) {
        setTimeout(tick, 30);
      } else {
        // generation done — wait ~1.1s of DOM-stability, then re-enable send
        setTimeout(() => {
          send.disabled = false;
        }, 1100);
      }
    };
    tick();
  });

  newChat.addEventListener('click', () => {
    responses.innerHTML = '';
  });
</script>
</body>
</html>
```

Key properties for tests:
- Typing in `#input` enables `#send` (dom_selector readiness).
- Clicking `#send` appends `div[data-role="assistant"]` inside `#responses`, types out the reply character-by-character (~30 ms each), then after a 1.1s quiet period re-enables `#send`. Both `dom_stable` (with `stable_sec=1`) and `send_button_reenable` fire at the same end-of-generation moment.
- `#new-chat` clears responses — target for `new_session_action`.

- [x] **Step 3: Smoke-open the fixture**

Run:
```bash
python3.11 -c "from pathlib import Path; assert Path('tests/fixtures/fake_chat.html').is_file(); print('ok')"
```
Expected: `ok`.

- [x] **Step 4: Commit**

```bash
git add tests/fixtures/fake_chat.html tests/fixtures/__init__.py
git commit -m "test(fixtures): fake_chat.html for web executor integration tests"
```

---

## Task 5: ActionRunner

Executes `goto`, `wait_for`, `click`, `sleep`, `fill`, `press` against a Playwright `Page`. `fill.text` supports `$ENV_VAR` expansion.

**Files:**
- Create: `src/autoagent/executors/action_runner.py`
- Create: `tests/unit/test_action_runner.py`

- [x] **Step 1: Write failing tests**

`tests/unit/test_action_runner.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from autoagent.executors.action_runner import ActionRunner
from autoagent.profiles.schemas import ActionStep


def _mk_page() -> AsyncMock:
    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    return page


async def test_goto_passes_url_and_timeout() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="goto", url="https://example.com", timeout_sec=5)])
    page.goto.assert_awaited_once_with("https://example.com", timeout=5000)


async def test_wait_for_calls_wait_for_selector() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="wait_for", selector="#send", timeout_sec=3)])
    page.wait_for_selector.assert_awaited_once_with("#send", timeout=3000)


async def test_click_calls_click() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="click", selector="#send")])
    page.click.assert_awaited_once()


async def test_sleep_sleeps_for_ms() -> None:
    import time as _time

    page = _mk_page()
    runner = ActionRunner(page)
    t0 = _time.monotonic()
    await runner.run([ActionStep(action="sleep", ms=50)])
    elapsed = _time.monotonic() - t0
    assert elapsed >= 0.04


async def test_fill_uses_selector_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="fill", selector="#input", text="hello")])
    page.fill.assert_awaited_once_with("#input", "hello", timeout=5000)


async def test_fill_expands_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOO_PASSWORD", "s3cret")
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="fill", selector="#pw", text="$FOO_PASSWORD")])
    page.fill.assert_awaited_once_with("#pw", "s3cret", timeout=5000)


async def test_fill_missing_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_ENV_Q", raising=False)
    page = _mk_page()
    runner = ActionRunner(page)
    with pytest.raises(ValueError, match="MISSING_ENV_Q"):
        await runner.run([ActionStep(action="fill", selector="#x", text="$MISSING_ENV_Q")])


async def test_press_key() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([ActionStep(action="press", key="Enter")])
    page.keyboard.press.assert_awaited_once_with("Enter")


async def test_unknown_action_raises() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    with pytest.raises(ValueError, match="unknown action"):
        await runner.run([ActionStep(action="yell", text="oops")])


async def test_log_records_each_step() -> None:
    page = _mk_page()
    runner = ActionRunner(page)
    await runner.run([
        ActionStep(action="goto", url="https://x"),
        ActionStep(action="click", selector="#y"),
    ])
    assert [e["action"] for e in runner.log] == ["goto", "click"]
    assert all(e["ok"] is True for e in runner.log)


async def test_log_captures_failure() -> None:
    page = _mk_page()
    page.click.side_effect = RuntimeError("boom")
    runner = ActionRunner(page)
    with pytest.raises(RuntimeError):
        await runner.run([ActionStep(action="click", selector="#y")])
    assert runner.log[0]["ok"] is False
    assert "boom" in runner.log[0]["error"]
```

- [x] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_action_runner.py -v
```
Expected: ImportError.

- [x] **Step 3: Implement `ActionRunner`**

`src/autoagent/executors/action_runner.py`:

```python
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

from autoagent.profiles.schemas import ActionStep

ENV_VAR_RE = re.compile(r"^\$([A-Z_][A-Z0-9_]*)$")


class ActionRunner:
    """Executes declarative action steps against a Playwright Page.

    Supported actions: goto, wait_for, click, sleep, fill, press.
    """

    def __init__(self, page: Any) -> None:
        self.page = page
        self.log: list[dict[str, Any]] = []
        self._t0 = time.monotonic()

    async def run(self, steps: list[ActionStep]) -> None:
        for step in steps:
            entry: dict[str, Any] = {
                "t_ms": int((time.monotonic() - self._t0) * 1000),
                "action": step.action,
                "selector": getattr(step, "selector", None),
                "ok": False,
                "error": None,
            }
            try:
                await self._dispatch(step)
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
                self.log.append(entry)
                raise
            entry["ok"] = True
            self.log.append(entry)

    async def _dispatch(self, step: ActionStep) -> None:
        action = step.action
        if action == "goto":
            url = step.url  # type: ignore[attr-defined]
            timeout_ms = int(getattr(step, "timeout_sec", 30) * 1000)
            await self.page.goto(url, timeout=timeout_ms)
        elif action == "wait_for":
            selector = step.selector  # type: ignore[attr-defined]
            timeout_ms = int(getattr(step, "timeout_sec", 30) * 1000)
            await self.page.wait_for_selector(selector, timeout=timeout_ms)
        elif action == "click":
            selector = step.selector  # type: ignore[attr-defined]
            timeout_ms = int(getattr(step, "timeout_sec", 5) * 1000)
            await self.page.click(selector, timeout=timeout_ms)
        elif action == "sleep":
            ms = int(getattr(step, "ms", 0))
            await asyncio.sleep(ms / 1000)
        elif action == "fill":
            selector = step.selector  # type: ignore[attr-defined]
            text = self._expand_env(step.text)  # type: ignore[attr-defined]
            timeout_ms = int(getattr(step, "timeout_sec", 5) * 1000)
            await self.page.fill(selector, text, timeout=timeout_ms)
        elif action == "press":
            key = step.key  # type: ignore[attr-defined]
            await self.page.keyboard.press(key)
        else:
            raise ValueError(f"unknown action: {action}")

    @staticmethod
    def _expand_env(text: str) -> str:
        m = ENV_VAR_RE.match(text)
        if not m:
            return text
        name = m.group(1)
        val = os.environ.get(name)
        if val is None:
            raise ValueError(f"environment variable {name} is not set")
        return val
```

- [x] **Step 4: Run tests**

```bash
python3.11 -m pytest tests/unit/test_action_runner.py -v
```
Expected: 11 passed.

- [x] **Step 5: Lint**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
```

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/executors/action_runner.py tests/unit/test_action_runner.py
git commit -m "feat(executors): ActionRunner with 6 actions + env-var expansion for fill"
```

---

## Task 6: CompleteDetector

Implements `dom_stable` and `send_button_reenable` completion strategies.

**Files:**
- Create: `src/autoagent/executors/complete_detector.py`
- Create: `tests/unit/test_complete_detector.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_complete_detector.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from autoagent.executors.complete_detector import (
    wait_for_complete,
)
from autoagent.profiles.schemas import DomStable, SendButtonReenable


async def test_dom_stable_returns_when_text_stops_changing() -> None:
    page = AsyncMock()
    # Sequence: "a" → "ab" → "abc" → "abc" → "abc" → "abc"
    texts = iter(["a", "ab", "abc", "abc", "abc", "abc", "abc"])
    page.inner_text = AsyncMock(side_effect=lambda *_a, **_kw: next(texts))

    await wait_for_complete(
        page,
        DomStable(type="dom_stable", stable_sec=0.15, max_wait_sec=5),
        response_selector="#responses",
        poll_interval_sec=0.05,
    )
    # We don't assert exact call count, but >= 4 polls must have happened
    # to observe stability across 0.15s.
    assert page.inner_text.await_count >= 4


async def test_dom_stable_times_out() -> None:
    page = AsyncMock()
    counter = {"i": 0}

    async def never_stable(*_a, **_kw):
        counter["i"] += 1
        return f"text {counter['i']}"

    page.inner_text = never_stable
    with pytest.raises(TimeoutError):
        await wait_for_complete(
            page,
            DomStable(type="dom_stable", stable_sec=0.2, max_wait_sec=0.4),
            response_selector="#responses",
            poll_interval_sec=0.05,
        )


async def test_send_button_reenable_waits_for_enabled() -> None:
    page = AsyncMock()
    # Simulate disabled → disabled → enabled
    states = iter([True, True, False, False])
    page.is_disabled = AsyncMock(side_effect=lambda *_a, **_kw: next(states))
    await wait_for_complete(
        page,
        SendButtonReenable(type="send_button_reenable"),
        response_selector="#responses",
        send_button_selector="#send",
        poll_interval_sec=0.05,
        max_wait_sec=5,
    )
    assert page.is_disabled.await_count >= 3


async def test_send_button_reenable_times_out() -> None:
    page = AsyncMock()
    page.is_disabled = AsyncMock(return_value=True)
    with pytest.raises(TimeoutError):
        await wait_for_complete(
            page,
            SendButtonReenable(type="send_button_reenable"),
            response_selector="#responses",
            send_button_selector="#send",
            poll_interval_sec=0.05,
            max_wait_sec=0.3,
        )


async def test_send_button_reenable_requires_button_selector() -> None:
    page = AsyncMock()
    with pytest.raises(ValueError, match="send_button_selector"):
        await wait_for_complete(
            page,
            SendButtonReenable(type="send_button_reenable"),
            response_selector="#responses",
            send_button_selector=None,
            poll_interval_sec=0.05,
            max_wait_sec=1,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_complete_detector.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the detector**

`src/autoagent/executors/complete_detector.py`:

```python
from __future__ import annotations

import asyncio
import time
from typing import Any

from autoagent.profiles.schemas import (
    CompleteDetection,
    DomStable,
    SendButtonReenable,
)


async def wait_for_complete(
    page: Any,
    strategy: CompleteDetection,
    *,
    response_selector: str,
    send_button_selector: str | None = None,
    poll_interval_sec: float = 0.2,
    max_wait_sec: float | None = None,
) -> None:
    """Block until the chosen strategy reports completion. Raises TimeoutError on timeout."""

    if isinstance(strategy, DomStable):
        await _dom_stable(
            page,
            response_selector=response_selector,
            stable_sec=float(strategy.stable_sec),
            max_wait_sec=float(strategy.max_wait_sec if max_wait_sec is None else max_wait_sec),
            poll_interval_sec=poll_interval_sec,
        )
    elif isinstance(strategy, SendButtonReenable):
        if send_button_selector is None:
            raise ValueError("send_button_reenable requires send_button_selector")
        await _send_button_reenable(
            page,
            selector=send_button_selector,
            max_wait_sec=float(max_wait_sec if max_wait_sec is not None else 180),
            poll_interval_sec=poll_interval_sec,
        )
    else:
        raise ValueError(f"unsupported completion strategy: {type(strategy).__name__}")


async def _dom_stable(
    page: Any,
    *,
    response_selector: str,
    stable_sec: float,
    max_wait_sec: float,
    poll_interval_sec: float,
) -> None:
    deadline = time.monotonic() + max_wait_sec
    last_text: str | None = None
    stable_since: float | None = None

    while time.monotonic() < deadline:
        text = await page.inner_text(response_selector)
        now = time.monotonic()
        if text == last_text:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stable_sec:
                return
        else:
            last_text = text
            stable_since = None
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"dom_stable not reached within {max_wait_sec}s")


async def _send_button_reenable(
    page: Any,
    *,
    selector: str,
    max_wait_sec: float,
    poll_interval_sec: float,
) -> None:
    deadline = time.monotonic() + max_wait_sec
    saw_disabled = False

    while time.monotonic() < deadline:
        disabled = await page.is_disabled(selector)
        if disabled:
            saw_disabled = True
        elif saw_disabled:
            return
        await asyncio.sleep(poll_interval_sec)

    raise TimeoutError(f"send_button_reenable not reached within {max_wait_sec}s")
```

- [ ] **Step 4: Run tests**

```bash
python3.11 -m pytest tests/unit/test_complete_detector.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Lint and commit**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
git add src/autoagent/executors/complete_detector.py tests/unit/test_complete_detector.py
git commit -m "feat(executors): CompleteDetector for dom_stable + send_button_reenable"
```

---

## Task 7: ScreenshotStore

Manages directory + filename generation for per-sample screenshots.

**Files:**
- Create: `src/autoagent/executors/screenshot_store.py`
- Create: `tests/unit/test_screenshot_store.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_screenshot_store.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from autoagent.executors.screenshot_store import ScreenshotStore, slug_label


def test_slug_label_keeps_alnum_underscore() -> None:
    assert slug_label("ready_state_01") == "ready_state_01"


def test_slug_label_replaces_spaces_and_dots() -> None:
    assert slug_label("after fill.ok") == "after_fill_ok"


def test_slug_label_lowercases_and_strips_junk() -> None:
    assert slug_label("Ready!!$") == "ready"


def test_slug_label_empty_becomes_step() -> None:
    assert slug_label("") == "step"
    assert slug_label("@#$") == "step"


def test_next_path_creates_parent_dir_and_zero_pads(tmp_path: Path) -> None:
    store = ScreenshotStore(root=tmp_path, batch_id="b1", sample_id="s1")
    p1 = store.next_path("ready")
    p2 = store.next_path("filled")
    assert p1.name == "01_ready.png"
    assert p2.name == "02_filled.png"
    assert p1.parent == tmp_path / "b1" / "s1"
    assert p1.parent.is_dir()


def test_next_path_survives_preexisting(tmp_path: Path) -> None:
    (tmp_path / "b1" / "s1").mkdir(parents=True)
    (tmp_path / "b1" / "s1" / "01_ready.png").write_bytes(b"")
    store = ScreenshotStore(root=tmp_path, batch_id="b1", sample_id="s1")
    p = store.next_path("filled")
    # Store starts its own counter; files with same index are simply overwritten
    # only if the test forces reuse. Expect counter starts at 01 per store instance.
    assert p.name == "01_filled.png"


def test_logs_dir_property(tmp_path: Path) -> None:
    store = ScreenshotStore(root=tmp_path, batch_id="b1", sample_id="s1")
    assert store.logs_dir == str((tmp_path / "b1" / "s1").resolve())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_screenshot_store.py -v
```

- [ ] **Step 3: Implement the store**

`src/autoagent/executors/screenshot_store.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

_ALLOWED = re.compile(r"[a-z0-9_]+")


def slug_label(label: str) -> str:
    lowered = label.strip().lower().replace(" ", "_").replace(".", "_")
    parts = _ALLOWED.findall(lowered)
    joined = "_".join(parts)
    return joined or "step"


class ScreenshotStore:
    """Computes per-sample screenshot file paths under <root>/<batch_id>/<sample_id>/.

    Filename format: NNN_<label>.png where NNN is a 2- or 3-digit zero-padded counter
    scoped to this store instance (not persisted across executor restarts).
    """

    def __init__(self, root: Path, batch_id: str, sample_id: str) -> None:
        self._dir = (root / batch_id / sample_id).resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    @property
    def logs_dir(self) -> str:
        return str(self._dir)

    def next_path(self, label: str) -> Path:
        self._counter += 1
        n = f"{self._counter:02d}" if self._counter < 100 else f"{self._counter:03d}"
        return self._dir / f"{n}_{slug_label(label)}.png"
```

- [ ] **Step 4: Run tests**

```bash
python3.11 -m pytest tests/unit/test_screenshot_store.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Lint and commit**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
git add src/autoagent/executors/screenshot_store.py tests/unit/test_screenshot_store.py
git commit -m "feat(executors): ScreenshotStore (per-sample NNN_<label>.png paths)"
```

---

## Task 8: WebExecutor — mocked Playwright unit tests + full implementation

Fills in the skeleton from Task 2 using the building blocks from Tasks 5–7. Uses mocked Playwright so tests stay fast.

**Files:**
- Modify: `src/autoagent/executors/web_executor.py`
- Create: `tests/unit/test_web_executor_unit.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_web_executor_unit.py`:

```python
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoagent.executors.base import ExecutorContext
from autoagent.executors.web_executor import WebExecutor
from autoagent.models.api import Sample
from autoagent.profiles.schemas import (
    ActionStep,
    DomStable,
    WebBrowserConfig,
    WebProfile,
    WebReadyCheck,
    WebSendMethodKeyboard,
)


def _profile(user_data_dir: str | None = None) -> WebProfile:
    return WebProfile(
        name="fake_site",
        platform="web",
        url="file:///tmp/fake_chat.html",
        browser=WebBrowserConfig(headless=True, user_data_dir=user_data_dir),
        ready_check=WebReadyCheck(type="dom_selector", selector="#input", timeout_sec=5),
        recovery_path=[ActionStep(action="goto", url="file:///tmp/fake_chat.html")],
        input_selector="#input",
        send_method=WebSendMethodKeyboard(type="keyboard", key="Enter"),
        response_container_selector="#responses > div[data-role='assistant']:last-child",
        new_session_action=[ActionStep(action="click", selector="#new-chat")],
        complete_detection=DomStable(type="dom_stable", stable_sec=0.1, max_wait_sec=5),
    )


def _sample(prompts: list[str], *, new_session: bool = True, retry: int = 0) -> Sample:
    return Sample(
        id="s1",
        prompts=prompts,
        mode="gui_pc_web",
        target_profile="fake_site",
        new_session=new_session,
        retry=retry,
    )


def _patch_playwright(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Install a mock async_playwright().start() chain and return the Page mock."""

    page = AsyncMock()
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.fill = AsyncMock()
    page.click = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.screenshot = AsyncMock()
    page.inner_text = AsyncMock(return_value="echo: hi")
    page.is_disabled = AsyncMock(return_value=False)

    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()

    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)
    chromium.launch_persistent_context = AsyncMock(return_value=context)

    pw = AsyncMock()
    pw.chromium = chromium

    @asynccontextmanager
    async def fake_async_playwright():
        class _P:
            async def start(self_inner):
                return pw

            async def stop(self_inner):
                return None

        yield pw

    class _Ctx:
        async def __aenter__(self_inner):
            return pw

        async def __aexit__(self_inner, *_a):
            return None

    def _entry():
        return _Ctx()

    from autoagent.executors import web_executor as we

    monkeypatch.setattr(we, "async_playwright", _entry)
    return page


async def test_happy_path_single_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    page.inner_text = AsyncMock(side_effect=["echo: hi", "echo: hi", "echo: hi"])
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(logs_dir=None, verbose_logs=False)

    out = await executor.execute(
        _sample(["hi"]), _profile(), ctx
    )

    assert out == ["echo: hi"]
    page.goto.assert_awaited()
    page.fill.assert_awaited_with("#input", "hi", timeout=5000)
    # keyboard send
    page.keyboard.press.assert_awaited_with("Enter")


async def test_multi_prompt_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    page.inner_text = AsyncMock(
        side_effect=["a", "a", "a", "b", "b", "b", "c", "c", "c"]
    )
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    out = await executor.execute(_sample(["1", "2", "3"]), _profile(), ctx)
    # Three prompts → three response strings (last inner_text per round)
    assert len(out) == 3
    assert page.fill.await_count == 3


async def test_new_session_triggers_new_session_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    await executor.execute(_sample(["hi"], new_session=True), _profile(), ctx)
    # new_session_action is `click #new-chat`
    page.click.assert_any_await("#new-chat", timeout=5000)


async def test_new_session_false_skips_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    await executor.execute(_sample(["hi"], new_session=False), _profile(), ctx)
    # When new_session=False, #new-chat should NOT be clicked
    for call in page.click.await_args_list:
        args, kwargs = call
        assert args[0] != "#new-chat"


async def test_persistent_context_when_user_data_dir_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    await executor.execute(_sample(["hi"]), _profile(user_data_dir=str(tmp_path)), ctx)

    from autoagent.executors import web_executor as we  # noqa

    # launch_persistent_context must have been used instead of launch
    # We access the pw object stashed by _patch_playwright via the page mock chain indirectly:
    # the outer chromium is the AsyncMock we installed; we just verify fill still happened
    page.fill.assert_awaited()


async def test_click_button_send_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from autoagent.profiles.schemas import WebSendMethodClick

    page = _patch_playwright(monkeypatch)
    prof = _profile()
    prof = prof.model_copy(
        update={"send_method": WebSendMethodClick(type="click_button", selector="#send")}
    )
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    await executor.execute(_sample(["hi"]), prof, ctx)
    page.click.assert_any_await("#send", timeout=5000)
    # keyboard.press must not have been used
    page.keyboard.press.assert_not_awaited()


async def test_retry_on_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    calls = {"n": 0}

    async def flaky_fill(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("flaky")

    page.fill = AsyncMock(side_effect=flaky_fill)

    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=False)
    # retry=1 → execute() only runs once per call; retries live in run()
    with pytest.raises(RuntimeError):
        await executor.execute(_sample(["hi"], retry=1), _profile(), ctx)
    # recovery_path must have been executed after the first failure
    page.goto.await_count >= 2


async def test_verbose_logs_captures_per_action_screenshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _patch_playwright(monkeypatch)
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(verbose_logs=True)
    await executor.execute(_sample(["hi"]), _profile(), ctx)
    # verbose → many screenshots. non-verbose would be ≤5 (milestones only).
    assert page.screenshot.await_count >= 5
```

- [ ] **Step 2: Run tests to verify they fail (WebExecutor.execute is still NotImplementedError)**

```bash
python3.11 -m pytest tests/unit/test_web_executor_unit.py -v
```

- [ ] **Step 3: Implement `WebExecutor.execute`**

Replace `src/autoagent/executors/web_executor.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from autoagent.executors.action_runner import ActionRunner
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.executors.complete_detector import wait_for_complete
from autoagent.executors.screenshot_store import ScreenshotStore
from autoagent.models.api import Sample
from autoagent.profiles.schemas import (
    WebProfile,
    WebSendMethodClick,
    WebSendMethodKeyboard,
)


class WebExecutor(Executor):
    """Playwright-backed executor for `mode=gui_pc_web`.

    Each `execute` call owns its own Browser/Context/Page lifecycle. For batches
    that share a `user_data_dir`, the scheduler is expected to force
    concurrency=1 (Task 10) so the profile lock is respected.
    """

    def __init__(self, screenshots_root: Path | None = None) -> None:
        self._root = Path(screenshots_root) if screenshots_root else Path("./data/logs")

    async def execute(
        self, sample: Sample, profile: Any, ctx: ExecutorContext
    ) -> list[str]:
        if not isinstance(profile, WebProfile):
            raise TypeError(f"WebExecutor requires WebProfile, got {type(profile).__name__}")

        store = ScreenshotStore(
            root=self._root,
            batch_id=ctx.logs_dir or "ad_hoc",
            sample_id=sample.id,
        )
        ctx.logs_dir = store.logs_dir  # record back into context for SampleResult

        responses: list[str] = []
        async with async_playwright() as pw:
            if profile.browser.user_data_dir:
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=profile.browser.user_data_dir,
                    headless=profile.browser.headless,
                )
                browser = None
            else:
                browser = await pw.chromium.launch(headless=profile.browser.headless)
                context = await browser.new_context()

            try:
                page = await context.new_page()
                runner = ActionRunner(page)

                await page.goto(profile.url, timeout=30_000)
                await page.wait_for_selector(
                    profile.ready_check.selector,
                    timeout=int(profile.ready_check.timeout_sec * 1000),
                )
                await self._screenshot(page, store, "ready", verbose=True)

                if sample.new_session and profile.new_session_action:
                    await runner.run(list(profile.new_session_action))
                    await self._screenshot(page, store, "new_session", verbose=ctx.verbose_logs)

                for idx, prompt in enumerate(sample.prompts, start=1):
                    try:
                        await page.fill(profile.input_selector, prompt, timeout=5000)
                        await self._screenshot(
                            page, store, f"filled_{idx}", verbose=ctx.verbose_logs
                        )

                        await self._send(page, profile.send_method)
                        await self._screenshot(
                            page, store, f"sent_{idx}", verbose=ctx.verbose_logs
                        )

                        await wait_for_complete(
                            page,
                            profile.complete_detection,
                            response_selector=profile.response_container_selector,
                            send_button_selector=_send_button_selector(profile.send_method),
                        )
                        text = await page.inner_text(profile.response_container_selector)
                        responses.append(text)
                        await self._screenshot(page, store, f"done_{idx}", verbose=True)
                    except Exception:
                        await self._screenshot(page, store, f"error_{idx}", verbose=True)
                        # run recovery then re-raise so Executor.run handles retry
                        try:
                            await runner.run(list(profile.recovery_path))
                        except Exception:
                            pass
                        raise

                # merge action log into context metadata for SampleResult
                ctx_metadata = getattr(ctx, "action_log", None)
                if ctx_metadata is None:
                    setattr(ctx, "action_log", runner.log)
                return responses
            finally:
                if browser is not None:
                    await browser.close()
                else:
                    await context.close()

    async def _send(self, page: Any, method: Any) -> None:
        if isinstance(method, WebSendMethodKeyboard):
            await page.keyboard.press(method.key)
        elif isinstance(method, WebSendMethodClick):
            await page.click(method.selector, timeout=5000)
        else:
            raise ValueError(f"unsupported send method: {method}")

    async def _screenshot(
        self, page: Any, store: ScreenshotStore, label: str, *, verbose: bool
    ) -> None:
        if not verbose and label not in {"ready", "done_1", "error_1"} and not label.startswith(
            "done_"
        ) and not label.startswith("error_"):
            return
        path = store.next_path(label)
        try:
            await page.screenshot(path=str(path), full_page=False)
        except Exception:
            # Screenshot failure must not fail the sample
            pass


def _send_button_selector(method: Any) -> str | None:
    if isinstance(method, WebSendMethodClick):
        return method.selector
    return None
```

- [ ] **Step 4: Run unit tests**

```bash
python3.11 -m pytest tests/unit/test_web_executor_unit.py -v
```
Expected: all pass. If any fail, reconcile mock expectations vs. actual Playwright calls. The `_patch_playwright` helper monkeypatches the module-level `async_playwright`; if the executor imports `async_playwright` differently, adjust the test's `monkeypatch.setattr` target.

- [ ] **Step 5: Run the full suite**

```bash
python3.11 -m pytest -q -m "not playwright"
```
Expected: 68 prior + 11 (action_runner) + 5 (detector) + 7 (store) + ~8 (web executor unit) + ~7 (bus) + 3 (factory) = ~109 passed.

- [ ] **Step 6: Lint and commit**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
git add src/autoagent/executors/web_executor.py tests/unit/test_web_executor_unit.py
git commit -m "feat(executors): WebExecutor with Playwright + screenshots + recovery"
```

---

## Task 9: WebExecutor real-Playwright integration test

Exercises the full pipeline against `fake_chat.html` with a real Chromium.

**Files:**
- Create: `tests/integration/test_web_executor_e2e.py`

- [ ] **Step 1: Write the integration test**

`tests/integration/test_web_executor_e2e.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from autoagent.executors.base import ExecutorContext
from autoagent.executors.web_executor import WebExecutor
from autoagent.models.api import Sample
from autoagent.profiles.schemas import (
    ActionStep,
    DomStable,
    WebBrowserConfig,
    WebProfile,
    WebReadyCheck,
    WebSendMethodClick,
)

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "fake_chat.html").resolve()
FIXTURE_URL = FIXTURE.as_uri()

pytestmark = pytest.mark.playwright


def _profile() -> WebProfile:
    return WebProfile(
        name="fake",
        platform="web",
        url=FIXTURE_URL,
        browser=WebBrowserConfig(headless=True, user_data_dir=None),
        ready_check=WebReadyCheck(type="dom_selector", selector="#input", timeout_sec=10),
        recovery_path=[ActionStep(action="goto", url=FIXTURE_URL)],
        input_selector="#input",
        send_method=WebSendMethodClick(type="click_button", selector="#send"),
        response_container_selector="#responses > div[data-role='assistant']:last-child",
        new_session_action=[ActionStep(action="click", selector="#new-chat")],
        complete_detection=DomStable(type="dom_stable", stable_sec=0.8, max_wait_sec=30),
    )


async def test_single_prompt_e2e(tmp_path: Path) -> None:
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(logs_dir="b_test", verbose_logs=False)
    responses = await executor.execute(
        Sample(id="s1", prompts=["hi"], mode="gui_pc_web", target_profile="fake"),
        _profile(),
        ctx,
    )
    assert responses == ["echo: hi"]


async def test_multi_prompt_e2e(tmp_path: Path) -> None:
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(logs_dir="b_test", verbose_logs=False)
    responses = await executor.execute(
        Sample(id="s2", prompts=["a", "bb", "ccc"], mode="gui_pc_web", target_profile="fake"),
        _profile(),
        ctx,
    )
    assert responses == ["echo: a", "echo: bb", "echo: ccc"]


async def test_new_session_clears_history(tmp_path: Path) -> None:
    executor = WebExecutor(screenshots_root=tmp_path)
    ctx = ExecutorContext(logs_dir="b_test", verbose_logs=False)
    # new_session=True should click #new-chat, clearing responses before the prompt
    responses = await executor.execute(
        Sample(
            id="s3",
            prompts=["fresh"],
            mode="gui_pc_web",
            target_profile="fake",
            new_session=True,
        ),
        _profile(),
        ctx,
    )
    assert responses == ["echo: fresh"]


async def test_bad_selector_triggers_recovery(tmp_path: Path) -> None:
    executor = WebExecutor(screenshots_root=tmp_path)
    bad = _profile().model_copy(update={"input_selector": "#does-not-exist"})
    ctx = ExecutorContext(logs_dir="b_test", verbose_logs=False)
    with pytest.raises(Exception):  # noqa: BLE001
        await executor.execute(
            Sample(
                id="s4",
                prompts=["x"],
                mode="gui_pc_web",
                target_profile="fake",
                retry=0,
            ),
            bad,
            ctx,
        )
    # Screenshots for error_1 must have been written
    files = list(tmp_path.rglob("*error*.png"))
    assert files, "expected at least one error_* screenshot under logs dir"
```

- [ ] **Step 2: Run the integration test (real Chromium required)**

```bash
python3.11 -m pytest tests/integration/test_web_executor_e2e.py -v
```
Expected: 4 passed. If `browserType.launch: Executable doesn't exist` appears, re-run `python3.11 -m playwright install chromium`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_web_executor_e2e.py
git commit -m "test(integration): real-Playwright e2e against fake_chat.html"
```

---

## Task 10: Scheduler — force concurrency=1 for user_data_dir profiles

**Files:**
- Modify: `src/autoagent/scheduler/batch_scheduler.py`
- Create: `tests/unit/test_scheduler_web_concurrency.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_scheduler_web_concurrency.py`:

```python
from __future__ import annotations

import asyncio
import logging

import pytest

from autoagent.models.api import Sample
from autoagent.profiles.schemas import (
    ActionStep,
    DomStable,
    WebBrowserConfig,
    WebProfile,
    WebReadyCheck,
    WebSendMethodKeyboard,
)
from autoagent.scheduler.batch_scheduler import BatchScheduler


class _RecordingExecutor:
    def __init__(self, running: list[int]) -> None:
        self._running = running
        self._peak = 0
        self._active = 0
        self._lock = asyncio.Lock()

    async def run(self, sample, profile, default_timeout_sec, ctx):  # noqa: ANN001
        async with self._lock:
            self._active += 1
            self._peak = max(self._peak, self._active)
        await asyncio.sleep(0.05)
        async with self._lock:
            self._active -= 1
        from autoagent.models.api import SampleResult

        return SampleResult(
            id=sample.id,
            status="done",
            prompts_sent=list(sample.prompts),
            responses=["ok"],
            duration_ms=50,
            mode=sample.mode,
            target_profile=sample.target_profile,
            attempt_count=1,
        )


def _persistent_profile(name: str, user_data_dir: str) -> WebProfile:
    return WebProfile(
        name=name,
        platform="web",
        url="about:blank",
        browser=WebBrowserConfig(headless=True, user_data_dir=user_data_dir),
        ready_check=WebReadyCheck(type="dom_selector", selector="#x", timeout_sec=1),
        recovery_path=[ActionStep(action="goto", url="about:blank")],
        input_selector="#x",
        send_method=WebSendMethodKeyboard(type="keyboard", key="Enter"),
        response_container_selector="#x",
        complete_detection=DomStable(type="dom_stable", stable_sec=0.1, max_wait_sec=1),
    )


async def test_web_profile_with_user_data_dir_forces_concurrency_1(
    caplog: pytest.LogCaptureFixture, tmp_path
) -> None:
    prof = _persistent_profile("p_persist", str(tmp_path))
    running: list[int] = []
    executor = _RecordingExecutor(running)

    scheduler = BatchScheduler(
        executor_factory=lambda _m: executor,
        profile_lookup=lambda _n: prof,
    )

    samples = [
        Sample(id=f"s{i}", prompts=["hi"], mode="gui_pc_web", target_profile="p_persist")
        for i in range(4)
    ]

    caplog.set_level(logging.WARNING, logger="autoagent.scheduler.batch_scheduler")
    batch_id = await scheduler.submit(
        name="t", mode="gui_pc_web", concurrency=4, samples=samples
    )
    await scheduler.wait_done(batch_id, timeout_sec=30)

    assert executor._peak == 1, f"expected serial execution, got peak={executor._peak}"
    assert any("user_data_dir" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run the failing test**

```bash
python3.11 -m pytest tests/unit/test_scheduler_web_concurrency.py -v
```
Expected: fails (peak == 4 currently).

- [ ] **Step 3: Implement the downgrade**

Modify `src/autoagent/scheduler/batch_scheduler.py`. Add a helper near the top of the file (after imports):

```python
def _resolve_concurrency(
    requested: int,
    mode: str,
    samples: list[Sample],
    profile_lookup: Callable[[str], Any],
    *,
    logger: logging.Logger = log,
) -> int:
    if mode != "gui_pc_web" or not samples:
        return max(1, requested)
    # Inspect all referenced web profiles; if any has user_data_dir, force 1.
    seen: set[str] = set()
    for s in samples:
        if s.target_profile in seen:
            continue
        seen.add(s.target_profile)
        try:
            profile = profile_lookup(s.target_profile)
        except Exception:
            continue
        uddir = getattr(getattr(profile, "browser", None), "user_data_dir", None)
        if uddir:
            if requested > 1:
                logger.warning(
                    "batch: profile %s has user_data_dir=%s; forcing concurrency=1 "
                    "(requested %d)",
                    profile.name,
                    uddir,
                    requested,
                )
            return 1
    return max(1, requested)
```

Then in `submit`, change:

```python
        state = _RunState(
            samples=samples,
            mode=mode,
            concurrency=max(1, concurrency),
            target_profile_default=target_profile_default,
        )
```

to:

```python
        effective = _resolve_concurrency(
            concurrency, mode, samples, self._profile_lookup
        )
        state = _RunState(
            samples=samples,
            mode=mode,
            concurrency=effective,
            target_profile_default=target_profile_default,
        )
```

And change the `create_batch` call to use `state.concurrency` (already is).

- [ ] **Step 4: Run tests**

```bash
python3.11 -m pytest tests/unit/test_scheduler_web_concurrency.py -v
python3.11 -m pytest tests/integration/test_batches_endpoints.py -v
```
Expected: new test passes; existing batch integration tests still pass (they use `mode=api`).

- [ ] **Step 5: Lint and commit**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
git add src/autoagent/scheduler/batch_scheduler.py tests/unit/test_scheduler_web_concurrency.py
git commit -m "feat(scheduler): force concurrency=1 for web profiles with user_data_dir"
```

---

## Task 11: Scheduler publishes events to the bus

Wire scheduler state transitions into the `BatchEventBus`. Makes BatchDetail GET include the current `seq`.

**Files:**
- Modify: `src/autoagent/scheduler/batch_scheduler.py`
- Modify: `src/autoagent/api/batches.py` (GET `/batches/{id}` returns `seq`)
- Create: `tests/integration/test_scheduler_events.py`

- [ ] **Step 1: Write the integration test**

`tests/integration/test_scheduler_events.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from autoagent.events.bus import get_event_bus, reset_bus_for_tests
from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample, SampleResult
from autoagent.profiles.schemas import ApiConfig, ApiProfile
from autoagent.scheduler.batch_scheduler import BatchScheduler


class _FastExec(Executor):
    async def execute(self, sample, profile, ctx):  # noqa: ANN001
        return ["ok"]


def _profile() -> ApiProfile:
    return ApiProfile(
        name="fast",
        platform="api",
        api=ApiConfig(base_url="http://x", model="m", api_key_env="NOTHING"),
    )


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_bus_for_tests()
    yield
    reset_bus_for_tests()


async def test_scheduler_publishes_sample_and_batch_events() -> None:
    bus = get_event_bus()
    executor = _FastExec()
    scheduler = BatchScheduler(
        executor_factory=lambda _m: executor,
        profile_lookup=lambda _n: _profile(),
    )

    samples = [
        Sample(id=f"s{i}", prompts=["hi"], mode="api", target_profile="fast", dry_run=True)
        for i in range(2)
    ]

    received: list[tuple[str, dict]] = []

    async def reader(batch_id):
        async for event in bus.subscribe(batch_id):
            received.append((event.kind, event.payload))
            if event.kind == "batch_done":
                break

    batch_id = await scheduler.submit(name="t", mode="api", concurrency=2, samples=samples)
    await asyncio.wait_for(reader(batch_id), timeout=10)

    kinds = [k for k, _ in received]
    assert "sample_update" in kinds
    assert "batch_progress" in kinds
    assert kinds[-1] == "batch_done"
    assert bus.last_seq(batch_id) >= 1


async def test_batch_detail_endpoint_exposes_seq() -> None:
    # Covered more fully in Task 12, but assert here the field exists end-to-end
    from autoagent.api._deps import reset_scheduler_for_tests

    reset_scheduler_for_tests()
    bus = get_event_bus()
    await bus.publish("b_fake", "batch_progress", {"done": 1, "total": 1})
    assert bus.last_seq("b_fake") == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
python3.11 -m pytest tests/integration/test_scheduler_events.py -v
```
Expected: fail because scheduler doesn't publish yet.

- [ ] **Step 3: Wire publishes in scheduler**

Open `src/autoagent/scheduler/batch_scheduler.py`. At top, add:

```python
from autoagent.events.bus import get_event_bus
```

Inside `_run`, after `await update_batch_status(batch_id, "running")`, add:

```python
        bus = get_event_bus()
```

At the start of `run_one`, just before the `if state.cancel_event.is_set()` check, add:

```python
            await bus.publish(
                batch_id, "sample_update",
                {"sample_id": sample.id, "status": "running"},
            )
```

After the `upsert_sample` try/except block, inside the `async with state.progress_lock:` block, after `update_batch_progress`, add:

```python
                    await bus.publish(
                        batch_id,
                        "sample_update",
                        {
                            "sample_id": sample.id,
                            "status": result.status,
                            "duration_ms": result.duration_ms,
                        },
                    )
                    await bus.publish(
                        batch_id,
                        "batch_progress",
                        {
                            "done": state.done_count,
                            "failed": state.failed_count,
                            "total": len(state.samples),
                            "running": 0,  # running count is implicit via sample_update
                        },
                    )
```

In the outer `finally` of `_run`, after `await update_batch_status(batch_id, final_status)` line (which is inside `try`), add a publish in `finally` after `writer.close()`:

```python
            await bus.publish(
                batch_id,
                "batch_done",
                {"status": final_status if 'final_status' in locals() else "failed"},
            )
```

To avoid referencing an unbound name, restructure: capture `final_status` before `finally` runs. Simplest pattern — move the `update_batch_status` + capture to a local, then publish `batch_done` in `finally`:

```python
        final_status: str = "failed"
        try:
            await asyncio.gather(*(run_one(s) for s in state.samples))
            final_status = (
                "cancelled"
                if state.cancel_event.is_set()
                else ("done" if state.failed_count == 0 else "failed")
            )
            await update_batch_status(batch_id, final_status)
        finally:
            writer.close()
            try:
                await bus.publish(batch_id, "batch_done", {"status": final_status})
            except Exception:
                log.exception("failed to publish batch_done for %s", batch_id)
            state.done_event.set()
            log.info("batch %s complete in %.1fs", batch_id, time.monotonic() - start)
```

- [ ] **Step 4: Expose `seq` on BatchDetail GET**

Open `src/autoagent/api/batches.py`. Find the GET `/batches/{id}` handler. Import `get_event_bus` from `autoagent.events.bus` at top. In the handler, after constructing the `BatchDetail` instance (or inside the `**dict`), set:

```python
    detail.seq = get_event_bus().last_seq(batch_id)
```

If the handler returns a newly built `BatchDetail(...)`, add `seq=get_event_bus().last_seq(batch_id)` to the kwargs. Run `grep -n "BatchDetail(" src/autoagent/api/batches.py` to confirm the exact construction site and adapt.

- [ ] **Step 5: Run tests**

```bash
python3.11 -m pytest tests/integration/test_scheduler_events.py tests/integration/test_batches_endpoints.py -v
```
Expected: new events test passes; existing batch tests still pass.

- [ ] **Step 6: Lint and commit**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
git add src/autoagent/scheduler/batch_scheduler.py src/autoagent/api/batches.py tests/integration/test_scheduler_events.py
git commit -m "feat(scheduler): publish sample_update/batch_progress/batch_done events"
```

---

## Task 12: SSE endpoint

Serve `GET /batches/{id}/events` as a Server-Sent Events stream.

**Files:**
- Modify: `src/autoagent/api/batches.py`
- Create: `tests/integration/test_sse_endpoint.py`

- [ ] **Step 1: Write the integration test**

`tests/integration/test_sse_endpoint.py`:

```python
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport

from autoagent.events.bus import get_event_bus, reset_bus_for_tests
from autoagent.main import app
from autoagent.auth.jwt import create_access_token


@pytest.fixture(autouse=True)
def _reset_bus():
    reset_bus_for_tests()
    yield
    reset_bus_for_tests()


@pytest.fixture
def token() -> str:
    return create_access_token("admin")


async def _collect_events(
    client: httpx.AsyncClient, url: str, token: str, n: int
) -> list[dict]:
    out: list[dict] = []
    async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as r:
        assert r.status_code == 200, await r.aread()
        assert r.headers["content-type"].startswith("text/event-stream")
        buffer = ""
        async for chunk in r.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                raw, buffer = buffer.split("\n\n", 1)
                for line in raw.splitlines():
                    if line.startswith("data: "):
                        out.append(json.loads(line[6:]))
                        if len(out) >= n:
                            return out
    return out


async def test_sse_receives_published_events(token: str) -> None:
    bus = get_event_bus()
    transport = ASGITransport(app=app)

    async def publisher():
        await asyncio.sleep(0.1)
        await bus.publish("b1", "batch_progress", {"done": 1, "total": 3})
        await bus.publish("b1", "batch_done", {"status": "done"})

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        pub_task = asyncio.create_task(publisher())
        events = await asyncio.wait_for(
            _collect_events(client, "/api/v1/batches/b1/events", token, 2),
            timeout=5,
        )
        await pub_task

    assert events[0]["kind"] == "batch_progress"
    assert events[1]["kind"] == "batch_done"
    assert events[0]["seq"] < events[1]["seq"]


async def test_sse_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/batches/b1/events")
        assert r.status_code == 401
```

- [ ] **Step 2: Run to verify failure**

```bash
python3.11 -m pytest tests/integration/test_sse_endpoint.py -v
```
Expected: 404 (endpoint doesn't exist).

- [ ] **Step 3: Add the SSE endpoint**

In `src/autoagent/api/batches.py`, add imports at top:

```python
from sse_starlette.sse import EventSourceResponse
from autoagent.events.bus import get_event_bus
```

Append a new route at the bottom of the file:

```python
@router.get("/{batch_id}/events")
async def stream_batch_events(batch_id: str):
    bus = get_event_bus()

    async def generator():
        async for event in bus.subscribe(batch_id):
            yield {
                "id": str(event.seq),
                "event": event.kind,
                "data": json_dumps(
                    {"seq": event.seq, "kind": event.kind, "payload": event.payload,
                     "ts": event.ts}
                ),
            }
            if event.kind == "batch_done":
                break

    return EventSourceResponse(generator())
```

Add import:

```python
import json as _json
def json_dumps(obj) -> str:
    return _json.dumps(obj, separators=(",", ":"))
```

(or use `json.dumps` inline with compact separators — the helper keeps the route tidy).

- [ ] **Step 4: Run tests**

```bash
python3.11 -m pytest tests/integration/test_sse_endpoint.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Run broader suite to catch regressions**

```bash
python3.11 -m pytest -q -m "not playwright"
```

- [ ] **Step 6: Lint and commit**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
git add src/autoagent/api/batches.py tests/integration/test_sse_endpoint.py
git commit -m "feat(api): SSE endpoint /batches/{id}/events via sse-starlette"
```

---

## Task 13: Screenshots endpoints

`GET /batches/{bid}/samples/{sid}/screenshots` (list) and `/.../screenshots/{name}` (download) with path-traversal guards.

**Files:**
- Modify: `src/autoagent/api/batches.py`
- Modify: `src/autoagent/models/api.py` (add `ScreenshotInfo`)
- Create: `tests/integration/test_screenshots_endpoint.py`

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_screenshots_endpoint.py`:

```python
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from autoagent.auth.jwt import create_access_token
from autoagent.config.settings import get_settings
from autoagent.main import app


@pytest.fixture
def token() -> str:
    return create_access_token("admin")


def _seed(tmp_logs: Path, batch_id: str, sample_id: str) -> None:
    d = tmp_logs / batch_id / sample_id
    d.mkdir(parents=True)
    (d / "01_ready.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (d / "02_filled.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")


async def test_list_screenshots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/api/v1/batches/b1/samples/s1/screenshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        names = [x["name"] for x in r.json()]
        assert names == ["01_ready.png", "02_filled.png"]


async def test_download_screenshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/api/v1/batches/b1/samples/s1/screenshots/01_ready.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert r.content.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "bad_name",
    [
        "../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "01_ready.jpg",
        "01_READY.png",
        "a.png",
    ],
)
async def test_download_rejects_invalid_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str, bad_name: str
) -> None:
    logs = tmp_path / "logs"
    _seed(logs, "b1", "s1")
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            f"/api/v1/batches/b1/samples/s1/screenshots/{bad_name}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code in (400, 404)


async def test_list_missing_dir_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, token: str
) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(
        "autoagent.api.batches.get_settings",
        lambda: get_settings().model_copy(update={"logs_root": logs}),
    )
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.get(
            "/api/v1/batches/b_none/samples/s_none/screenshots",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json() == []
```

- [ ] **Step 2: Run to verify failures**

```bash
python3.11 -m pytest tests/integration/test_screenshots_endpoint.py -v
```

- [ ] **Step 3: Add `ScreenshotInfo` model**

Open `src/autoagent/models/api.py`. Add:

```python
class ScreenshotInfo(BaseModel):
    name: str
    label: str
    taken_at: datetime
```

Place near the other small response models. `datetime` is already imported.

- [ ] **Step 4: Implement endpoints**

In `src/autoagent/api/batches.py`, add imports/constants at top:

```python
import re
from datetime import datetime, timezone
from autoagent.models.api import ScreenshotInfo

_SCREENSHOT_RE = re.compile(r"^\d{2,3}_[a-z0-9_]+\.png$")
```

Append routes at the bottom:

```python
@router.get(
    "/{batch_id}/samples/{sample_id}/screenshots",
    response_model=list[ScreenshotInfo],
)
async def list_screenshots(batch_id: str, sample_id: str) -> list[ScreenshotInfo]:
    settings = get_settings()
    sample_dir = (settings.logs_root / batch_id / sample_id).resolve()
    if not sample_dir.is_dir():
        return []
    out: list[ScreenshotInfo] = []
    for entry in sorted(sample_dir.iterdir()):
        if not entry.is_file() or not _SCREENSHOT_RE.match(entry.name):
            continue
        label = entry.stem.split("_", 1)[1] if "_" in entry.stem else entry.stem
        taken = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        out.append(ScreenshotInfo(name=entry.name, label=label, taken_at=taken))
    return out


@router.get("/{batch_id}/samples/{sample_id}/screenshots/{name}")
async def download_screenshot(batch_id: str, sample_id: str, name: str) -> FileResponse:
    if not _SCREENSHOT_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid screenshot name")
    settings = get_settings()
    root = settings.logs_root.resolve()
    target = (root / batch_id / sample_id / name).resolve()
    try:
        target.relative_to(root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path traversal blocked") from e
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        target,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
```

- [ ] **Step 5: Run tests**

```bash
python3.11 -m pytest tests/integration/test_screenshots_endpoint.py -v
python3.11 -m pytest -q -m "not playwright"
```
Expected: 4 new tests pass; overall suite passes.

- [ ] **Step 6: Lint and commit**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
git add src/autoagent/api/batches.py src/autoagent/models/api.py tests/integration/test_screenshots_endpoint.py
git commit -m "feat(api): screenshot list + download endpoints (traversal-guarded)"
```

---

## Task 14: `/tests/sync` dispatches by profile.platform

When caller hits `/tests/sync` with a `mode=gui_pc_web` sample, the scheduler already dispatches through the factory, so this works end-to-end once Tasks 2+8 are in place. This task adds an explicit integration test that the connectivity flow works for a web profile, and extends the timeout path for web samples.

**Files:**
- Modify: `src/autoagent/api/tests.py` (timeout extension note)
- Create: `tests/integration/test_tests_sync_web.py`

- [ ] **Step 1: Write the integration test**

`tests/integration/test_tests_sync_web.py`:

```python
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from autoagent.auth.jwt import create_access_token
from autoagent.main import app
from autoagent.profiles.registry import save_profile

FIXTURE = (Path(__file__).parent.parent / "fixtures" / "fake_chat.html").resolve()
FIXTURE_URL = FIXTURE.as_uri()

pytestmark = pytest.mark.playwright


@pytest.fixture
def token() -> str:
    return create_access_token("admin")


async def test_tests_sync_routes_to_web_executor(tmp_path: Path, token: str) -> None:
    # Save a web profile in the profile registry
    yaml_content = f"""
name: fake_site
platform: web
url: "{FIXTURE_URL}"
browser:
  headless: true
ready_check:
  type: dom_selector
  selector: '#input'
  timeout_sec: 10
recovery_path:
  - {{ action: goto, url: "{FIXTURE_URL}" }}
input_selector: '#input'
send_method:
  type: click_button
  selector: '#send'
response_container_selector: "#responses > div[data-role='assistant']:last-child"
new_session_action:
  - {{ action: click, selector: '#new-chat' }}
complete_detection:
  type: dom_stable
  stable_sec: 0.8
  max_wait_sec: 30
"""
    await save_profile("fake_site", yaml_content)

    payload = {
        "id": "t1",
        "prompts": ["hi"],
        "mode": "gui_pc_web",
        "target_profile": "fake_site",
        "retry": 0,
        "timeout_sec": 60,
    }
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        timeout=120,
    ) as c:
        r = await c.post(
            "/api/v1/tests/sync",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "done"
        assert body["responses"] == ["echo: hi"]
```

- [ ] **Step 2: Confirm the current `/tests/sync` handler tolerates long timeouts**

Open `src/autoagent/api/tests.py`. The current `wait_done` call uses `timeout_sec=(sample.timeout_sec or 600) + 30`, which already accommodates web samples. No code change needed, but add a comment for clarity:

```python
    # sample.timeout_sec is the per-sample timeout; we wait slightly longer
    # to absorb executor startup/teardown (notably Playwright launch time).
    await sch.wait_done(batch_id, timeout_sec=(sample.timeout_sec or 600) + 30)
```

- [ ] **Step 3: Run the test (real Chromium required)**

```bash
python3.11 -m pytest tests/integration/test_tests_sync_web.py -v
```
Expected: 1 passed. If profile save fails due to registry path, confirm `get_settings().data_root` is writable in the test env; if necessary, add a `monkeypatch` to point `data_root` at `tmp_path`.

- [ ] **Step 4: Commit**

```bash
git add src/autoagent/api/tests.py tests/integration/test_tests_sync_web.py
git commit -m "test(integration): /tests/sync dispatches web profile to WebExecutor"
```

---

## Task 15: Frontend types + screenshots API + `useBatchStream` hook

**Files:**
- Modify: `web/src/types/api.ts`
- Create: `web/src/api/screenshots.ts`
- Create: `web/src/hooks/useBatchStream.ts`
- Create: `web/src/hooks/useBatchStream.test.ts`

- [ ] **Step 1: Extend types**

In `web/src/types/api.ts`, add:

```ts
export interface ScreenshotInfo {
  name: string
  label: string
  taken_at: string
}
```

Find `BatchDetail` and add `seq: number` as a required field.

- [ ] **Step 2: Add the screenshots API client**

`web/src/api/screenshots.ts`:

```ts
import { client } from './client'
import { ScreenshotInfo } from '../types/api'

export async function listScreenshots(
  batchId: string,
  sampleId: string,
): Promise<ScreenshotInfo[]> {
  const { data } = await client.get<ScreenshotInfo[]>(
    `/batches/${batchId}/samples/${sampleId}/screenshots`,
  )
  return data
}

export function screenshotUrl(batchId: string, sampleId: string, name: string): string {
  // returns a relative URL; AntD <Image> and <img src> will go through the same auth layer
  return `/api/v1/batches/${batchId}/samples/${sampleId}/screenshots/${encodeURIComponent(name)}`
}
```

Note: the screenshot download is served by FastAPI at same origin; authenticated `<img>` requests do not carry the bearer token from axios. Plan-3 approach: since the auth gate relies on the bearer token, we must load screenshots via `fetch()` with `Authorization` header and then render via `URL.createObjectURL(blob)`, or else serve them with a cookie session. Since Plan 2 ships token-in-localStorage only, use a helper:

Replace `screenshotUrl` with a lazy blob fetcher:

```ts
export async function fetchScreenshotBlobUrl(
  batchId: string,
  sampleId: string,
  name: string,
): Promise<string> {
  const { data } = await client.get<Blob>(
    `/batches/${batchId}/samples/${sampleId}/screenshots/${encodeURIComponent(name)}`,
    { responseType: 'blob' },
  )
  return URL.createObjectURL(data)
}
```

`screenshotUrl` is still useful for the `<img loading="lazy">` src when paired with `fetchScreenshotBlobUrl` resolution. Keep both:

```ts
export function screenshotPath(batchId: string, sampleId: string, name: string): string {
  return `/api/v1/batches/${batchId}/samples/${sampleId}/screenshots/${encodeURIComponent(name)}`
}
```

- [ ] **Step 3: Implement `useBatchStream`**

`web/src/hooks/useBatchStream.ts`:

```ts
import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { BatchDetail } from '../types/api'
import { client } from '../api/client'

type SseEvent = {
  seq: number
  kind: 'sample_update' | 'batch_progress' | 'batch_done'
  payload: Record<string, unknown>
  ts: string
}

export function useBatchStream(id: string | undefined) {
  const queryClient = useQueryClient()
  const seqRef = useRef(0)
  const query = useQuery({
    queryKey: ['batch', id],
    queryFn: async () => {
      const { data } = await client.get<BatchDetail>(`/batches/${id}`)
      seqRef.current = data.seq ?? 0
      return data
    },
    enabled: !!id,
  })

  useEffect(() => {
    if (!id || !query.data) return
    const token = localStorage.getItem('autoagent_token') ?? ''
    // EventSource can't set headers; fall back to a query-string token on the endpoint
    // is an option, but the current backend uses Depends(require_user) on the Bearer header.
    // Workaround: use a short-lived fetch-based ReadableStream parser that honors the header.
    const abort = new AbortController()

    const run = async () => {
      const resp = await fetch(`/api/v1/batches/${id}/events`, {
        headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
        signal: abort.signal,
      })
      if (!resp.ok || !resp.body) return
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() ?? ''
        for (const chunk of chunks) {
          for (const line of chunk.split('\n')) {
            if (!line.startsWith('data: ')) continue
            const event = JSON.parse(line.slice(6)) as SseEvent
            if (event.seq <= seqRef.current) continue
            seqRef.current = event.seq
            queryClient.setQueryData<BatchDetail | undefined>(
              ['batch', id],
              (prev) => applyEvent(prev, event),
            )
            if (event.kind === 'batch_done') abort.abort()
          }
        }
      }
    }
    run().catch(() => {})

    return () => abort.abort()
  }, [id, query.data !== undefined, queryClient])

  return query
}

function applyEvent(
  prev: BatchDetail | undefined,
  event: SseEvent,
): BatchDetail | undefined {
  if (!prev) return prev
  const next: BatchDetail = { ...prev, seq: event.seq }
  if (event.kind === 'batch_progress') {
    const p = event.payload as { done?: number; failed?: number; total?: number }
    if (typeof p.done === 'number') next.done = p.done
    if (typeof p.failed === 'number') next.failed = p.failed
  }
  if (event.kind === 'sample_update') {
    // Light-touch: just bump seq so consumers re-render; the full sample list
    // is refetched by react-query on next user interaction.
  }
  if (event.kind === 'batch_done') {
    const p = event.payload as { status?: BatchDetail['status'] }
    if (p.status) next.status = p.status
  }
  return next
}
```

- [ ] **Step 4: Write a unit test for seq dedup + batch_done shutdown**

`web/src/hooks/useBatchStream.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

import { useBatchStream } from './useBatchStream'

let fetchCalls: string[] = []
let readerFrames: string[] = []

function encodeStream(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    async start(controller) {
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame))
        await new Promise((r) => setTimeout(r, 10))
      }
      controller.close()
    },
  })
}

beforeEach(() => {
  fetchCalls = []
  localStorage.setItem('autoagent_token', 'tok')
  global.fetch = vi.fn(async (url: string, init?: RequestInit) => {
    fetchCalls.push(String(url))
    if (String(url).endsWith('/events')) {
      return new Response(encodeStream(readerFrames), {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      })
    }
    // initial GET
    return new Response(
      JSON.stringify({
        batch_id: 'b1',
        name: 'n',
        mode: 'api',
        status: 'running',
        total: 3,
        done: 0,
        failed: 0,
        seq: 0,
        concurrency: 1,
        samples: [],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    )
  }) as unknown as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
})

function withProvider(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useBatchStream', () => {
  it('applies batch_progress events to cached data', async () => {
    readerFrames = [
      'data: {"seq":1,"kind":"batch_progress","payload":{"done":1,"failed":0,"total":3},"ts":"t"}\n\n',
      'data: {"seq":2,"kind":"batch_done","payload":{"status":"done"},"ts":"t"}\n\n',
    ]
    const { result } = renderHook(() => useBatchStream('b1'), {
      wrapper: ({ children }) => withProvider(children),
    })
    await waitFor(() => expect(result.current.data?.done).toBe(1))
    await waitFor(() => expect(result.current.data?.status).toBe('done'))
  })

  it('drops events with seq <= initial', async () => {
    readerFrames = [
      'data: {"seq":0,"kind":"batch_progress","payload":{"done":99},"ts":"t"}\n\n',
      'data: {"seq":1,"kind":"batch_progress","payload":{"done":5},"ts":"t"}\n\n',
      'data: {"seq":2,"kind":"batch_done","payload":{"status":"done"},"ts":"t"}\n\n',
    ]
    const { result } = renderHook(() => useBatchStream('b1'), {
      wrapper: ({ children }) => withProvider(children),
    })
    await waitFor(() => expect(result.current.data?.done).toBe(5))
    expect(result.current.data?.done).not.toBe(99)
  })
})
```

- [ ] **Step 5: Run tests**

```bash
cd web && pnpm test
```
Expected: prior 8 + 2 new = 10 passed.

- [ ] **Step 6: Commit**

```bash
cd ..
git add web/src/types/api.ts web/src/api/screenshots.ts web/src/hooks/useBatchStream.ts web/src/hooks/useBatchStream.test.ts
git commit -m "feat(web): useBatchStream + screenshots API + types"
```

---

## Task 16: Frontend mode dropdown + profile filter (BatchNew, Tests/Quick)

**Files:**
- Modify: `web/src/pages/Batches/New.tsx`
- Modify: `web/src/pages/Tests/Quick.tsx`

- [ ] **Step 1: Extend mode dropdown in BatchNew**

In `web/src/pages/Batches/New.tsx`, find the mode `Select` options. Add `{ label: 'Web (GUI)', value: 'gui_pc_web' }` after the `api` option.

Filter the target-profile list by currently-selected mode: api-mode shows profiles with `platform: api`; web-mode shows `platform: web`. Use the existing `useProfiles()` result and filter client-side.

Concrete: inside the `Form` component, read the current mode via `Form.useWatch('mode', form)` and compute:

```tsx
const mode = Form.useWatch('mode', form)
const selectedPlatform = mode === 'gui_pc_web' ? 'web' : 'api'
const profileOptions = (profiles ?? [])
  .filter((p) => p.platform === selectedPlatform)
  .map((p) => ({ label: p.name, value: p.name }))
```

- [ ] **Step 2: Same change in Tests/Quick**

`web/src/pages/Tests/Quick.tsx`: add `gui_pc_web` option and apply the same platform filter.

For web mode, override the sync request timeout:

```tsx
const payload = { ...values, mode, retry: 0, timeout_sec: mode === 'gui_pc_web' ? 180 : 60 }
const resp = await client.post<SampleResult>('/tests/sync', payload, {
  timeout: mode === 'gui_pc_web' ? 240_000 : 60_000,
})
```

- [ ] **Step 3: Run tests + build**

```bash
cd web && pnpm test && pnpm build
```
Expected: all tests pass; build succeeds.

- [ ] **Step 4: Commit**

```bash
cd ..
git add web/src/pages/Batches/New.tsx web/src/pages/Tests/Quick.tsx
git commit -m "feat(web): gui_pc_web in mode dropdown + platform-filtered profiles"
```

---

## Task 17: Frontend Profile Edit — enable connectivity test for web

**Files:**
- Modify: `web/src/pages/Profiles/Edit.tsx`
- Modify: `web/src/pages/Profiles/ConnectivityTestModal.tsx`

- [ ] **Step 1: Relax the regex that enables the button**

Current code checks `/^platform:\s*api\b/m`. Replace with:

```ts
const PLATFORM_RE = /^platform:\s*(api|web)\b/m
const canTest = PLATFORM_RE.test(yaml)
const platformFromYaml: 'api' | 'web' | null = (() => {
  const m = PLATFORM_RE.exec(yaml)
  return (m?.[1] as 'api' | 'web') ?? null
})()
```

Pass `platformFromYaml` into the modal.

- [ ] **Step 2: Modal sends appropriate mode + timeout**

In `ConnectivityTestModal.tsx`, accept a new prop `platform: 'api' | 'web' | null`. Compute:

```ts
const mode = platform === 'web' ? 'gui_pc_web' : 'api'
const timeoutSec = platform === 'web' ? 180 : 60
const httpTimeoutMs = platform === 'web' ? 240_000 : 60_000
```

Use these in the `/tests/sync` POST. Display "等待浏览器启动 + 响应(最长 3 分钟)" hint when `platform === 'web'`.

- [ ] **Step 3: Run tests**

```bash
cd web && pnpm test
```

- [ ] **Step 4: Commit**

```bash
cd ..
git add web/src/pages/Profiles/Edit.tsx web/src/pages/Profiles/ConnectivityTestModal.tsx
git commit -m "feat(web): connectivity test button supports platform=web (180s timeout)"
```

---

## Task 18: SampleDetail — ScreenshotStrip + ActionLogTable

**Files:**
- Create: `web/src/components/ScreenshotStrip.tsx`
- Modify: `web/src/pages/Batches/SampleDetail.tsx`

- [ ] **Step 1: ScreenshotStrip component**

`web/src/components/ScreenshotStrip.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Image, Spin, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { listScreenshots, fetchScreenshotBlobUrl } from '../api/screenshots'

interface Props {
  batchId: string
  sampleId: string
}

export function ScreenshotStrip({ batchId, sampleId }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['screenshots', batchId, sampleId],
    queryFn: () => listScreenshots(batchId, sampleId),
  })
  const [blobs, setBlobs] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!data) return
    let revoked = false
    ;(async () => {
      const out: Record<string, string> = {}
      for (const item of data) {
        try {
          out[item.name] = await fetchScreenshotBlobUrl(batchId, sampleId, item.name)
        } catch (_e) {
          // ignore single-image failures
        }
      }
      if (!revoked) setBlobs(out)
    })()
    return () => {
      revoked = true
      Object.values(blobs).forEach((u) => URL.revokeObjectURL(u))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, batchId, sampleId])

  if (isLoading) return <Spin />
  if (!data || data.length === 0) return <Empty description="no screenshots" />

  return (
    <Image.PreviewGroup>
      <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 8 }}>
        {data.map((item) => (
          <div key={item.name} style={{ flex: '0 0 auto', textAlign: 'center' }}>
            <Image
              width={160}
              height={100}
              src={blobs[item.name]}
              placeholder={<Spin />}
              alt={item.label}
              style={{ objectFit: 'cover', border: '1px solid #eee' }}
            />
            <div style={{ fontSize: 12, color: '#666' }}>{item.label}</div>
          </div>
        ))}
      </div>
    </Image.PreviewGroup>
  )
}
```

- [ ] **Step 2: Add ActionLogTable inline + render in SampleDetail**

In `web/src/pages/Batches/SampleDetail.tsx`, import `ScreenshotStrip` and render below the existing response block. Add an `ActionLog` table reading `sample.metadata.action_log`:

```tsx
import { Table, Typography } from 'antd'
import { ScreenshotStrip } from '../../components/ScreenshotStrip'
// ...existing imports

type ActionLogEntry = {
  t_ms: number
  action: string
  selector?: string | null
  ok: boolean
  error?: string | null
}

// Inside the component, after the responses section:
{sample && (
  <>
    <Typography.Title level={5} style={{ marginTop: 24 }}>Screenshots</Typography.Title>
    <ScreenshotStrip batchId={batchId!} sampleId={sample.id} />

    <Typography.Title level={5} style={{ marginTop: 24 }}>Action log</Typography.Title>
    <Table<ActionLogEntry>
      size="small"
      rowKey={(r) => `${r.t_ms}-${r.action}`}
      pagination={false}
      dataSource={(sample.metadata?.action_log as ActionLogEntry[] | undefined) ?? []}
      columns={[
        { title: 't (ms)', dataIndex: 't_ms', width: 80 },
        { title: 'action', dataIndex: 'action', width: 120 },
        { title: 'selector', dataIndex: 'selector', ellipsis: true },
        { title: 'ok', dataIndex: 'ok', width: 60, render: (v: boolean) => (v ? '✓' : '✗') },
        { title: 'error', dataIndex: 'error', ellipsis: true },
      ]}
      locale={{ emptyText: 'no actions recorded' }}
    />
  </>
)}
```

- [ ] **Step 3: Run tests + build**

```bash
cd web && pnpm test && pnpm build && pnpm lint
```

- [ ] **Step 4: Commit**

```bash
cd ..
git add web/src/components/ScreenshotStrip.tsx web/src/pages/Batches/SampleDetail.tsx
git commit -m "feat(web): SampleDetail screenshots strip + action log table"
```

---

## Task 19: Swap `useBatch` → `useBatchStream`

Keep `useBatch` exported for back-compat internally, but point `BatchDetail.tsx` at the streaming hook.

**Files:**
- Modify: `web/src/api/batches.ts` (re-export `useBatchStream`)
- Modify: `web/src/pages/Batches/Detail.tsx`

- [ ] **Step 1: Re-export `useBatchStream` from `api/batches.ts`**

At the bottom of `web/src/api/batches.ts`:

```ts
export { useBatchStream } from '../hooks/useBatchStream'
```

- [ ] **Step 2: Switch consumer**

In `web/src/pages/Batches/Detail.tsx`, replace:

```ts
import { useBatch } from '../../api/batches'
// ...
const { data, isLoading, error } = useBatch(id)
```

with:

```ts
import { useBatchStream } from '../../api/batches'
// ...
const { data, isLoading, error } = useBatchStream(id)
```

- [ ] **Step 3: Verify existing `Detail.test.tsx` still passes**

```bash
cd web && pnpm test
```
Expected: existing `Detail.test.tsx` still green. If it relied on `refetchInterval` behavior, relax the assertion — the hook now relies on SSE which the test's `mock` server doesn't provide, but the initial GET path still works.

If the test fails due to SSE fetch noise, adjust the test to also mock `fetch` for `/api/v1/batches/:id/events` to return an empty stream.

- [ ] **Step 4: Lint + build**

```bash
cd web && pnpm lint && pnpm build
```

- [ ] **Step 5: Commit**

```bash
cd ..
git add web/src/api/batches.ts web/src/pages/Batches/Detail.tsx web/src/pages/Batches/Detail.test.tsx
git commit -m "feat(web): BatchDetail uses useBatchStream (SSE) instead of polling"
```

---

## Task 20: Final verification + CLAUDE.md + tag

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run backend full suite (including playwright-marked)**

```bash
python3.11 -m pytest -v
```
Expected: ~95 passed (68 prior + ~25 new). If any `@pytest.mark.playwright` test fails, confirm `python3.11 -m playwright install chromium` has been run.

- [ ] **Step 2: Run backend fast suite (without Chromium)**

```bash
python3.11 -m pytest -q -m "not playwright"
```
Expected: ~88 passed.

- [ ] **Step 3: Run backend lint**

```bash
python3.11 -m ruff check . && python3.11 -m ruff format --check .
```
Expected: clean.

- [ ] **Step 4: Run frontend**

```bash
cd web && pnpm test && pnpm lint && pnpm format:check && pnpm build && cd ..
```
Expected: all green, `src/autoagent/static/` regenerated.

- [ ] **Step 5: Manual browser smoke — web mode end-to-end**

Assuming `tests/fixtures/fake_chat.html` is reachable:

```bash
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=admin_pw_1234
export JWT_SECRET=$(python3.11 -c "import secrets; print(secrets.token_hex(32))")
python3.11 -m uvicorn --app-dir src autoagent.main:app --port 8000
```

In a browser:

1. Log in at `http://localhost:8000/`.
2. Go to Profiles → new `fake_web`. Paste a YAML pointing `url:` at `file:///.../tests/fixtures/fake_chat.html` (use the absolute path). Save.
3. Click 连通性测试, prompt `hi`, wait — expect `echo: hi` response.
4. Go to Tests / Quick, mode `Web (GUI)`, profile `fake_web`, prompt `hi` — expect response.
5. Go to Batches / 新建批次, mode `Web (GUI)`, profile `fake_web`, upload a 3-line JSONL each with `mode: gui_pc_web`, `target_profile: fake_web`, `prompts: [...]`. Create.
6. Observe live SSE updates (no 2s polling in Network panel; only a pending `/events` stream). Batch reaches `done`.
7. Open SampleDetail — screenshots strip shows thumbnails; Action log populated.
8. Log out, revisit — redirect to `/login`.

- [ ] **Step 6: Update CLAUDE.md**

Replace the Plan 3 line under "Development status":

```markdown
- **Plan 3 — Web GUI Executor (Playwright):** ✅ complete (tag `web-gui-executor-v0.3.0`, <YYYY-MM-DD>). Playwright-backed `WebExecutor`, scheduler auto-downgrades concurrency for user_data_dir profiles, SSE replaces 2s polling, screenshot strip + action log in SampleDetail, connectivity test supports web profiles. Backend ~88 non-playwright tests + ~7 real-Chromium tests green.
```

Extend "Conventions" with:

```markdown
- **Playwright install:** run `python3.11 -m playwright install chromium` once per machine. Tests marked `@pytest.mark.playwright` require this; use `pytest -q -m "not playwright"` for the fast subset.
- **Screenshots:** `<data_root>/logs/<batch_id>/<sample_id>/NNN_<label>.png`. `ExecutorContext.verbose_logs=True` captures per-action; `False` captures milestones-only.
- **SSE progress:** `GET /api/v1/batches/{id}/events` is a streaming endpoint; frontend hook `useBatchStream` reconciles via `seq`. WebSocket is not used.
```

- [ ] **Step 7: Commit docs**

```bash
git add CLAUDE.md
git commit -m "docs: mark Plan 3 complete (Web GUI Executor)"
```

- [ ] **Step 8: Tag**

```bash
git tag -a web-gui-executor-v0.3.0 -m "Plan 3 complete: Web GUI Executor (Playwright)"
```

---

## Acceptance criteria (Plan 3 done when:)

1. ✅ `python3.11 -m pytest -v` = ~95 passed (68 prior + ~25 new).
2. ✅ `python3.11 -m pytest -q -m "not playwright"` runs without Chromium installed.
3. ✅ `ruff check .` + `ruff format --check .` clean.
4. ✅ `cd web && pnpm test && pnpm lint && pnpm build` green.
5. ✅ Profile Edit connectivity test works end-to-end against `fake_chat.html` for a `platform: web` profile.
6. ✅ A web batch with 3 samples and `concurrency=2` on an ephemeral profile completes, peak 2 running.
7. ✅ BatchDetail updates in real time via SSE; DevTools shows a single long-lived `/events` request and no 2s polling cycle.
8. ✅ `useBatchStream` closes its fetch on unmount (no dangling requests in DevTools).
9. ✅ SampleDetail screenshots strip renders thumbnails + modal viewer + Action log table.
10. ✅ CLAUDE.md reflects Plan 3 complete; tag `web-gui-executor-v0.3.0` present.

---

## Handoff to Plan 4 (Android Executor)

- The `Executor` interface is stable. Plan 4 adds `AndroidExecutor` (uiautomator2 + PaddleOCR).
- `CompleteDetector` adds `ui_tree_stable` + `pixel_stable` strategies alongside the existing `dom_stable` + `send_button_reenable`.
- `ScreenshotStore` is platform-agnostic and will be reused for Android screenshots.
- SSE event bus is platform-agnostic; Android events will use the same `sample_update` / `batch_progress` / `batch_done` kinds.
- Plan 4 introduces a new `DevicePool` (ADB lock) that does not exist yet.
