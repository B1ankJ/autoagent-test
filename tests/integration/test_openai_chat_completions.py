from __future__ import annotations

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.auth.passwords import hash_password
from autoagent.config.settings import get_settings
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


async def test_chat_completions_api_success_with_static_api_key(
    client: AsyncClient,
    httpx_mock: HTTPXMock,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STATIC_API_KEY", "permanent-key")
    get_settings.cache_clear()
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
        json={"choices": [{"message": {"content": "hi from static key"}}]},
    )

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "p_api", "messages": [{"role": "user", "content": "hello"}]},
        headers={"Authorization": "Bearer permanent-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["choices"][0]["message"]["content"] == "hi from static key"
    assert body["x_autoagent"]["responses"] == ["hi from static key"]


async def test_chat_completions_returns_openai_shaped_401_without_token(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "missing", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_api_key"


async def test_chat_completions_rejects_wrong_static_api_key(
    client: AsyncClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("STATIC_API_KEY", "permanent-key")
    get_settings.cache_clear()

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "missing", "messages": [{"role": "user", "content": "hello"}]},
        headers={"Authorization": "Bearer wrong-key"},
    )

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "invalid_api_key"
    assert body["error"]["message"] == "Invalid or expired token"


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


async def test_chat_completions_returns_openai_shaped_400_for_malformed_json(
    client: AsyncClient,
) -> None:
    headers = await _login(client)
    response = await client.post(
        "/v1/chat/completions",
        content='{"model":"p_api","messages":[{"role":"user","content":"hello"}]',
        headers={**headers, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "invalid_request_error"


async def test_chat_completions_returns_openai_shaped_500_for_unexpected_runtime_error(
    client: AsyncClient,
    monkeypatch,
) -> None:
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

    async def fake_execute(sample, *, get_scheduler_fn, list_samples_for_batch_fn):
        raise RuntimeError("boom")

    monkeypatch.setattr("autoagent.api.openai_compat.execute_sync_sample", fake_execute)
    headers = await _login(client)

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "p_api", "messages": [{"role": "user", "content": "hello"}]},
        headers=headers,
    )

    assert response.status_code == 500
    body = response.json()
    assert "error" in body
    assert body["error"]["type"] == "api_error"


async def test_chat_completions_maps_extensions_and_profile_mode(
    client: AsyncClient,
    monkeypatch,
) -> None:
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

    async def fake_execute(sample, *, get_scheduler_fn, list_samples_for_batch_fn):
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

    async def fake_execute(sample, *, get_scheduler_fn, list_samples_for_batch_fn):
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
