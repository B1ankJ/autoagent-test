from __future__ import annotations

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("STATIC_API_KEY", "permanent-key")
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    from autoagent.config.settings import get_settings

    get_settings.cache_clear()
    await init_db()
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    get_settings.cache_clear()


async def test_static_api_key_can_call_tests_sync(
    client: AsyncClient,
    httpx_mock: HTTPXMock,
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
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "hi!"}}]},
    )

    response = await client.post(
        "/api/v1/tests/sync",
        headers={"Authorization": "Bearer permanent-key"},
        json={
            "id": "t1",
            "prompts": ["hello"],
            "mode": "api",
            "target_profile": "p_api",
        },
    )

    assert response.status_code == 200
    assert response.json()["responses"] == ["hi!"]


async def test_wrong_static_api_key_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/profiles",
        headers={"Authorization": "Bearer wrong-key"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"
