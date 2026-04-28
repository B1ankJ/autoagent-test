# Web LLM Response Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional LLM-assisted response extraction to the Web executor, mirroring the Android pattern — profile YAML carries credentials, LLM runs in parallel with CSS selector extraction every round, results stored in `ctx.llm_responses` / `ctx.llm_errors`.

**Architecture:** Three focused changes: (1) add credential fields + `llm_response_enabled()` to `WebProfile`; (2) new `web_response_llm_extractor.py` with a web-specific HTML system prompt and an `_capture_html()` Playwright helper; (3) integrate the call into `web_executor.py` after each rule extraction round with soft failure.

**Tech Stack:** Python 3.11, httpx (async), pydantic v2, playwright (async), pytest-asyncio, pytest monkeypatch + `httpx.MockTransport`.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `src/autoagent/profiles/schemas.py` |
| Create | `src/autoagent/executors/web_response_llm_extractor.py` |
| Modify | `src/autoagent/executors/web_executor.py` |
| Create | `tests/unit/test_web_response_llm_extractor.py` |
| Modify | `tests/unit/test_web_profile_schema.py` *(new if absent)* |

---

### Task 1: Add LLM credential fields to `WebProfile`

**Files:**
- Modify: `src/autoagent/profiles/schemas.py:97-108`
- Create/modify: `tests/unit/test_web_profile_schema.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_web_profile_schema.py`:

```python
import pytest
from autoagent.profiles.schemas import WebProfile


def _base_profile(**extra):
    return {
        "name": "test_web",
        "platform": "web",
        "url": "https://example.com",
        "ready_check": {"type": "dom_selector", "selector": "[role='textbox']"},
        "recovery_path": [],
        "input_selector": "[role='textbox']",
        "send_method": {"type": "keyboard", "key": "Enter"},
        "response_container_selector": ".reply",
        "complete_detection": {"type": "dom_stable", "stable_sec": 2, "max_wait_sec": 120},
        **extra,
    }


def test_llm_disabled_by_default():
    p = WebProfile(**_base_profile())
    assert p.llm_response_enabled() is False


def test_llm_disabled_when_partial():
    p = WebProfile(**_base_profile(base_url="https://api/v1", model="m"))
    assert p.llm_response_enabled() is False


def test_llm_enabled_when_all_set():
    p = WebProfile(**_base_profile(
        base_url="https://api/v1", model="my-model", api_key="sk-123"
    ))
    assert p.llm_response_enabled() is True


def test_llm_disabled_when_empty_string():
    p = WebProfile(**_base_profile(base_url="", model="m", api_key="k"))
    assert p.llm_response_enabled() is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_web_profile_schema.py -v
```

Expected: `AttributeError: 'WebProfile' object has no attribute 'llm_response_enabled'` or similar.

- [ ] **Step 3: Add fields and method to `WebProfile`**

In `src/autoagent/profiles/schemas.py`, replace the `WebProfile` class body (lines 97-108):

```python
class WebProfile(BaseModel):
    name: str
    platform: Literal["web"]
    url: str
    browser: WebBrowserConfig = Field(default_factory=WebBrowserConfig)
    ready_check: WebReadyCheck
    recovery_path: list[ActionStep]
    input_selector: str
    send_method: WebSendMethod
    response_container_selector: str
    new_session_action: list[ActionStep] = Field(default_factory=list)
    complete_detection: CompleteDetection
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None

    def llm_response_enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3.11 -m pytest tests/unit/test_web_profile_schema.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Run fast suite to check no regressions**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/profiles/schemas.py tests/unit/test_web_profile_schema.py
git commit -m "feat: add LLM credential fields to WebProfile"
```

---

### Task 2: Create `web_response_llm_extractor.py`

**Files:**
- Create: `src/autoagent/executors/web_response_llm_extractor.py`
- Create: `tests/unit/test_web_response_llm_extractor.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/test_web_response_llm_extractor.py`:

```python
import httpx
import pytest

from autoagent.executors.web_response_llm_extractor import extract_web_response_via_llm


def _mock(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_extract_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"response": "Hello from AI"}'}}]},
        )

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor._make_client", _f
    )
    r = await extract_web_response_via_llm(
        prompt="hi",
        html="<div class='reply'>Hello from AI</div>",
        base_url="https://api/v1",
        model="m",
        api_key="k",
    )
    assert r.text == "Hello from AI"
    assert r.error is None
    assert r.latency_ms >= 0
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_extract_empty_response_is_not_error(monkeypatch):
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"response": ""}'}}]}
        )

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor._make_client", _f
    )
    r = await extract_web_response_via_llm(
        prompt="hi", html="<div/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error is None


@pytest.mark.asyncio
async def test_extract_auth_failure(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor._make_client", _f
    )
    r = await extract_web_response_via_llm(
        prompt="hi", html="<div/>", base_url="https://api/v1", model="m", api_key="bad"
    )
    assert r.text == ""
    assert r.error == "auth"
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_extract_response_shape_failure(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor._make_client", _f
    )
    r = await extract_web_response_via_llm(
        prompt="hi", html="<div/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error == "response_shape"


@pytest.mark.asyncio
async def test_extract_connect_error(monkeypatch):
    async def _f(*, timeout):
        return httpx.AsyncClient(
            transport=_mock(lambda req: (_ for _ in ()).throw(httpx.ConnectError("refused"))),
            timeout=timeout,
        )

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor._make_client", _f
    )
    r = await extract_web_response_via_llm(
        prompt="hi", html="<div/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error == "connect"


@pytest.mark.asyncio
async def test_extract_truncates_oversized_html(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        captured["len"] = len(body)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"response": "ok"}'}}]}
        )

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.web_response_llm_extractor._make_client", _f
    )
    huge = "x" * 300_000
    r = await extract_web_response_via_llm(
        prompt="hi",
        html=huge,
        base_url="https://api/v1",
        model="m",
        api_key="k",
        max_html_chars=120_000,
    )
    assert r.text == "ok"
    assert r.error == "truncated"
    assert r.truncated_input is True
    assert captured["len"] < 300_000 + 5000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_web_response_llm_extractor.py -v
```

Expected: `ModuleNotFoundError: No module named 'autoagent.executors.web_response_llm_extractor'`

- [ ] **Step 3: Create the extractor module**

Create `src/autoagent/executors/web_response_llm_extractor.py`:

```python
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from autoagent.executors.response_llm_extractor import LLMExtractionResult

_SYSTEM_PROMPT = (
    "你是一个网页内容提取助手。用户会给你：\n"
    "1) 本轮用户发送给 AI 产品的 prompt 文本；\n"
    "2) 本轮页面的 HTML 片段（可能是响应容器的 outerHTML，也可能是整页 body）。\n\n"
    "你的唯一任务：从 HTML 中找出 AI 助手对用户 prompt 的最新一条回复，"
    "把该回复的纯文本内容原样抽取出来。\n\n"
    "规则：\n"
    "- 只返回助手最新一条回复的文本，不要包含用户自己的 prompt、历史消息、"
    "按钮文字、占位符、界面提示、加载动画文字等 UI 元素的内容。\n"
    "- 若 HTML 中找不到可识别的助手回复，返回空字符串。\n"
    "- 不做改写、不做总结、不加前后缀、不输出解释。\n"
    "- 严格按给定 JSON schema 返回。"
)

_RESPONSE_SCHEMA = {
    "name": "web_response_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"response": {"type": "string"}},
        "required": ["response"],
    },
}


async def _make_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _truncate_html(html: str, max_chars: int) -> tuple[str, bool]:
    if len(html) <= max_chars:
        return html, False
    part = max_chars // 3
    head = html[:part]
    mid_start = (len(html) - part) // 2
    middle = html[mid_start : mid_start + part]
    tail = html[-part:]
    return (
        f"{head}\n<!-- truncated -->\n{middle}\n<!-- truncated -->\n{tail}",
        True,
    )


def _parse_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = [c.get("text", "") for c in content if isinstance(c, dict)]
        return "".join(chunks)
    raise ValueError("unsupported content shape")


def _clip_debug_text(value: str, max_chars: int = 4000) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}\n...<truncated {len(value) - max_chars} chars>"


async def extract_web_response_via_llm(
    *,
    prompt: str,
    html: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
    max_html_chars: int = 120_000,
) -> LLMExtractionResult:
    trimmed, truncated = _truncate_html(html, max_html_chars)
    user_payload = {"prompt": prompt, "html": trimmed}
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = base_url.rstrip("/") + "/chat/completions"
    timeout = httpx.Timeout(timeout_sec)

    started = time.monotonic()
    try:
        async with (await _make_client(timeout=timeout)) as client:
            resp = await client.post(url, headers=headers, json=body)
    except httpx.TimeoutException:
        return LLMExtractionResult(
            "",
            "timeout",
            int((time.monotonic() - started) * 1000),
            truncated_input=truncated,
        )
    except httpx.HTTPError:
        return LLMExtractionResult(
            "",
            "connect",
            int((time.monotonic() - started) * 1000),
            truncated_input=truncated,
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    raw_response_text = _clip_debug_text(resp.text)

    if resp.status_code in (401, 403):
        return LLMExtractionResult(
            "",
            "auth",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
            truncated_input=truncated,
        )
    if resp.status_code >= 400:
        return LLMExtractionResult(
            "",
            "response_shape",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
            truncated_input=truncated,
        )

    raw_message_content: str | None = None
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        text = _parse_content(content)
        raw_message_content = _clip_debug_text(text)
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("response"), str):
            return LLMExtractionResult(
                "",
                "response_shape",
                latency_ms,
                status_code=resp.status_code,
                raw_response_text=raw_response_text,
                raw_message_content=raw_message_content,
                truncated_input=truncated,
            )
    except (KeyError, IndexError, TypeError, ValueError):
        return LLMExtractionResult(
            "",
            "response_shape",
            latency_ms,
            status_code=resp.status_code,
            raw_response_text=raw_response_text,
            raw_message_content=raw_message_content,
            truncated_input=truncated,
        )

    return LLMExtractionResult(
        text=parsed["response"],
        error="truncated" if truncated else None,
        latency_ms=latency_ms,
        status_code=resp.status_code,
        raw_response_text=raw_response_text,
        raw_message_content=raw_message_content,
        truncated_input=truncated,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3.11 -m pytest tests/unit/test_web_response_llm_extractor.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Run fast suite to check no regressions**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/executors/web_response_llm_extractor.py \
        tests/unit/test_web_response_llm_extractor.py
git commit -m "feat: add web_response_llm_extractor module"
```

---

### Task 3: Integrate LLM extraction into `web_executor.py`

**Files:**
- Modify: `src/autoagent/executors/web_executor.py`
- Create: `tests/unit/test_web_executor_llm.py`

- [ ] **Step 1: Write failing unit test**

Create `tests/unit/test_web_executor_llm.py`:

```python
"""Unit test for web executor LLM integration (mocks Playwright page)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from autoagent.executors.web_response_llm_extractor import LLMExtractionResult


@pytest.mark.asyncio
async def test_capture_html_uses_selector_when_found():
    from autoagent.executors.web_executor import _capture_html

    page = AsyncMock()
    page.evaluate = AsyncMock(return_value="<div>hello</div>")
    result = await _capture_html(page, ".reply")
    assert result == "<div>hello</div>"
    page.evaluate.assert_called_once()
    # selector was passed as argument
    call_args = page.evaluate.call_args
    assert ".reply" in str(call_args)


@pytest.mark.asyncio
async def test_capture_html_falls_back_to_body_when_selector_missing():
    from autoagent.executors.web_executor import _capture_html

    page = AsyncMock()
    # First call (selector lookup) returns None, second call (body) returns full html
    page.evaluate = AsyncMock(side_effect=[None, "<body>full</body>"])
    result = await _capture_html(page, ".missing")
    assert result == "<body>full</body>"
    assert page.evaluate.call_count == 2


@pytest.mark.asyncio
async def test_capture_html_returns_empty_string_when_both_none():
    from autoagent.executors.web_executor import _capture_html

    page = AsyncMock()
    page.evaluate = AsyncMock(side_effect=[None, None])
    result = await _capture_html(page, ".missing")
    assert result == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3.11 -m pytest tests/unit/test_web_executor_llm.py -v
```

Expected: `ImportError: cannot import name '_capture_html' from 'autoagent.executors.web_executor'`

- [ ] **Step 3: Add `_capture_html` helper and integrate LLM extraction into `web_executor.py`**

**Add imports** at the top of `src/autoagent/executors/web_executor.py` (after existing imports):

```python
from autoagent.executors.web_response_llm_extractor import (
    LLMExtractionResult,
    extract_web_response_via_llm,
)
```

**Add `_capture_html` function** at the bottom of `src/autoagent/executors/web_executor.py` (before the existing `_send_button_selector` function):

```python
async def _capture_html(page: Any, selector: str) -> str:
    html = await page.evaluate(
        "(sel) => { const el = document.querySelector(sel); return el ? el.outerHTML : null; }",
        selector,
    )
    if html is None:
        html = await page.evaluate("() => document.body.outerHTML")
    return html or ""
```

**Integrate into the per-prompt loop** in `execute()`. Replace the block from `responses.append(text)` to the `done_` screenshot (lines ~176-177) with:

```python
                        responses.append(text)
                        if profile.llm_response_enabled():
                            try:
                                html = await _capture_html(
                                    page, profile.response_container_selector
                                )
                                llm_res = await extract_web_response_via_llm(
                                    prompt=prompt,
                                    html=html,
                                    base_url=profile.base_url,
                                    model=profile.model,
                                    api_key=profile.api_key,
                                )
                            except Exception:  # noqa: BLE001
                                llm_res = LLMExtractionResult(
                                    text="", error="connect", latency_ms=0
                                )
                            ctx.llm_responses.append(llm_res.text)
                            ctx.llm_errors.append(llm_res.error)
                            _log.debug(
                                "web sample %s prompt %s llm extraction: "
                                "error=%s latency_ms=%s text=%r",
                                sample.id,
                                idx,
                                llm_res.error,
                                llm_res.latency_ms,
                                llm_res.text,
                            )
                        await self._screenshot(page, store, f"done_{idx}", verbose=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3.11 -m pytest tests/unit/test_web_executor_llm.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Run full fast suite**

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

Expected: all tests pass (count increases by 3 + 4 from Tasks 1 and 2).

- [ ] **Step 6: Lint and format**

```bash
python3.11 -m ruff check src/autoagent/executors/web_executor.py \
    src/autoagent/executors/web_response_llm_extractor.py \
    src/autoagent/profiles/schemas.py
python3.11 -m ruff format src/autoagent/executors/web_executor.py \
    src/autoagent/executors/web_response_llm_extractor.py \
    src/autoagent/profiles/schemas.py
```

Expected: no errors. If ruff flags the bare `except Exception` as BLE001, the `# noqa: BLE001` comment already handles it.

- [ ] **Step 7: Commit**

```bash
git add src/autoagent/executors/web_executor.py \
        tests/unit/test_web_executor_llm.py
git commit -m "feat: integrate LLM extraction into web executor"
```

---

## Verification

After all tasks complete, run the full fast suite one final time:

```bash
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

Expected output: all tests pass. New test count should be at least 13 higher than baseline (4 schema + 6 extractor + 3 executor).

To manually verify end-to-end with a real web profile, add `base_url`, `model`, and `api_key` to any existing `.yaml` under `data/profiles/`, start the dev server, and run a batch — `llm_responses` will appear in the SampleDetail panel alongside rule-based responses.
