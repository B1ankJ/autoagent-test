# LLM Response Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, per-profile LLM extractor that reads each round's `after_result_<n>.xml` and produces the assistant's latest reply, running alongside (never replacing) the existing rule-based extractor. Every Android `SampleResult` carries two parallel response lists so users can compare.

**Architecture:** Credentials are stored **once** in the KV-backed `VLMConfig` (Config page) and are the **default source** only. The single source of truth **at runtime** is the profile YAML's new `base_url` / `model` / `api_key` triple; triple complete → LLM enabled for that profile. The Android executor appends to `ctx.llm_responses` / `ctx.llm_errors` after the rule extractor has produced its text; `Executor.run()` merges those into `SampleResult`. Profile Builder's existing draft enrichment (previously configured via `PROFILE_BUILDER_LLM_*` env) migrates to reading the same `VLMConfig`.

**Tech Stack:** Python 3.11 · FastAPI · Pydantic v2 · async SQLAlchemy · `httpx` (no `openai` SDK) · pytest-asyncio · React 18 + TanStack Query v5 + Ant Design.

**Spec reference:** `docs/superpowers/specs/2026-04-25-llm-response-extraction-design.md`.

**Prereq:** Plan 4 Android Executor code-complete on branch `plan4-android-executor`. Work happens on the same branch.

**Delivery:** ship at tag `llm-response-extraction-v0.5.0` after manual smoke succeeds.

---

## File Structure

```text
src/autoagent/
  models/
    api.py                          # MODIFY: VLMConfig.api_key_env → api_key;
                                    #         SampleResult +llm_responses +llm_errors
  profiles/
    schemas.py                      # MODIFY: AndroidProfile +base_url +model +api_key
                                    #         + llm_response_enabled()
  config/
    settings.py                     # MODIFY: remove profile_builder_llm_* fields
  executors/
    base.py                         # MODIFY: ExecutorContext +llm_responses +llm_errors
                                    #         Executor.run() copies them into SampleResult
    llm_checker.py                  # CREATE: check_llm_api() + CheckResult dataclass
    response_llm_extractor.py       # CREATE: extract_response_via_llm() + LLMExtractionResult
    profile_builder_generator.py    # MODIFY: read VLMConfig from KV instead of Settings
    android_executor.py             # MODIFY: per-round LLM extractor call after rule extractor
  api/
    config.py                       # MODIFY: POST /vlm/test; PUT /vlm strict validation
    profile_builder.py              # MODIFY: draft endpoint accepts inject_llm; copies triple
tests/
  unit/
    test_llm_checker.py             # CREATE
    test_response_llm_extractor.py  # CREATE
    test_profile_builder_generator.py  # MODIFY: reads KV not Settings
    test_android_profile_schema.py  # MODIFY or CREATE: llm_response_enabled branches
  integration/
    test_config_vlm_endpoints.py    # CREATE
    test_profile_builder_endpoints.py  # MODIFY: inject_llm branch
    test_android_executor_llm.py    # CREATE: both triples / missing triple via mock LLM
web/src/
  api/config.ts                     # MODIFY: useTestLLM() mutation
  pages/
    Config.tsx                      # MODIFY: test button + error rendering
    Profiles/Builder.tsx            # MODIFY: inject-llm checkbox + mutation param
    Batches/SampleDetail.tsx        # MODIFY: two-column response rendering
docs/
  superpowers/plans/
    2026-04-23-plan-4-android-manual-smoke.md   # MODIFY: add 6 smoke steps (§9 of spec)
CLAUDE.md                           # MODIFY: drop PROFILE_BUILDER_LLM_* mentions;
                                    #         note profile-YAML sensitivity;
                                    #         note runtime-creds-only-from-YAML
.env.example                        # MODIFY: remove PROFILE_BUILDER_LLM_* lines
```

---

## Task 1: `SampleResult` gains `llm_responses` and `llm_errors` (additive)

**Files:**
- Modify: `src/autoagent/models/api.py` (around line 36, `class SampleResult`)
- Test: `tests/unit/test_sample_result_llm_fields.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_sample_result_llm_fields.py
from autoagent.models.api import SampleResult


def test_sample_result_default_llm_fields_are_empty_lists():
    result = SampleResult(
        id="s1",
        status="done",
        prompts_sent=["hi"],
        responses=["hello"],
        duration_ms=1,
        attempt_count=1,
        mode="gui_android",
        target_profile="qwen_android",
    )
    assert result.llm_responses == []
    assert result.llm_errors == []


def test_sample_result_dumps_llm_fields_alongside_responses():
    result = SampleResult(
        id="s1",
        status="done",
        prompts_sent=["p1", "p2"],
        responses=["r1", "r2"],
        llm_responses=["lr1", ""],
        llm_errors=[None, "auth"],
        duration_ms=1,
        attempt_count=1,
        mode="gui_android",
        target_profile="qwen_android",
    )
    dumped = result.model_dump()
    assert dumped["llm_responses"] == ["lr1", ""]
    assert dumped["llm_errors"] == [None, "auth"]
```

- [ ] **Step 2: Run the test and verify it fails**

```
python3.11 -m pytest tests/unit/test_sample_result_llm_fields.py -v
```
Expected: both tests FAIL with `ValidationError` / `AttributeError` because `llm_responses` / `llm_errors` don't exist yet.

- [ ] **Step 3: Implement additive fields**

In `src/autoagent/models/api.py`, inside `class SampleResult(BaseModel):` add (right after `responses`):

```python
    llm_responses: list[str] = []
    llm_errors: list[str | None] = []
```

- [ ] **Step 4: Run the test and verify it passes**

```
python3.11 -m pytest tests/unit/test_sample_result_llm_fields.py -v
```
Expected: PASS 2/2.

- [ ] **Step 5: Run the rest of the suite fast-subset to confirm no regression**

```
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```
Expected: existing count passes. A few tests that build `SampleResult` literally won't care because fields default.

- [ ] **Step 6: Commit**

```
git add src/autoagent/models/api.py tests/unit/test_sample_result_llm_fields.py
git commit -m "feat(models): add llm_responses and llm_errors to SampleResult"
```

---

## Task 2: `ExecutorContext` gains parallel LLM lists; `Executor.run()` propagates them

**Files:**
- Modify: `src/autoagent/executors/base.py`
- Test: `tests/unit/test_executor_run_llm_propagation.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_executor_run_llm_propagation.py
import pytest

from autoagent.executors.base import Executor, ExecutorContext
from autoagent.models.api import Sample


class _StubExecutor(Executor):
    async def execute(self, sample, profile, ctx):
        ctx.llm_responses.append("L1")
        ctx.llm_errors.append(None)
        ctx.llm_responses.append("")
        ctx.llm_errors.append("auth")
        return ["R1", "R2"]


@pytest.mark.asyncio
async def test_run_copies_llm_fields_from_ctx_into_result():
    sample = Sample(id="s1", prompts=["p1", "p2"], mode="gui_android", target_profile="x")
    ctx = ExecutorContext()
    result = await _StubExecutor().run(sample, profile=None, default_timeout_sec=30, ctx=ctx)
    assert result.responses == ["R1", "R2"]
    assert result.llm_responses == ["L1", ""]
    assert result.llm_errors == [None, "auth"]


@pytest.mark.asyncio
async def test_run_default_llm_fields_are_empty_when_ctx_untouched():
    sample = Sample(id="s1", prompts=["p1"], mode="gui_android", target_profile="x")

    class _Legacy(Executor):
        async def execute(self, sample, profile, ctx):
            return ["R1"]

    result = await _Legacy().run(sample, profile=None, default_timeout_sec=30)
    assert result.llm_responses == []
    assert result.llm_errors == []
```

- [ ] **Step 2: Run the test and verify it fails**

```
python3.11 -m pytest tests/unit/test_executor_run_llm_propagation.py -v
```
Expected: FAIL (AttributeError on `ctx.llm_responses`).

- [ ] **Step 3: Extend `ExecutorContext` and `Executor.run()`**

In `src/autoagent/executors/base.py`, edit the dataclass:

```python
@dataclass
class ExecutorContext:
    logs_dir: str | None = None
    verbose_logs: bool = True
    api_timeout_sec: int = 60
    gui_timeout_sec: int = 180
    action_log: list[dict[str, Any]] = field(default_factory=list)
    action_replay_path: Path | None = None
    screenshot_index: list[Any] = field(default_factory=list)
    device_serial: str | None = None
    llm_responses: list[str] = field(default_factory=list)
    llm_errors: list[str | None] = field(default_factory=list)
```

In `Executor.run()`, change the final return (both normal-path and dry-run) to include:

```python
        return SampleResult(
            id=sample.id,
            status=status if status == "done" else ("timeout" if status == "timeout" else "failed"),
            prompts_sent=list(sample.prompts),
            responses=responses,
            llm_responses=list(ctx.llm_responses),
            llm_errors=list(ctx.llm_errors),
            duration_ms=int((time.monotonic() - t0) * 1000),
            attempt_count=attempts,
            mode=sample.mode,
            target_profile=sample.target_profile,
            metadata=_merge_ctx_metadata(sample, ctx),
            error=last_error,
            logs_dir=ctx.logs_dir,
            started_at=started,
            ended_at=datetime.now(timezone.utc),
        )
```

The dry-run branch keeps defaults (empty lists) — no change needed unless you want consistency; if so add `llm_responses=[], llm_errors=[]` explicitly.

- [ ] **Step 4: Run the test and verify it passes**

```
python3.11 -m pytest tests/unit/test_executor_run_llm_propagation.py -v
```
Expected: PASS 2/2.

- [ ] **Step 5: Fast suite regression check**

```
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```

- [ ] **Step 6: Commit**

```
git add src/autoagent/executors/base.py tests/unit/test_executor_run_llm_propagation.py
git commit -m "feat(executors): propagate llm_responses/llm_errors via ExecutorContext"
```

---

## Task 3: `AndroidProfile` gains `base_url` / `model` / `api_key` + `llm_response_enabled()`

**Files:**
- Modify: `src/autoagent/profiles/schemas.py` (around line 126)
- Test: `tests/unit/test_android_profile_schema.py` (modify if exists; else create)

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_android_profile_schema.py
from autoagent.profiles.schemas import AndroidProfile


_BASE = dict(
    name="qwen_android",
    platform="android",
    package="com.aliyun.tongyi",
    serial="ABC",
)


def test_android_profile_llm_disabled_by_default():
    p = AndroidProfile(**_BASE)
    assert p.base_url is None
    assert p.model is None
    assert p.api_key is None
    assert p.llm_response_enabled() is False


def test_android_profile_llm_enabled_when_triple_complete():
    p = AndroidProfile(
        **_BASE,
        base_url="https://example/v1",
        model="qwen-plus",
        api_key="sk-xxx",
    )
    assert p.llm_response_enabled() is True


def test_android_profile_llm_disabled_when_any_field_missing():
    for missing in ("base_url", "model", "api_key"):
        kwargs = {"base_url": "u", "model": "m", "api_key": "k"}
        kwargs[missing] = None
        p = AndroidProfile(**_BASE, **kwargs)
        assert p.llm_response_enabled() is False, f"{missing} missing should disable"
```

- [ ] **Step 2: Run the test and verify it fails**

```
python3.11 -m pytest tests/unit/test_android_profile_schema.py -v
```
Expected: FAIL (unknown kwargs / missing method).

- [ ] **Step 3: Extend `AndroidProfile`**

In `src/autoagent/profiles/schemas.py::AndroidProfile`, right after `serial: str` (before `input_method`), add:

```python
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
```

Add method at end of class:

```python
    def llm_response_enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)
```

- [ ] **Step 4: Run the test and verify it passes**

```
python3.11 -m pytest tests/unit/test_android_profile_schema.py -v
```
Expected: PASS 3/3.

- [ ] **Step 5: Confirm existing profile YAMLs still load**

```
python3.11 -m pytest tests/unit -q -k "profile"
```
Expected: previously-passing profile tests still pass (new fields are optional).

- [ ] **Step 6: Commit**

```
git add src/autoagent/profiles/schemas.py tests/unit/test_android_profile_schema.py
git commit -m "feat(profiles): add LLM triple + llm_response_enabled() to AndroidProfile"
```

---

## Task 4: `VLMConfig.api_key_env` → `api_key` (breaking rename)

**Files:**
- Modify: `src/autoagent/models/api.py` (around line 120, `class VLMConfig`)
- Modify: any caller references (grep first)
- Test: `tests/unit/test_vlm_config_api_key.py`

- [ ] **Step 1: Search for all references to `api_key_env`**

```
grep -rn "api_key_env" src tests web
```
Record every hit. Likely a small number: the Pydantic class itself, possibly the Config page frontend, possibly one integration test.

- [ ] **Step 2: Write failing test**

```python
# tests/unit/test_vlm_config_api_key.py
from autoagent.models.api import VLMConfig


def test_vlm_config_defaults_are_all_none():
    cfg = VLMConfig()
    assert cfg.base_url is None
    assert cfg.model is None
    assert cfg.api_key is None
    assert cfg.extra_headers == {}


def test_vlm_config_accepts_api_key_literal():
    cfg = VLMConfig(base_url="u", model="m", api_key="sk-xxx")
    assert cfg.api_key == "sk-xxx"


def test_vlm_config_rejects_old_api_key_env_field():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VLMConfig(base_url="u", model="m", api_key_env="SOME_ENV")
```

- [ ] **Step 3: Run the test and verify it fails**

```
python3.11 -m pytest tests/unit/test_vlm_config_api_key.py -v
```
Expected: FAIL (third test passes if current shape rejects extras; first two may pass or fail depending on current defaults).

- [ ] **Step 4: Rename the field**

In `src/autoagent/models/api.py::VLMConfig`:

```python
class VLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
```

(If `ConfigDict` / `Field` aren't already imported at the top of the file, add them from `pydantic`.)

- [ ] **Step 5: Update every other caller found in Step 1**

Typical places: any helper that previously dereferenced `cfg.api_key_env` (e.g. `os.environ[cfg.api_key_env]`) must now just use `cfg.api_key`. Apply those edits.

- [ ] **Step 6: Run the unit test and the fast suite**

```
python3.11 -m pytest tests/unit/test_vlm_config_api_key.py -v
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```
Expected: all green. Integration tests that previously hit `/config/vlm` may still pass because they only send `base_url` / `model`. If any fail, update to use the new field.

- [ ] **Step 7: Commit**

```
git add -A
git commit -m "refactor(models): rename VLMConfig.api_key_env to api_key (breaking)"
```

---

## Task 5: New module `executors/llm_checker.py`

**Files:**
- Create: `src/autoagent/executors/llm_checker.py`
- Test: `tests/unit/test_llm_checker.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_llm_checker.py
import httpx
import pytest

from autoagent.executors.llm_checker import CheckResult, check_llm_api


def _mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_check_llm_api_ok_200_with_valid_shape(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer sk-xyz"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hi"}}]},
        )

    async def _client_factory(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _client_factory)
    res = await check_llm_api("https://api/v1", "qwen-plus", "sk-xyz")
    assert res.ok is True
    assert res.stage == "ok"
    assert res.latency_ms >= 0


@pytest.mark.asyncio
async def test_check_llm_api_auth_failure(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _f)
    res = await check_llm_api("https://api/v1", "qwen-plus", "bad")
    assert res.ok is False
    assert res.stage == "auth"
    assert "invalid key" in res.message.lower() or "401" in res.message


@pytest.mark.asyncio
async def test_check_llm_api_model_not_found(monkeypatch):
    def handler(request):
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _f)
    res = await check_llm_api("https://api/v1", "zzz", "sk-xyz")
    assert res.ok is False
    assert res.stage == "model_not_found"


@pytest.mark.asyncio
async def test_check_llm_api_connect_failure(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _f)
    res = await check_llm_api("https://api/v1", "qwen-plus", "sk-xyz")
    assert res.ok is False
    assert res.stage == "connect"


@pytest.mark.asyncio
async def test_check_llm_api_response_shape(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": []})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock_transport(handler), timeout=timeout)

    monkeypatch.setattr("autoagent.executors.llm_checker._make_client", _f)
    res = await check_llm_api("https://api/v1", "qwen-plus", "sk-xyz")
    assert res.ok is False
    assert res.stage == "response_shape"


def test_check_result_dataclass_fields_exist():
    r = CheckResult(ok=True, stage="ok", message="ok", latency_ms=12)
    assert (r.ok, r.stage, r.message, r.latency_ms) == (True, "ok", "ok", 12)
```

- [ ] **Step 2: Run the test and verify it fails**

```
python3.11 -m pytest tests/unit/test_llm_checker.py -v
```
Expected: ImportError (module doesn't exist).

- [ ] **Step 3: Create `executors/llm_checker.py`**

```python
# src/autoagent/executors/llm_checker.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import httpx

Stage = Literal["connect", "auth", "model_not_found", "response_shape", "ok"]


@dataclass
class CheckResult:
    ok: bool
    stage: Stage
    message: str
    latency_ms: int


async def _make_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    # Indirection so tests can monkeypatch the transport.
    return httpx.AsyncClient(timeout=timeout)


def _error_message(body: object, fallback: str) -> str:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(err, str):
            return err
    return fallback


async def check_llm_api(
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
) -> CheckResult:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 5,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    timeout = httpx.Timeout(timeout_sec)
    started = time.monotonic()
    try:
        async with (await _make_client(timeout=timeout)) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        return CheckResult(
            ok=False,
            stage="connect",
            message=f"timeout: {exc}",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError as exc:
        return CheckResult(
            ok=False,
            stage="connect",
            message=str(exc) or exc.__class__.__name__,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        body = response.json()
    except ValueError:
        body = None

    if response.status_code == 401 or response.status_code == 403:
        return CheckResult(False, "auth", _error_message(body, f"http {response.status_code}"), latency_ms)
    if response.status_code == 404:
        return CheckResult(False, "model_not_found", _error_message(body, "model not found"), latency_ms)
    if response.status_code >= 400:
        return CheckResult(False, "response_shape", _error_message(body, f"http {response.status_code}"), latency_ms)

    if not isinstance(body, dict):
        return CheckResult(False, "response_shape", "non-json body", latency_ms)
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return CheckResult(False, "response_shape", "empty choices", latency_ms)
    first = choices[0]
    if not isinstance(first, dict) or "message" not in first:
        return CheckResult(False, "response_shape", "missing message", latency_ms)

    return CheckResult(True, "ok", "ok", latency_ms)
```

- [ ] **Step 4: Run the test and verify it passes**

```
python3.11 -m pytest tests/unit/test_llm_checker.py -v
```
Expected: PASS 6/6.

- [ ] **Step 5: Commit**

```
git add src/autoagent/executors/llm_checker.py tests/unit/test_llm_checker.py
git commit -m "feat(executors): add llm_checker with staged error mapping"
```

---

## Task 6: New module `executors/response_llm_extractor.py`

**Files:**
- Create: `src/autoagent/executors/response_llm_extractor.py`
- Test: `tests/unit/test_response_llm_extractor.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_response_llm_extractor.py
import httpx
import pytest

from autoagent.executors.response_llm_extractor import (
    LLMExtractionResult,
    extract_response_via_llm,
)


def _mock(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_extract_success(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"response": "你好，我是助手。"}'}}]},
        )

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == "你好，我是助手。"
    assert r.error is None
    assert r.latency_ms >= 0


@pytest.mark.asyncio
async def test_extract_empty_response_is_not_error(monkeypatch):
    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"response": ""}'}}]}
        )

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error is None


@pytest.mark.asyncio
async def test_extract_response_shape_failure(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="k"
    )
    assert r.text == ""
    assert r.error == "response_shape"


@pytest.mark.asyncio
async def test_extract_auth_failure(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    async def _f(*, timeout):
        return httpx.AsyncClient(transport=_mock(handler), timeout=timeout)

    monkeypatch.setattr(
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    r = await extract_response_via_llm(
        prompt="hi", xml="<root/>", base_url="https://api/v1", model="m", api_key="bad"
    )
    assert r.text == ""
    assert r.error == "auth"


@pytest.mark.asyncio
async def test_extract_truncates_oversized_xml(monkeypatch):
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
        "autoagent.executors.response_llm_extractor._make_client", _f
    )
    huge = "x" * 300_000
    r = await extract_response_via_llm(
        prompt="hi", xml=huge, base_url="https://api/v1", model="m", api_key="k",
        max_xml_chars=120_000,
    )
    assert r.text == "ok"
    assert r.error == "truncated"
    assert captured["len"] < 300_000 + 5000  # truncated, not full huge
```

- [ ] **Step 2: Run the test and verify it fails**

```
python3.11 -m pytest tests/unit/test_response_llm_extractor.py -v
```
Expected: ImportError.

- [ ] **Step 3: Create the module**

```python
# src/autoagent/executors/response_llm_extractor.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

_SYSTEM_PROMPT = (
    "你是一个 Android 聊天 App 响应抽取器。用户会给你：\n"
    "1) 本轮用户输入的 prompt 文本；\n"
    "2) 本轮执行结束时 App 的 UI 层级 XML（Android uiautomator dump 格式，"
    "只读，代表页面当前可见节点树）。\n\n"
    "你的唯一任务：从 XML 中定位助手（assistant/bot）对用户 prompt 的最新一条回复，"
    "把该回复的纯文本内容原样抽取出来。\n\n"
    "规则：\n"
    "- 只返回助手最新一条回复的文本，不要包含用户自己的 prompt、历史消息、"
    "UI 提示、按钮文案、占位符、输入建议、底部功能栏、Toast 等无关内容。\n"
    "- 多个 TextView 组成的同一条回复要按 XML 中出现顺序拼接成一段文本，"
    "段落之间用换行分隔。\n"
    "- 若 XML 中找不到可识别的助手回复，返回空字符串。\n"
    "- 不做改写、不做总结、不加前后缀、不输出解释。\n"
    "- 严格按给定 JSON schema 返回。"
)

_RESPONSE_SCHEMA = {
    "name": "android_response_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"response": {"type": "string"}},
        "required": ["response"],
    },
}


@dataclass
class LLMExtractionResult:
    text: str
    error: str | None
    latency_ms: int


async def _make_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


def _truncate_xml(xml: str, max_chars: int) -> tuple[str, bool]:
    if len(xml) <= max_chars:
        return xml, False
    part = max_chars // 3
    head = xml[:part]
    mid_start = (len(xml) - part) // 2
    middle = xml[mid_start : mid_start + part]
    tail = xml[-part:]
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


async def extract_response_via_llm(
    *,
    prompt: str,
    xml: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_sec: float = 30.0,
    max_xml_chars: int = 120_000,
) -> LLMExtractionResult:
    trimmed, truncated = _truncate_xml(xml, max_xml_chars)
    user_payload = {"prompt": prompt, "xml": trimmed}
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
        return LLMExtractionResult("", "timeout", int((time.monotonic() - started) * 1000))
    except httpx.HTTPError:
        return LLMExtractionResult("", "connect", int((time.monotonic() - started) * 1000))

    latency_ms = int((time.monotonic() - started) * 1000)

    if resp.status_code in (401, 403):
        return LLMExtractionResult("", "auth", latency_ms)
    if resp.status_code >= 400:
        return LLMExtractionResult("", "response_shape", latency_ms)

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        text = _parse_content(content)
        parsed = json.loads(text)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("response"), str):
            return LLMExtractionResult("", "response_shape", latency_ms)
    except (KeyError, IndexError, TypeError, ValueError):
        return LLMExtractionResult("", "response_shape", latency_ms)

    return LLMExtractionResult(
        text=parsed["response"],
        error="truncated" if truncated else None,
        latency_ms=latency_ms,
    )
```

- [ ] **Step 4: Run the test and verify it passes**

```
python3.11 -m pytest tests/unit/test_response_llm_extractor.py -v
```
Expected: PASS 5/5.

- [ ] **Step 5: Commit**

```
git add src/autoagent/executors/response_llm_extractor.py tests/unit/test_response_llm_extractor.py
git commit -m "feat(executors): add response_llm_extractor with json_schema output"
```

---

## Task 7: Profile Builder draft enrichment reads `VLMConfig` from KV

**Files:**
- Modify: `src/autoagent/executors/profile_builder_generator.py`
- Modify: `src/autoagent/api/profile_builder.py` (the call site of `maybe_generate_llm_draft`)
- Modify: `tests/unit/test_profile_builder_generator.py`

- [ ] **Step 1: Read current call site**

Open `src/autoagent/api/profile_builder.py` and locate the `maybe_generate_llm_draft(...)` call inside `generate_draft()`. Note what it currently passes (likely `settings=...`).

- [ ] **Step 2: Update unit tests first (TDD)**

Replace/augment the existing `test_profile_builder_generator.py` so tests pass a `VLMConfig` instead of mocking `Settings`:

```python
# tests/unit/test_profile_builder_generator.py
import pytest

from autoagent.executors.profile_builder_generator import (
    _has_llm_config,
    maybe_generate_llm_draft,
    merge_llm_draft,
)
from autoagent.models.api import VLMConfig


def test_has_llm_config_requires_triple():
    assert _has_llm_config(VLMConfig()) is False
    assert _has_llm_config(VLMConfig(base_url="u", model="m")) is False
    assert _has_llm_config(VLMConfig(base_url="u", model="m", api_key="k")) is True


def test_merge_llm_draft_none_returns_copy_of_rule_draft():
    base = {"package": "p", "activity": "a"}
    out = merge_llm_draft(base, None)
    assert out == base
    assert out is not base  # copied


def test_merge_llm_draft_overrides_only_non_empty_fields():
    base = {"package": "p", "activity": "a"}
    override = {"activity": "b", "extra": ""}
    out = merge_llm_draft(base, override)
    assert out == {"package": "p", "activity": "b"}


@pytest.mark.asyncio
async def test_maybe_generate_returns_none_when_vlm_incomplete():
    out = await maybe_generate_llm_draft(
        rule_draft={"package": "p"},
        candidates={},
        captures={},
        vlm=VLMConfig(base_url="u", model="m"),  # missing api_key
    )
    assert out is None
```

- [ ] **Step 3: Run the test and verify it fails**

```
python3.11 -m pytest tests/unit/test_profile_builder_generator.py -v
```
Expected: signature mismatch / unexpected kwarg.

- [ ] **Step 4: Refactor the generator module**

In `src/autoagent/executors/profile_builder_generator.py`:
- Remove the `from autoagent.config.settings import Settings, get_settings` import.
- Replace it with `from autoagent.models.api import VLMConfig`.
- Change `_has_llm_config` to `def _has_llm_config(vlm: VLMConfig) -> bool: return bool(vlm.base_url and vlm.model and vlm.api_key)`.
- Change `_request_llm_draft`'s first parameter from `settings: Settings` to `vlm: VLMConfig`; update field accesses: `settings.profile_builder_llm_model` → `vlm.model`, `settings.profile_builder_llm_api_key` → `vlm.api_key`, `settings.profile_builder_llm_base_url` → `vlm.base_url`, `settings.profile_builder_llm_timeout_sec` → a module-level constant `LLM_DRAFT_TIMEOUT_SEC = 30.0`.
- Change `maybe_generate_llm_draft`'s signature:

```python
async def maybe_generate_llm_draft(
    *,
    rule_draft: Mapping[str, Any],
    candidates: Mapping[str, Any],
    captures: Mapping[str, Any],
    vlm: VLMConfig | None = None,
) -> dict[str, Any] | None:
    if vlm is None or not _has_llm_config(vlm):
        return None
    try:
        return await _request_llm_draft(
            vlm=vlm,
            rule_draft=rule_draft,
            candidates=candidates,
            captures=captures,
        )
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return None
```

- [ ] **Step 5: Update the call site in `api/profile_builder.py`**

Before the `maybe_generate_llm_draft(...)` call, load the current VLMConfig from KV:

```python
from autoagent.models.api import VLMConfig
from autoagent.storage.configs import get_config

...

async def generate_draft(...):
    ...
    raw = await get_config(session_db, "vlm")
    vlm = VLMConfig.model_validate(raw) if raw else VLMConfig()
    override = await maybe_generate_llm_draft(
        rule_draft=rule_draft,
        candidates=candidates,
        captures=captures,
        vlm=vlm,
    )
    ...
```

Consult the actual current function around `profile_builder.py:814–883`; match existing patterns (session argument naming, etc.).

- [ ] **Step 6: Run unit + integration tests**

```
python3.11 -m pytest tests/unit/test_profile_builder_generator.py -v
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -v
```
Expected: unit passes; integration keeps passing (no behavior change when VLMConfig is unset).

- [ ] **Step 7: Commit**

```
git add src/autoagent/executors/profile_builder_generator.py src/autoagent/api/profile_builder.py tests/unit/test_profile_builder_generator.py
git commit -m "refactor(profile_builder): read LLM creds from VLMConfig KV not Settings"
```

---

## Task 8: Remove `PROFILE_BUILDER_LLM_*` settings

**Files:**
- Modify: `src/autoagent/config/settings.py`
- Modify: `.env.example`
- Modify: `CLAUDE.md` (strip mentions — defer to Task 16 bulk update)

- [ ] **Step 1: Delete the four fields**

In `src/autoagent/config/settings.py` remove these lines:

```python
    profile_builder_llm_base_url: str | None = None
    profile_builder_llm_model: str | None = None
    profile_builder_llm_api_key: str | None = None
    profile_builder_llm_timeout_sec: float = 30.0
```

- [ ] **Step 2: Grep for stragglers**

```
grep -rn "profile_builder_llm_" src tests
```
Expected: no hits (Task 7 removed all usages). If any remain, fix them.

- [ ] **Step 3: Update `.env.example`**

Remove the `PROFILE_BUILDER_LLM_*` block.

- [ ] **Step 4: Run full fast suite**

```
python3.11 -m pytest -q -m "not playwright and not android and not slow"
```
Expected: all green.

- [ ] **Step 5: Commit**

```
git add src/autoagent/config/settings.py .env.example
git commit -m "chore(config): drop obsolete PROFILE_BUILDER_LLM_* settings"
```

---

## Task 9: `POST /api/v1/config/vlm/test` endpoint

**Files:**
- Modify: `src/autoagent/api/config.py`
- Test: `tests/integration/test_config_vlm_endpoints.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_config_vlm_endpoints.py
from unittest.mock import patch

import pytest

from autoagent.executors.llm_checker import CheckResult


@pytest.mark.asyncio
async def test_post_vlm_test_returns_ok(client_logged_in):
    fake = CheckResult(ok=True, stage="ok", message="ok", latency_ms=5)
    with patch(
        "autoagent.api.config.check_llm_api",
        return_value=fake,
    ) as m:
        r = await client_logged_in.post(
            "/api/v1/config/vlm/test",
            json={"base_url": "u", "model": "m", "api_key": "k"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["stage"] == "ok"
    m.assert_awaited_once_with("u", "m", "k")


@pytest.mark.asyncio
async def test_post_vlm_test_returns_failure_body_with_200(client_logged_in):
    fake = CheckResult(ok=False, stage="auth", message="bad key", latency_ms=7)
    with patch("autoagent.api.config.check_llm_api", return_value=fake):
        r = await client_logged_in.post(
            "/api/v1/config/vlm/test",
            json={"base_url": "u", "model": "m", "api_key": "k"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["stage"] == "auth"
    assert body["message"] == "bad key"


@pytest.mark.asyncio
async def test_post_vlm_test_requires_triple(client_logged_in):
    r = await client_logged_in.post(
        "/api/v1/config/vlm/test",
        json={"base_url": "u", "model": "m"},  # no api_key
    )
    assert r.status_code == 422
```

Reuse the `client_logged_in` fixture from the existing integration test suite; check how other config tests obtain it (likely via `conftest.py`).

- [ ] **Step 2: Run test and verify it fails**

```
python3.11 -m pytest tests/integration/test_config_vlm_endpoints.py -v
```
Expected: 404 Not Found / route missing.

- [ ] **Step 3: Add the endpoint**

In `src/autoagent/api/config.py`:

```python
from pydantic import BaseModel

from autoagent.executors.llm_checker import CheckResult, check_llm_api


class _LLMTestRequest(BaseModel):
    base_url: str
    model: str
    api_key: str


@router.post("/vlm/test")
async def test_vlm_connectivity(body: _LLMTestRequest) -> CheckResult:
    return await check_llm_api(body.base_url, body.model, body.api_key)
```

(Router prefix is already `/api/v1/config` — don't double-prefix.)

- [ ] **Step 4: Run the test and verify it passes**

```
python3.11 -m pytest tests/integration/test_config_vlm_endpoints.py -v
```
Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```
git add src/autoagent/api/config.py tests/integration/test_config_vlm_endpoints.py
git commit -m "feat(api): add POST /config/vlm/test connectivity endpoint"
```

---

## Task 10: `PUT /api/v1/config/vlm` enforces connectivity check

**Files:**
- Modify: `src/autoagent/api/config.py`
- Test: `tests/integration/test_config_vlm_endpoints.py` (append)

- [ ] **Step 1: Append failing tests**

```python
# tests/integration/test_config_vlm_endpoints.py (append)
@pytest.mark.asyncio
async def test_put_vlm_runs_check_and_saves_on_success(client_logged_in):
    fake = CheckResult(ok=True, stage="ok", message="ok", latency_ms=5)
    with patch("autoagent.api.config.check_llm_api", return_value=fake) as m:
        r = await client_logged_in.put(
            "/api/v1/config/vlm",
            json={"base_url": "u", "model": "m", "api_key": "k"},
        )
    assert r.status_code == 200
    m.assert_awaited_once()

    r2 = await client_logged_in.get("/api/v1/config/vlm")
    body = r2.json()
    assert body["base_url"] == "u"
    assert body["api_key"] == "k"


@pytest.mark.asyncio
async def test_put_vlm_rejects_on_check_failure(client_logged_in):
    fake = CheckResult(ok=False, stage="auth", message="bad", latency_ms=1)
    with patch("autoagent.api.config.check_llm_api", return_value=fake):
        r = await client_logged_in.put(
            "/api/v1/config/vlm",
            json={"base_url": "u", "model": "m", "api_key": "bad"},
        )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["ok"] is False
    assert body["detail"]["stage"] == "auth"


@pytest.mark.asyncio
async def test_put_vlm_empty_triple_skips_check_and_saves(client_logged_in):
    with patch("autoagent.api.config.check_llm_api") as m:
        r = await client_logged_in.put(
            "/api/v1/config/vlm",
            json={"base_url": None, "model": None, "api_key": None},
        )
    assert r.status_code == 200
    m.assert_not_called()
```

- [ ] **Step 2: Run the tests and verify they fail**

```
python3.11 -m pytest tests/integration/test_config_vlm_endpoints.py -v
```
Expected: two new ones fail (no check gate yet).

- [ ] **Step 3: Add the gate**

In the existing `PUT /vlm` handler in `src/autoagent/api/config.py` (it currently just writes KV), insert the check:

```python
from dataclasses import asdict

from fastapi import HTTPException

from autoagent.executors.llm_checker import check_llm_api


@router.put("/vlm")
async def put_vlm(cfg: VLMConfig, session: AsyncSession = Depends(get_session)) -> VLMConfig:
    if cfg.base_url and cfg.model and cfg.api_key:
        result = await check_llm_api(cfg.base_url, cfg.model, cfg.api_key)
        if not result.ok:
            raise HTTPException(status_code=400, detail=asdict(result))
    elif cfg.base_url or cfg.model or cfg.api_key:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "stage": "response_shape", "message": "triple must be all set or all empty", "latency_ms": 0},
        )
    await put_config(session, "vlm", cfg.model_dump())
    return cfg
```

Adjust to match the actual existing handler signature / import style in `config.py`.

- [ ] **Step 4: Run and verify**

```
python3.11 -m pytest tests/integration/test_config_vlm_endpoints.py -v
```
Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```
git add src/autoagent/api/config.py tests/integration/test_config_vlm_endpoints.py
git commit -m "feat(api): enforce check_llm_api on PUT /config/vlm"
```

---

## Task 11: Profile Builder `/draft` accepts `inject_llm` and copies the triple

**Files:**
- Modify: `src/autoagent/api/profile_builder.py` (around line 814)
- Test: extend `tests/integration/test_profile_builder_endpoints.py`

- [ ] **Step 1: Append failing tests**

```python
# tests/integration/test_profile_builder_endpoints.py (append)
@pytest.mark.asyncio
async def test_generate_draft_inject_llm_writes_triple_into_yaml(
    client_logged_in, tmp_path, session  # fixtures from existing suite
):
    # preseed VLM config
    await client_logged_in.put(
        "/api/v1/config/vlm",
        json={"base_url": "u", "model": "m", "api_key": "k"},
    )  # Patched check_llm_api in this test module's fixtures; or use patch() here
    session_id = ...  # create a builder session via existing fixture
    r = await client_logged_in.post(
        f"/api/v1/profile-builder/sessions/{session_id}/draft",
        json={"inject_llm": True},
    )
    assert r.status_code == 200
    draft_yaml = r.json()["yaml"]
    assert "base_url: u" in draft_yaml
    assert "model: m" in draft_yaml
    assert "api_key: k" in draft_yaml


@pytest.mark.asyncio
async def test_generate_draft_inject_llm_rejects_when_global_incomplete(
    client_logged_in, session_id
):
    # No VLM config saved.
    r = await client_logged_in.post(
        f"/api/v1/profile-builder/sessions/{session_id}/draft",
        json={"inject_llm": True},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "llm_config_incomplete"


@pytest.mark.asyncio
async def test_generate_draft_without_inject_llm_keeps_old_shape(
    client_logged_in, session_id
):
    r = await client_logged_in.post(
        f"/api/v1/profile-builder/sessions/{session_id}/draft",
        json={},
    )
    assert r.status_code == 200
    draft_yaml = r.json()["yaml"]
    assert "api_key" not in draft_yaml
```

Match the fixtures / path conventions already in `test_profile_builder_endpoints.py`.

- [ ] **Step 2: Run tests, verify they fail**

```
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -v
```
Expected: three new cases fail.

- [ ] **Step 3: Extend the draft endpoint**

In `src/autoagent/api/profile_builder.py::generate_draft`:

```python
from pydantic import BaseModel


class _GenerateDraftRequest(BaseModel):
    inject_llm: bool = False


@router.post("/sessions/{session_id}/draft")
async def generate_draft(
    session_id: str,
    body: _GenerateDraftRequest = _GenerateDraftRequest(),
    session: AsyncSession = Depends(get_session),
) -> dict:
    ...
    # existing rule + maybe_generate_llm_draft flow ...
    draft_dict = merge_llm_draft(rule_draft, llm_override)

    if body.inject_llm:
        raw = await get_config(session, "vlm")
        vlm = VLMConfig.model_validate(raw) if raw else VLMConfig()
        if not (vlm.base_url and vlm.model and vlm.api_key):
            raise HTTPException(
                status_code=400,
                detail={"error": "llm_config_incomplete"},
            )
        # Preserve YAML field order: insert right after `serial`.
        keys = list(draft_dict.keys())
        insert_after = keys.index("serial") + 1 if "serial" in keys else len(keys)
        items = list(draft_dict.items())
        new_items = (
            items[:insert_after]
            + [("base_url", vlm.base_url), ("model", vlm.model), ("api_key", vlm.api_key)]
            + items[insert_after:]
        )
        draft_dict = dict(new_items)

    # existing YAML serialization / persistence ...
```

Preserve existing dict-ordering behavior when serializing to YAML (ruamel/pyyaml with `sort_keys=False`).

- [ ] **Step 4: Run tests**

```
python3.11 -m pytest tests/integration/test_profile_builder_endpoints.py -v
```
Expected: full file green.

- [ ] **Step 5: Commit**

```
git add src/autoagent/api/profile_builder.py tests/integration/test_profile_builder_endpoints.py
git commit -m "feat(profile_builder): inject_llm copies VLMConfig triple into generated YAML"
```

---

## Task 12: Android executor calls LLM extractor per round

**Files:**
- Modify: `src/autoagent/executors/android_executor.py` (around line 230–290, the per-prompt loop)
- Test: `tests/integration/test_android_executor_llm.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/integration/test_android_executor_llm.py
from unittest.mock import AsyncMock, patch

import pytest

from autoagent.executors.base import ExecutorContext
from autoagent.executors.android_executor import AndroidExecutor
from autoagent.executors.response_llm_extractor import LLMExtractionResult
from autoagent.models.api import Sample
from autoagent.profiles.schemas import AndroidProfile


# Use a small smoke fixture that stubs out device IO — see existing android_executor tests
# (they already monkeypatch uiautomator2 / adb). Reuse the same stubbing pattern.


@pytest.mark.asyncio
async def test_android_executor_skips_llm_when_profile_disables(
    stubbed_android_env,  # provides stub device / stub xml producing rule_text="R1"
):
    profile = AndroidProfile(
        name="p", platform="android", package="pkg", serial="S",
        # no base_url/model/api_key
        **stubbed_android_env.extra_profile_fields,
    )
    sample = Sample(id="s1", prompts=["hi"], mode="gui_android", target_profile="p")
    ctx = ExecutorContext()
    with patch(
        "autoagent.executors.android_executor.extract_response_via_llm",
        new=AsyncMock(),
    ) as m:
        await AndroidExecutor().execute(sample, profile, ctx)
    m.assert_not_called()
    assert ctx.llm_responses == []
    assert ctx.llm_errors == []


@pytest.mark.asyncio
async def test_android_executor_calls_llm_per_round_when_profile_enables(
    stubbed_android_env,
):
    profile = AndroidProfile(
        name="p", platform="android", package="pkg", serial="S",
        base_url="u", model="m", api_key="k",
        **stubbed_android_env.extra_profile_fields,
    )
    sample = Sample(id="s1", prompts=["hi", "hello"], mode="gui_android", target_profile="p")
    ctx = ExecutorContext()
    fake = AsyncMock(side_effect=[
        LLMExtractionResult("LLM_A", None, 10),
        LLMExtractionResult("", "auth", 5),
    ])
    with patch(
        "autoagent.executors.android_executor.extract_response_via_llm",
        new=fake,
    ):
        await AndroidExecutor().execute(sample, profile, ctx)
    assert fake.await_count == 2
    assert ctx.llm_responses == ["LLM_A", ""]
    assert ctx.llm_errors == [None, "auth"]
```

If the existing test module uses a different stubbing helper, lift it; the point is:

1. two-prompt sample,
2. mock `extract_response_via_llm` with two return values,
3. verify call count and list contents.

- [ ] **Step 2: Run test, verify it fails**

```
python3.11 -m pytest tests/integration/test_android_executor_llm.py -v
```
Expected: FAIL — extractor not yet called.

- [ ] **Step 3: Wire the extractor into the per-prompt loop**

In `src/autoagent/executors/android_executor.py`:

Add import at the top:

```python
from autoagent.executors.response_llm_extractor import extract_response_via_llm
```

Right after the line `responses.append(...)` and after `after_result_xml_path.write_text(xml, ...)` are written (so `xml` is guaranteed populated for ui_tree methods), add:

```python
                    if profile.llm_response_enabled():
                        xml_for_llm = xml if xml is not None else ""
                        sample_log.info("llm_extract_start idx=%s model=%s", idx, profile.model)
                        llm_res = await extract_response_via_llm(
                            prompt=prompt,
                            xml=xml_for_llm,
                            base_url=profile.base_url,
                            model=profile.model,
                            api_key=profile.api_key,
                        )
                        sample_log.info(
                            "llm_extract_done idx=%s latency_ms=%s error=%s",
                            idx, llm_res.latency_ms, llm_res.error,
                        )
                        ctx.llm_responses.append(llm_res.text)
                        ctx.llm_errors.append(llm_res.error)
```

Important: this block runs exactly **once per prompt**, unconditionally after the three `if/elif/else` branches — so place it **outside** the extraction branches but **inside** the per-prompt loop, after `ctx.screenshot_index.append(...)`.

For the `ocr_only` method where `xml` is `None`, still call the LLM with an empty string; record `error="response_shape"` naturally if the model returns nothing useful. (Alternatively: skip LLM when `xml is None`. Keep current plan: call with `""` so behavior is uniform; users choosing `ocr_only` alongside LLM can switch to `ui_tree_then_ocr` for meaningful LLM input.)

- [ ] **Step 4: Run tests and verify they pass**

```
python3.11 -m pytest tests/integration/test_android_executor_llm.py -v
```
Expected: 2/2 PASS.

- [ ] **Step 5: Regression check — existing Android tests**

```
python3.11 -m pytest tests/integration -q -m "not playwright and not android and not slow"
```

- [ ] **Step 6: Commit**

```
git add src/autoagent/executors/android_executor.py tests/integration/test_android_executor_llm.py
git commit -m "feat(android_executor): per-round LLM response extraction via profile triple"
```

---

## Task 13: Config page frontend — test button + save error rendering

**Files:**
- Modify: `web/src/api/config.ts`
- Modify: `web/src/pages/Config.tsx`
- Test: `web/src/pages/__tests__/Config.test.tsx` (create or extend)

- [ ] **Step 1: Add API client hook**

In `web/src/api/config.ts`, add:

```ts
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "./client";

export interface LLMCheckResult {
  ok: boolean;
  stage: "connect" | "auth" | "model_not_found" | "response_shape" | "ok";
  message: string;
  latency_ms: number;
}

export function useTestLLM() {
  return useMutation({
    mutationFn: async (body: { base_url: string; model: string; api_key: string }) => {
      const { data } = await apiClient.post<LLMCheckResult>(
        "/api/v1/config/vlm/test",
        body,
      );
      return data;
    },
  });
}
```

- [ ] **Step 2: Write failing test**

```tsx
// web/src/pages/__tests__/Config.test.tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Config from "../Config";

vi.mock("../../api/config", async () => {
  const actual = await vi.importActual<any>("../../api/config");
  return {
    ...actual,
    useTestLLM: () => ({
      mutateAsync: vi.fn(async () => ({
        ok: false,
        stage: "auth",
        message: "bad key",
        latency_ms: 5,
      })),
      isPending: false,
    }),
  };
});

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient();
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("Config page", () => {
  it("shows auth error after test button click", async () => {
    wrap(<Config />);
    // fill inputs (use actual labels present in Config.tsx)
    fireEvent.change(screen.getByLabelText(/base.?url/i), { target: { value: "u" } });
    fireEvent.change(screen.getByLabelText(/model/i), { target: { value: "m" } });
    fireEvent.change(screen.getByLabelText(/api.?key/i), { target: { value: "k" } });
    fireEvent.click(screen.getByRole("button", { name: /测试连通性/ }));
    await waitFor(() =>
      expect(screen.getByText(/认证失败/)).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 3: Run test, verify it fails**

```
cd web && pnpm test -- Config
```
Expected: component doesn't render the button or the message yet.

- [ ] **Step 4: Add the button + error UI to `Config.tsx`**

Minimal additions (actual JSX keeps AntD form layout already in place):

```tsx
import { useTestLLM, LLMCheckResult } from "../api/config";

const STAGE_TEXT: Record<LLMCheckResult["stage"], string> = {
  connect: "无法连接到该地址",
  auth: "认证失败，检查 API key",
  model_not_found: "模型不存在",
  response_shape: "返回格式异常",
  ok: "连通正常",
};

// inside component
const testLLM = useTestLLM();
const [llmTestMsg, setLlmTestMsg] = useState<string | null>(null);

async function handleTest() {
  setLlmTestMsg(null);
  const res = await testLLM.mutateAsync({
    base_url: baseUrl, model, api_key: apiKey,
  });
  const prefix = STAGE_TEXT[res.stage] ?? "未知错误";
  setLlmTestMsg(
    res.ok ? `${prefix}（${res.latency_ms} ms）` : `${prefix}：${res.message}`,
  );
}

// JSX near the VLM section
<Button onClick={handleTest} loading={testLLM.isPending}>
  测试连通性
</Button>
{llmTestMsg && (
  <Alert
    type={llmTestMsg.startsWith("连通正常") ? "success" : "error"}
    message={llmTestMsg}
    showIcon
    style={{ marginTop: 8 }}
  />
)}
```

Also update the save error path: catch `PUT /vlm` 400 and render using the same `STAGE_TEXT` map (the error body shape matches `LLMCheckResult`).

- [ ] **Step 5: Run the frontend tests**

```
cd web && pnpm test -- Config
cd web && pnpm lint
cd web && pnpm build
```
Expected: test passes, lint clean, build succeeds.

- [ ] **Step 6: Commit**

```
git add web/src/api/config.ts web/src/pages/Config.tsx web/src/pages/__tests__/Config.test.tsx
git commit -m "feat(web): Config page LLM connectivity test button + error stages"
```

---

## Task 14: Profile Builder frontend — LLM inject toggle

**Files:**
- Modify: `web/src/api/profileBuilder.ts` (draft mutation passes `inject_llm`)
- Modify: `web/src/pages/Profiles/Builder.tsx`
- Test: `web/src/pages/Profiles/__tests__/Builder.test.tsx` (extend or create)

- [ ] **Step 1: Update API hook**

Find the existing `useGenerateDraft` hook in `web/src/api/profileBuilder.ts`. Extend its body to accept `{ sessionId, injectLlm }` and POST `{inject_llm: injectLlm}` as the body.

```ts
export function useGenerateDraft() {
  return useMutation({
    mutationFn: async (args: { sessionId: string; injectLlm?: boolean }) => {
      const { data } = await apiClient.post(
        `/api/v1/profile-builder/sessions/${args.sessionId}/draft`,
        { inject_llm: !!args.injectLlm },
      );
      return data;
    },
  });
}
```

Update every existing caller accordingly (pass `{ sessionId }` or `{ sessionId, injectLlm }`).

- [ ] **Step 2: Write failing test**

```tsx
// web/src/pages/Profiles/__tests__/Builder.test.tsx
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Builder from "../Builder";

const mutateAsync = vi.fn(async () => ({ yaml: "name: ..." }));

vi.mock("../../../api/profileBuilder", () => ({
  useGenerateDraft: () => ({ mutateAsync, isPending: false }),
  useSession: () => ({ data: { id: "sess-1", captures: { idle: true, editing: true } } }),
}));

vi.mock("../../../api/config", () => ({
  useVLM: () => ({ data: { base_url: "u", model: "m", api_key: "k" } }),
}));

function wrap(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

describe("Builder inject_llm toggle", () => {
  it("passes inject_llm=true when checked", async () => {
    wrap(<Builder />);
    fireEvent.click(screen.getByLabelText(/注入 LLM/));
    fireEvent.click(screen.getByRole("button", { name: /Generate Draft/i }));
    expect(mutateAsync).toHaveBeenCalledWith({ sessionId: "sess-1", injectLlm: true });
  });

  it("disables the toggle when VLMConfig incomplete", () => {
    // override mock to return incomplete triple
    vi.doMock("../../../api/config", () => ({
      useVLM: () => ({ data: { base_url: "u", model: "m", api_key: null } }),
    }));
    wrap(<Builder />);
    expect(screen.getByLabelText(/注入 LLM/)).toBeDisabled();
  });
});
```

- [ ] **Step 3: Run, verify it fails**

```
cd web && pnpm test -- Builder
```

- [ ] **Step 4: Add toggle to the component**

In `web/src/pages/Profiles/Builder.tsx`, near the Generate Draft button:

```tsx
import { Checkbox, Tooltip } from "antd";
import { useVLM } from "../../api/config";

// inside component
const [injectLlm, setInjectLlm] = useState(false);
const { data: vlm } = useVLM();
const vlmReady = !!(vlm?.base_url && vlm?.model && vlm?.api_key);
const disabled = !vlmReady;

<Tooltip title={disabled ? "先在 Config 页面配置并通过连通性测试后才能启用" : ""}>
  <Checkbox
    checked={injectLlm}
    disabled={disabled}
    onChange={(e) => setInjectLlm(e.target.checked)}
    aria-label="注入 LLM 响应抽取配置"
  >
    生成时注入 LLM 响应抽取配置
  </Checkbox>
</Tooltip>

// Generate Draft click handler change
await generateDraft.mutateAsync({ sessionId: session.id, injectLlm });
```

- [ ] **Step 5: Run tests**

```
cd web && pnpm test -- Builder
cd web && pnpm lint
cd web && pnpm build
```

- [ ] **Step 6: Commit**

```
git add web/src/api/profileBuilder.ts web/src/pages/Profiles/Builder.tsx web/src/pages/Profiles/__tests__/Builder.test.tsx
git commit -m "feat(web): Profile Builder inject_llm toggle + wiring"
```

---

## Task 15: SampleDetail two-column response rendering

**Files:**
- Modify: `web/src/pages/Batches/SampleDetail.tsx`
- Test: `web/src/pages/Batches/__tests__/SampleDetail.test.tsx` (extend or create)

- [ ] **Step 1: Write failing test**

```tsx
// web/src/pages/Batches/__tests__/SampleDetail.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SampleDetail from "../SampleDetail";

vi.mock("../../../api/batches", () => ({
  useSample: () => ({
    data: {
      id: "s1",
      prompts_sent: ["hi", "hello"],
      responses: ["r1", "r2"],
      llm_responses: ["lr1", ""],
      llm_errors: [null, "auth"],
    },
  }),
}));

function wrap(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);
}

describe("SampleDetail two-column responses", () => {
  it("renders rule and llm columns with per-round alignment", () => {
    wrap(<SampleDetail />);
    expect(screen.getByText("r1")).toBeInTheDocument();
    expect(screen.getByText("lr1")).toBeInTheDocument();
    // Second round: llm text empty + error stage shown
    expect(screen.getByText("r2")).toBeInTheDocument();
    expect(screen.getByText(/auth/i)).toBeInTheDocument();
  });

  it("falls back to single column when llm_responses empty", () => {
    // remock with llm_responses: []
    vi.doMock("../../../api/batches", () => ({
      useSample: () => ({
        data: {
          id: "s1",
          prompts_sent: ["hi"],
          responses: ["r1"],
          llm_responses: [],
          llm_errors: [],
        },
      }),
    }));
    wrap(<SampleDetail />);
    expect(screen.queryByText(/LLM 抽取/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, verify it fails**

```
cd web && pnpm test -- SampleDetail
```

- [ ] **Step 3: Update the component**

In `SampleDetail.tsx`, replace the single response list with a two-column render. Sketch:

```tsx
const rows = sample.prompts_sent.map((p, i) => ({
  prompt: p,
  rule: sample.responses[i] ?? "",
  llm: sample.llm_responses[i] ?? "",
  err: sample.llm_errors[i] ?? null,
}));

const hasLLM = sample.llm_responses.length > 0;

return (
  <Table
    dataSource={rows}
    rowKey={(_, i) => String(i)}
    pagination={false}
    columns={[
      { title: "用户输入", dataIndex: "prompt" },
      { title: "规则抽取", dataIndex: "rule" },
      ...(hasLLM
        ? [
            {
              title: "LLM 抽取",
              dataIndex: "llm",
              render: (_: string, row: any) => (
                <div>
                  <div>{row.llm}</div>
                  {row.err && (
                    <div style={{ color: "#999", fontSize: 12 }}>错误：{row.err}</div>
                  )}
                </div>
              ),
            },
          ]
        : []),
    ]}
  />
);
```

Match the existing file's component library (AntD `Table` or `List`) — adapt column types accordingly. Keep pre-existing non-response UI untouched.

- [ ] **Step 4: Run tests and build**

```
cd web && pnpm test -- SampleDetail
cd web && pnpm lint
cd web && pnpm build
```

- [ ] **Step 5: Commit**

```
git add web/src/pages/Batches/SampleDetail.tsx web/src/pages/Batches/__tests__/SampleDetail.test.tsx
git commit -m "feat(web): SampleDetail two-column rule vs LLM response view"
```

---

## Task 16: Docs, CLAUDE.md, smoke plan, release tag

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md`

- [ ] **Step 1: Update CLAUDE.md**

Under "Conventions", remove any mentions of `PROFILE_BUILDER_LLM_*` env vars. Add:

```md
- **Profile LLM credentials:** Android profile YAMLs may now contain plaintext `base_url`, `model`, `api_key` for LLM response extraction. Treat `data/profiles/*.yaml` as sensitive: no public git, no unencrypted backups, include in Plan 5 `SecretStr` migration scope.
- **Runtime LLM creds:** Runtime LLM response extraction reads credentials from the profile YAML only. Global `VLMConfig` (Config page) is the default source for Profile Builder draft enrichment and "inject LLM into generated YAML", not for runtime.
- **LLM connectivity test:** `POST /api/v1/config/vlm/test` mirrors `PUT /api/v1/config/vlm` validation. `PUT` refuses to save non-empty but incomplete triples.
```

Under "When starting a new task", add a pointer to the new spec: `docs/superpowers/specs/2026-04-25-llm-response-extraction-design.md`.

Under "Development status", flip Plan 4 status note to include this feature, e.g. append:

```md
- LLM response extraction shipped at tag `llm-response-extraction-v0.5.0` (2026-04-25). Android runtime emits `SampleResult.llm_responses` / `llm_errors` alongside the rule-based `responses`.
```

(Only add this line after the smoke steps in Step 2 are green and tag is pushed.)

- [ ] **Step 2: Extend the Android manual smoke plan**

Append to `docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md`:

```md
## LLM response extraction smoke (2026-04-25)

1. Unconfigured baseline: remove VLM config; run a small Android batch. Expected: JSONL rows contain `"llm_responses": []`, `"llm_errors": []`.
2. Bad key rejection: set `api_key` to an invalid value in Config page; click 测试连通性. Expected: stage=auth message surfaced. Save is also rejected.
3. Good key acceptance: set valid triple; 测试连通性 returns 连通正常; Save succeeds.
4. Builder inject: in Profile Builder, check 生成时注入 LLM 响应抽取配置, Generate Draft, confirm the saved YAML contains `base_url`/`model`/`api_key` directly after `serial`.
5. End-to-end success: run a batch with that YAML. SampleDetail shows two columns; `responses` and `llm_responses` both populated.
6. Graceful failure: edit the YAML to change `api_key` to garbage; rerun. Sample status is still `done`; `llm_responses[i]=""`, `llm_errors[i]="auth"`; SampleDetail shows an auth error under the LLM column.
```

- [ ] **Step 3: Run full suite outside sandbox (Playwright + Android markers skipped for CI subset)**

```
python3.11 -m pytest -q -m "not playwright and not android and not slow"
cd web && pnpm test && pnpm lint && pnpm build
```
Expected: all green.

- [ ] **Step 4: Execute the smoke steps above on a real Android device**

Record outcomes in the smoke doc under a new "Result" block, matching the style of prior smoke runs.

- [ ] **Step 5: Commit docs + tag release**

```
git add CLAUDE.md docs/superpowers/plans/2026-04-23-plan-4-android-manual-smoke.md
git commit -m "docs: record LLM response extraction feature + smoke results"
git tag llm-response-extraction-v0.5.0
git log --oneline -10
```

(Do NOT `git push --tags` without user confirmation; per repo conventions pushing requires explicit user approval.)

---

## Self-Review Notes

- Spec §2 (credential model): covered by Tasks 1–4, 7, 8.
- Spec §3 (Config page): Tasks 5, 9, 10, 13.
- Spec §4 (Profile Builder inject): Tasks 11, 14.
- Spec §5 (runtime extraction): Tasks 6, 12.
- Spec §6 (prompt & schema): Task 6.
- Spec §7 (result model & UI): Tasks 1, 2, 15.
- Spec §8 (removal list): Task 8.
- Spec §9 (testing): unit + integration embedded in each task; end-to-end smoke in Task 16.
- Spec §10 (non-goals): not implemented (explicit non-goals).
- Spec §11 (CLAUDE.md): Task 16.

Type consistency checklist confirmed: `LLMExtractionResult`, `CheckResult`, `Stage` literals, `VLMConfig`, `AndroidProfile.llm_response_enabled()`, `ExecutorContext.llm_responses` / `llm_errors`, `SampleResult.llm_responses` / `llm_errors` — all referenced names match across tasks.
