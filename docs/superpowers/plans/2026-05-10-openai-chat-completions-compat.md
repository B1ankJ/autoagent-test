# OpenAI Chat Completions Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-streaming `POST /v1/chat/completions` endpoint that lets OpenAI-compatible clients trigger the existing single sync test flow with JWT auth and AutoAgent extension fields.

**Architecture:** Keep execution on the existing sync test pipeline. Add a small compatibility layer that validates an OpenAI-shaped request, resolves `model -> target_profile`, derives internal `mode` from the profile platform, builds a `Sample`, executes it through a shared sync-test helper, and maps the `SampleResult` back into an OpenAI-style `chat.completion` response with an `x_autoagent` extension payload.

**Tech Stack:** FastAPI, Pydantic v2, existing JWT auth (`decode_token`), existing scheduler-backed sync test flow, pytest, pytest-httpx, ruff.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/autoagent/services/__init__.py` | Create | Service package marker |
| `src/autoagent/services/sync_tests.py` | Create | Shared sync test helper reused by internal and OpenAI routes |
| `src/autoagent/api/tests.py` | Modify | Delegate existing `/api/v1/tests/sync` behavior to shared helper |
| `tests/unit/test_sync_tests_service.py` | Create | Unit coverage for shared sync helper |
| `src/autoagent/openai_compat/__init__.py` | Create | Compatibility package marker |
| `src/autoagent/openai_compat/schemas.py` | Create | OpenAI compatibility request/response models |
| `src/autoagent/openai_compat/chat_completions.py` | Create | Request validation, profile resolution, `Sample` mapping, result selection, error rendering |
| `tests/unit/test_openai_compat.py` | Create | Unit coverage for mapping, validation, response selection, error payloads |
| `src/autoagent/api/openai_compat.py` | Create | `POST /v1/chat/completions` route with JWT bearer handling and JSON responses |
| `src/autoagent/main.py` | Modify | Mount the OpenAI compatibility router |
| `tests/integration/test_openai_chat_completions.py` | Create | Integration coverage for success, auth failure, unsupported parameters, mapping, LLM fallback/preference |
| `README.md` | Modify | Document the new compatibility endpoint and Python SDK usage |

---

### Task 1: Shared Sync Test Helper

**Files:**
- Create: `src/autoagent/services/__init__.py`
- Create: `src/autoagent/services/sync_tests.py`
- Modify: `src/autoagent/api/tests.py`
- Test: `tests/unit/test_sync_tests_service.py`

- [ ] **Step 1: Write the failing unit test for the shared helper**

```python
# tests/unit/test_sync_tests_service.py
from __future__ import annotations

import pytest
from fastapi import HTTPException

from autoagent.models.api import Sample, SampleResult
from autoagent.services import sync_tests as mod


@pytest.mark.asyncio
async def test_execute_sync_sample_uses_gui_android_wait_timeout(monkeypatch):
    captured: dict[str, object] = {}

    class Scheduler:
        async def submit(self, **kwargs):
            captured.update(kwargs)
            return "b1"

        async def wait_done(self, batch_id, timeout_sec):
            captured["batch_id"] = batch_id
            captured["timeout_sec"] = timeout_sec

    async def fake_list(_batch_id: str):
        return [
            SampleResult(
                id="s1",
                status="done",
                prompts_sent=["hi"],
                responses=["echo: hi"],
                mode="gui_android",
                target_profile="android_profile",
            )
        ]

    monkeypatch.setattr(mod, "get_scheduler", lambda: Scheduler())
    monkeypatch.setattr(mod, "list_samples_for_batch", fake_list)

    sample = Sample(
        id="s1",
        prompts=["hi"],
        mode="gui_android",
        target_profile="android_profile",
    )

    result = await mod.execute_sync_sample(sample)

    assert result.status == "done"
    assert captured["timeout_sec"] == 210


@pytest.mark.asyncio
async def test_execute_sync_sample_raises_when_no_result_recorded(monkeypatch):
    class Scheduler:
        async def submit(self, **kwargs):
            return "b2"

        async def wait_done(self, batch_id, timeout_sec):
            return None

    async def fake_list(_batch_id: str):
        return []

    monkeypatch.setattr(mod, "get_scheduler", lambda: Scheduler())
    monkeypatch.setattr(mod, "list_samples_for_batch", fake_list)

    sample = Sample(id="s2", prompts=["yo"], mode="api", target_profile="p_api")

    with pytest.raises(HTTPException) as exc:
        await mod.execute_sync_sample(sample)

    assert exc.value.status_code == 500
    assert exc.value.detail == "no result recorded"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.11 -m pytest tests/unit/test_sync_tests_service.py -v`

Expected: FAIL because `autoagent.services.sync_tests` does not exist yet.

- [ ] **Step 3: Create the shared helper package and helper module**

```python
# src/autoagent/services/__init__.py
"""Small reusable backend services."""
```

```python
# src/autoagent/services/sync_tests.py
from __future__ import annotations

from fastapi import HTTPException

from autoagent.api._deps import get_scheduler
from autoagent.models.api import Sample, SampleResult
from autoagent.storage.samples import list_samples_for_batch


async def execute_sync_sample(sample: Sample) -> SampleResult:
    scheduler = get_scheduler()
    batch_id = await scheduler.submit(
        name=f"sync-{sample.id}",
        mode=sample.mode,
        concurrency=1,
        samples=[sample],
    )
    wait_timeout = sample.timeout_sec or (180 if sample.mode == "gui_android" else 600)
    await scheduler.wait_done(batch_id, timeout_sec=wait_timeout + 30)
    results = await list_samples_for_batch(batch_id)
    if not results:
        raise HTTPException(status_code=500, detail="no result recorded")
    return results[0]
```

- [ ] **Step 4: Update the existing tests router to delegate to the shared helper**

```python
# src/autoagent/api/tests.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from autoagent.auth.deps import require_user
from autoagent.models.api import AsyncTestResponse, Sample, SampleResult
from autoagent.services.sync_tests import execute_sync_sample
from autoagent.storage.samples import list_samples_for_batch
from autoagent.api._deps import get_scheduler

router = APIRouter(prefix="/tests", tags=["tests"], dependencies=[Depends(require_user)])


async def execute_sync_test(sample: Sample) -> SampleResult:
    return await execute_sync_sample(sample)


@router.post("/sync", response_model=SampleResult)
async def run_sync(sample: Sample) -> SampleResult:
    return await execute_sync_test(sample)
```

- [ ] **Step 5: Run the shared-helper tests and the existing sync-endpoint regression tests**

Run: `python3.11 -m pytest tests/unit/test_sync_tests_service.py tests/integration/test_tests_endpoints.py tests/integration/test_tests_sync_android.py -q`

Expected: PASS. Existing `/api/v1/tests/sync` behavior should still match the pre-refactor contract.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/services/__init__.py src/autoagent/services/sync_tests.py src/autoagent/api/tests.py tests/unit/test_sync_tests_service.py
git commit -m "refactor: extract shared sync test helper"
```

---

### Task 2: OpenAI Compatibility Models And Mapping Logic

**Files:**
- Create: `src/autoagent/openai_compat/__init__.py`
- Create: `src/autoagent/openai_compat/schemas.py`
- Create: `src/autoagent/openai_compat/chat_completions.py`
- Test: `tests/unit/test_openai_compat.py`

- [ ] **Step 1: Write the failing unit tests for request validation, mode mapping, response selection, and error payloads**

```python
# tests/unit/test_openai_compat.py
from __future__ import annotations

import pytest

from autoagent.models.api import SampleResult
from autoagent.openai_compat.chat_completions import (
    OpenAICompatError,
    build_chat_completion_response,
    build_sample_from_request,
    ensure_supported_request,
    mode_for_profile,
    select_message_content,
)
from autoagent.openai_compat.schemas import ChatCompletionsRequest
from autoagent.profiles.schemas import ApiProfile, WebProfile


def _api_profile() -> ApiProfile:
    return ApiProfile.model_validate(
        {
            "name": "p_api",
            "platform": "api",
            "api": {
                "base_url": "https://api.example.com/v1",
                "model": "m",
                "api_key": "OPENAI_TEST_KEY",
            },
        }
    )


def _web_profile_with_llm() -> WebProfile:
    return WebProfile.model_validate(
        {
            "name": "p_web",
            "platform": "web",
            "url": "file:///tmp/fake.html",
            "ready_check": {"type": "dom_selector", "selector": "#input"},
            "recovery_path": [],
            "input_selector": "#input",
            "send_method": {"type": "keyboard"},
            "response_container_selector": "#responses",
            "complete_detection": {"type": "dom_stable"},
            "base_url": "https://llm.example.com/v1",
            "model": "vlm",
            "api_key": "secret",
        }
    )


def test_request_rejects_stream_true():
    body = ChatCompletionsRequest.model_validate(
        {
            "model": "p_api",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }
    )

    with pytest.raises(OpenAICompatError) as exc:
        ensure_supported_request(body)

    assert exc.value.status_code == 400
    assert exc.value.param == "stream"


def test_build_sample_uses_last_user_message():
    body = ChatCompletionsRequest.model_validate(
        {
            "model": "p_api",
            "messages": [
                {"role": "system", "content": "ignore"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "also ignore"},
                {"role": "user", "content": "last"},
            ],
            "new_session": True,
            "timeout_sec": 123,
            "retry": 1,
            "dry_run": True,
            "metadata": {"tag": "sdk"},
        }
    )

    sample = build_sample_from_request(body, _api_profile())

    assert sample.prompts == ["last"]
    assert sample.target_profile == "p_api"
    assert sample.mode == "api"
    assert sample.new_session is True
    assert sample.timeout_sec == 123
    assert sample.retry == 1
    assert sample.dry_run is True
    assert sample.metadata == {"tag": "sdk"}


def test_mode_for_profile_maps_web_to_gui_pc_web():
    assert mode_for_profile(_web_profile_with_llm()) == "gui_pc_web"


def test_select_message_content_prefers_successful_llm_result():
    result = SampleResult(
        id="s1",
        status="done",
        prompts_sent=["hi"],
        responses=["static result"],
        llm_responses=["llm result"],
        llm_errors=[None],
        mode="gui_pc_web",
        target_profile="p_web",
    )

    assert select_message_content(result, _web_profile_with_llm()) == "llm result"


def test_select_message_content_falls_back_when_llm_failed():
    result = SampleResult(
        id="s2",
        status="done",
        prompts_sent=["hi"],
        responses=["static result"],
        llm_responses=[""],
        llm_errors=["auth"],
        mode="gui_pc_web",
        target_profile="p_web",
    )

    assert select_message_content(result, _web_profile_with_llm()) == "static result"


def test_build_chat_completion_response_includes_x_autoagent():
    body = ChatCompletionsRequest.model_validate(
        {"model": "p_api", "messages": [{"role": "user", "content": "hi"}]}
    )
    result = SampleResult(
        id="s3",
        status="done",
        prompts_sent=["hi"],
        responses=["hello"],
        mode="api",
        target_profile="p_api",
    )

    response = build_chat_completion_response(body, result, _api_profile())

    assert response.choices[0].message.content == "hello"
    assert response.x_autoagent.sample_id == "s3"
    assert response.x_autoagent.responses == ["hello"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3.11 -m pytest tests/unit/test_openai_compat.py -v`

Expected: FAIL because the compatibility package does not exist yet.

- [ ] **Step 3: Create the compatibility package, schemas, and mapping helpers**

```python
# src/autoagent/openai_compat/__init__.py
"""OpenAI-compatible request/response adapters."""
```

```python
# src/autoagent/openai_compat/schemas.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class ChatCompletionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False
    new_session: bool = False
    timeout_sec: int | None = Field(default=None, gt=0)
    retry: int = Field(default=2, ge=0)
    dry_run: bool = False
    tools: Any | None = None
    tool_choice: Any | None = None
    functions: Any | None = None
    function_call: Any | None = None
    n: int = 1
    response_format: Any | None = None
    audio: Any | None = None
    modalities: Any | None = None
    parallel_tool_calls: bool | None = None


class ChatCompletionMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatCompletionMessage
    finish_reason: Literal["stop"] = "stop"


class AutoAgentPayload(BaseModel):
    sample_id: str
    status: str
    attempt_count: int
    duration_ms: int | None = None
    responses: list[str] = Field(default_factory=list)
    llm_responses: list[str] = Field(default_factory=list)
    llm_errors: list[str | None] = Field(default_factory=list)
    logs_dir: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    x_autoagent: AutoAgentPayload


class OpenAIError(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class OpenAIErrorResponse(BaseModel):
    error: OpenAIError
```

```python
# src/autoagent/openai_compat/chat_completions.py
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from autoagent.models.api import Sample, SampleResult
from autoagent.openai_compat.schemas import (
    AutoAgentPayload,
    ChatCompletionChoice,
    ChatCompletionMessage,
    ChatCompletionResponse,
    ChatCompletionsRequest,
    OpenAIError,
    OpenAIErrorResponse,
)
from autoagent.profiles.registry import load_profile
from autoagent.profiles.schemas import (
    AgentAndroidProfile,
    AgentPcProfile,
    AndroidProfile,
    ApiProfile,
    Profile,
    WebProfile,
)


@dataclass
class OpenAICompatError(Exception):
    status_code: int
    message: str
    error_type: str = "invalid_request_error"
    param: str | None = None
    code: str | None = None

    def to_response(self) -> OpenAIErrorResponse:
        return OpenAIErrorResponse(
            error=OpenAIError(
                message=self.message,
                type=self.error_type,
                param=self.param,
                code=self.code,
            )
        )


def ensure_supported_request(body: ChatCompletionsRequest) -> None:
    if body.stream:
        raise OpenAICompatError(
            status_code=400,
            message="stream=true is not supported",
            param="stream",
            code="unsupported_parameter",
        )
    if body.tools is not None:
        raise OpenAICompatError(400, "tools is not supported", param="tools", code="unsupported_parameter")
    if body.tool_choice is not None:
        raise OpenAICompatError(400, "tool_choice is not supported", param="tool_choice", code="unsupported_parameter")
    if body.functions is not None:
        raise OpenAICompatError(400, "functions is not supported", param="functions", code="unsupported_parameter")
    if body.function_call is not None:
        raise OpenAICompatError(400, "function_call is not supported", param="function_call", code="unsupported_parameter")
    if body.n != 1:
        raise OpenAICompatError(400, "only n=1 is supported", param="n", code="unsupported_parameter")
    if body.response_format is not None:
        raise OpenAICompatError(400, "response_format is not supported", param="response_format", code="unsupported_parameter")
    if body.audio is not None:
        raise OpenAICompatError(400, "audio is not supported", param="audio", code="unsupported_parameter")
    if body.modalities is not None:
        raise OpenAICompatError(400, "modalities is not supported", param="modalities", code="unsupported_parameter")
    if body.parallel_tool_calls is not None:
        raise OpenAICompatError(400, "parallel_tool_calls is not supported", param="parallel_tool_calls", code="unsupported_parameter")


def resolve_profile(name: str) -> Profile:
    profile = load_profile(name)
    if profile is None:
        raise OpenAICompatError(
            status_code=404,
            message=f"target profile {name!r} not found",
            param="model",
            code="not_found",
        )
    return profile


def mode_for_profile(profile: Profile) -> str:
    if isinstance(profile, ApiProfile):
        return "api"
    if isinstance(profile, WebProfile):
        return "gui_pc_web"
    if isinstance(profile, AndroidProfile):
        return "gui_android"
    if isinstance(profile, AgentPcProfile):
        return "agent_pc"
    if isinstance(profile, AgentAndroidProfile):
        return "agent_android"
    raise OpenAICompatError(status_code=400, message="unsupported profile platform", param="model")


def extract_last_user_text(body: ChatCompletionsRequest) -> str:
    for message in reversed(body.messages):
        if message.role == "user" and message.content.strip():
            return message.content
    raise OpenAICompatError(
        status_code=400,
        message="messages must include at least one non-empty user message",
        param="messages",
        code="invalid_messages",
    )


def build_sample_from_request(body: ChatCompletionsRequest, profile: Profile) -> Sample:
    return Sample(
        id=f"chatcmpl_{uuid.uuid4().hex[:12]}",
        prompts=[extract_last_user_text(body)],
        mode=mode_for_profile(profile),
        target_profile=body.model,
        new_session=body.new_session,
        timeout_sec=body.timeout_sec,
        retry=body.retry,
        dry_run=body.dry_run,
        metadata=dict(body.metadata),
    )


def select_message_content(result: SampleResult, profile: Profile) -> str:
    llm_enabled = bool(getattr(profile, "llm_response_enabled", lambda: False)())
    if llm_enabled and result.llm_responses:
        first_error = result.llm_errors[0] if result.llm_errors else None
        first_llm = result.llm_responses[0]
        if first_error is None and first_llm:
            return first_llm
    return result.responses[0] if result.responses else ""


def build_chat_completion_response(
    body: ChatCompletionsRequest,
    result: SampleResult,
    profile: Profile,
) -> ChatCompletionResponse:
    content = select_message_content(result, profile)
    return ChatCompletionResponse(
        id=f"chatcmpl_{result.id}",
        created=int(time.time()),
        model=body.model,
        choices=[
            ChatCompletionChoice(
                message=ChatCompletionMessage(content=content),
            )
        ],
        x_autoagent=AutoAgentPayload(
            sample_id=result.id,
            status=result.status,
            attempt_count=result.attempt_count,
            duration_ms=result.duration_ms,
            responses=list(result.responses),
            llm_responses=list(result.llm_responses),
            llm_errors=list(result.llm_errors),
            logs_dir=result.logs_dir,
            metadata=dict(result.metadata),
        ),
    )
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `python3.11 -m pytest tests/unit/test_openai_compat.py -q`

Expected: PASS. Request validation, mapping, and final-content selection all behave exactly like the design doc.

- [ ] **Step 5: Commit**

```bash
git add src/autoagent/openai_compat/__init__.py src/autoagent/openai_compat/schemas.py src/autoagent/openai_compat/chat_completions.py tests/unit/test_openai_compat.py
git commit -m "feat: add openai chat completions mapping layer"
```

---

### Task 3: OpenAI Compatibility Route And App Wiring

**Files:**
- Create: `src/autoagent/api/openai_compat.py`
- Modify: `src/autoagent/main.py`
- Test: `tests/integration/test_openai_chat_completions.py`

- [ ] **Step 1: Write the failing integration tests for success, auth failure, unsupported parameters, mapping, and LLM fallback/preference**

```python
# tests/integration/test_openai_chat_completions.py
from __future__ import annotations

import yaml
import pytest
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.auth.passwords import hash_password
from autoagent.models.api import SampleResult
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {response.json()['token']}"}


async def test_chat_completions_api_success(client: AsyncClient, httpx_mock: HTTPXMock) -> None:
    save_profile_yaml(
        "p_api",
        yaml.safe_dump(
            {
                "name": "p_api",
                "platform": "api",
                "api": {
                    "base_url": "https://api.example.com/v1",
                    "model": "m",
                    "api_key": "OPENAI_TEST_KEY",
                },
            }
        ),
    )
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "hi!"}}]},
    )
    headers = await _login(client)

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "p_api", "messages": [{"role": "user", "content": "hello"}]},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "hi!"
    assert body["x_autoagent"]["responses"] == ["hi!"]


async def test_chat_completions_returns_openai_shaped_401_without_token(client: AsyncClient) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "missing", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


async def test_chat_completions_rejects_stream_true(client: AsyncClient) -> None:
    headers = await _login(client)
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "p_api",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "stream"


async def test_chat_completions_maps_extensions_and_profile_mode(client: AsyncClient, monkeypatch) -> None:
    save_profile_yaml(
        "fake_site",
        yaml.safe_dump(
            {
                "name": "fake_site",
                "platform": "web",
                "url": "file:///tmp/fake.html",
                "ready_check": {"type": "dom_selector", "selector": "#input"},
                "recovery_path": [],
                "input_selector": "#input",
                "send_method": {"type": "keyboard"},
                "response_container_selector": "#responses",
                "complete_detection": {"type": "dom_stable"},
            }
        ),
    )

    captured: dict[str, object] = {}

    async def fake_execute(sample):
        captured["sample"] = sample
        return SampleResult(
            id=sample.id,
            status="done",
            prompts_sent=list(sample.prompts),
            responses=["ok"],
            mode=sample.mode,
            target_profile=sample.target_profile,
            metadata=dict(sample.metadata),
        )

    monkeypatch.setattr("autoagent.api.openai_compat.execute_sync_sample", fake_execute)
    headers = await _login(client)
    response = await client.post(
        "/v1/chat/completions",
        json={
            "model": "fake_site",
            "messages": [{"role": "user", "content": "hello"}],
            "new_session": True,
            "timeout_sec": 120,
            "retry": 1,
            "dry_run": True,
            "metadata": {"tag": "sdk"},
        },
        headers=headers,
    )

    sample = captured["sample"]
    assert response.status_code == 200
    assert sample.mode == "gui_pc_web"
    assert sample.new_session is True
    assert sample.timeout_sec == 120
    assert sample.retry == 1
    assert sample.dry_run is True
    assert sample.metadata == {"tag": "sdk"}


async def test_chat_completions_prefers_llm_response_and_falls_back_when_needed(
    client: AsyncClient,
    monkeypatch,
) -> None:
    save_profile_yaml(
        "web_llm",
        yaml.safe_dump(
            {
                "name": "web_llm",
                "platform": "web",
                "url": "file:///tmp/fake.html",
                "ready_check": {"type": "dom_selector", "selector": "#input"},
                "recovery_path": [],
                "input_selector": "#input",
                "send_method": {"type": "keyboard"},
                "response_container_selector": "#responses",
                "complete_detection": {"type": "dom_stable"},
                "base_url": "https://llm.example.com/v1",
                "model": "vlm",
                "api_key": "secret",
            }
        ),
    )
    headers = await _login(client)
    call_count = {"count": 0}

    async def fake_execute(sample):
        call_count["count"] += 1
        if call_count["count"] == 1:
            return SampleResult(
                id=sample.id,
                status="done",
                prompts_sent=list(sample.prompts),
                responses=["static one"],
                llm_responses=["llm one"],
                llm_errors=[None],
                mode=sample.mode,
                target_profile=sample.target_profile,
            )
        return SampleResult(
            id=sample.id,
            status="done",
            prompts_sent=list(sample.prompts),
            responses=["static two"],
            llm_responses=[""],
            llm_errors=["auth"],
            mode=sample.mode,
            target_profile=sample.target_profile,
        )

    monkeypatch.setattr("autoagent.api.openai_compat.execute_sync_sample", fake_execute)

    first = await client.post(
        "/v1/chat/completions",
        json={"model": "web_llm", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    second = await client.post(
        "/v1/chat/completions",
        json={"model": "web_llm", "messages": [{"role": "user", "content": "hi again"}]},
        headers=headers,
    )

    assert first.json()["choices"][0]["message"]["content"] == "llm one"
    assert second.json()["choices"][0]["message"]["content"] == "static two"
```

- [ ] **Step 2: Run the integration test to verify it fails**

Run: `python3.11 -m pytest tests/integration/test_openai_chat_completions.py -q`

Expected: FAIL because `/v1/chat/completions` is not mounted yet.

- [ ] **Step 3: Create the compatibility route with OpenAI-shaped auth errors and success/error JSON payloads**

```python
# src/autoagent/api/openai_compat.py
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from autoagent.auth.jwt import decode_token
from autoagent.openai_compat.chat_completions import (
    OpenAICompatError,
    build_chat_completion_response,
    build_sample_from_request,
    ensure_supported_request,
    resolve_profile,
)
from autoagent.openai_compat.schemas import ChatCompletionsRequest
from autoagent.services.sync_tests import execute_sync_sample

router = APIRouter(prefix="/v1", tags=["openai_compat"])


def _require_openai_bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise OpenAICompatError(
            status_code=401,
            message="Missing bearer token",
            error_type="invalid_request_error",
            code="invalid_api_key",
        )
    try:
        payload = decode_token(token)
    except Exception as exc:  # noqa: BLE001
        raise OpenAICompatError(
            status_code=401,
            message="Invalid or expired token",
            error_type="invalid_request_error",
            code="invalid_api_key",
        ) from exc
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise OpenAICompatError(
            status_code=401,
            message="Malformed token",
            error_type="invalid_request_error",
            code="invalid_api_key",
        )
    return subject


@router.post("/chat/completions")
async def create_chat_completion(
    body: ChatCompletionsRequest,
    request: Request,
) -> JSONResponse:
    try:
        _require_openai_bearer(request)
        ensure_supported_request(body)
        profile = resolve_profile(body.model)
        sample = build_sample_from_request(body, profile)
        result = await execute_sync_sample(sample)
        response = build_chat_completion_response(body, result, profile)
        return JSONResponse(status_code=200, content=response.model_dump())
    except OpenAICompatError as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.to_response().model_dump())
```

- [ ] **Step 4: Mount the new router in the FastAPI app**

```python
# src/autoagent/main.py
from autoagent.api.openai_compat import router as openai_compat_router

app.include_router(openai_compat_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(tests_router, prefix="/api/v1")
```

- [ ] **Step 5: Run the new integration tests and the existing auth/tests regression set**

Run: `python3.11 -m pytest tests/integration/test_openai_chat_completions.py tests/integration/test_auth_endpoints.py tests/integration/test_tests_endpoints.py -q`

Expected: PASS. The new route works without breaking login or the existing sync test API.

- [ ] **Step 6: Commit**

```bash
git add src/autoagent/api/openai_compat.py src/autoagent/main.py tests/integration/test_openai_chat_completions.py
git commit -m "feat: add openai chat completions endpoint"
```

---

### Task 4: Documentation And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the README API section with OpenAI compatibility usage**

```md
## OpenAI-compatible single test

Users can call AutoAgent through an OpenAI-compatible sync endpoint:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<密码>"}' | jq -r .token)
```

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key=TOKEN,
)

resp = client.chat.completions.create(
    model="my_profile",
    messages=[{"role": "user", "content": "你好"}],
    extra_body={
        "new_session": True,
        "timeout_sec": 120,
        "retry": 1,
        "dry_run": False,
    },
)

print(resp.choices[0].message.content)
```

Notes:

- `model` maps to AutoAgent `target_profile`
- only the last `user` message is used in v1
- `stream=true` is not supported in v1
- when a profile has LLM response extraction enabled, AutoAgent prefers `llm_responses` and falls back to static `responses` on extraction failure
```

- [ ] **Step 2: Run the targeted test suite for all changed backend areas**

Run: `python3.11 -m pytest tests/unit/test_sync_tests_service.py tests/unit/test_openai_compat.py tests/integration/test_openai_chat_completions.py tests/integration/test_tests_endpoints.py tests/integration/test_tests_sync_android.py tests/integration/test_auth_endpoints.py -q`

Expected: PASS.

- [ ] **Step 3: Run the fast backend regression suite**

Run: `python3.11 -m pytest -q -m "not playwright and not android and not slow"`

Expected: PASS. No existing non-browser, non-device backend behavior regresses.

- [ ] **Step 4: Run lint on changed Python files**

Run: `python3.11 -m ruff check src/autoagent/api/openai_compat.py src/autoagent/openai_compat src/autoagent/services tests/unit/test_sync_tests_service.py tests/unit/test_openai_compat.py tests/integration/test_openai_chat_completions.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: add openai compatibility usage"
```
