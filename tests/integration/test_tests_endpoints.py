import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.auth.passwords import hash_password
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("OPENAI_TEST_KEY", "sk-test")
    await init_db()
    await upsert_user("admin", hash_password("pw"))
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
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client) -> dict:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_sync_test_runs_to_done(client, httpx_mock: HTTPXMock, monkeypatch):
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "hi!"}}]},
    )
    h = await _login(client)
    sample = {"id": "t1", "prompts": ["yo"], "mode": "api", "target_profile": "p_api"}
    r = await client.post("/api/v1/tests/sync", json=sample, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["responses"] == ["hi!"]
    assert body["llm_responses"] == []
    assert body["llm_errors"] == []


async def test_async_test_lifecycle(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "async ok"}}]},
    )
    h = await _login(client)
    sample = {"id": "t1", "prompts": ["yo"], "mode": "api", "target_profile": "p_api"}
    r = await client.post("/api/v1/tests", json=sample, headers=h)
    assert r.status_code == 202
    task_id = r.json()["task_id"]

    import asyncio

    for _ in range(40):
        await asyncio.sleep(0.1)
        r = await client.get(f"/api/v1/tests/{task_id}", headers=h)
        if r.status_code == 200 and r.json()["status"] in ("done", "failed"):
            break
    assert r.json()["status"] == "done"
    assert r.json()["responses"] == ["async ok"]
