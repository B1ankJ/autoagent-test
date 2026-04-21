import asyncio
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
    save_profile_yaml("p_api", yaml.safe_dump({
        "name": "p_api", "platform": "api",
        "api": {"base_url": "https://api.example.com/v1", "model": "m", "api_key_env": "OPENAI_TEST_KEY"},
    }))
    from autoagent.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client) -> dict:
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def _wait_done(client, h, batch_id, n=40):
    for _ in range(n):
        await asyncio.sleep(0.1)
        r = await client.get(f"/api/v1/batches/{batch_id}", headers=h)
        if r.json()["status"] in ("done", "failed", "cancelled"):
            return r.json()
    raise AssertionError("batch did not finish in time")


async def test_json_batch_flow(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://api.example.com/v1/chat/completions", json={"choices": [{"message": {"content": "a"}}]})
    httpx_mock.add_response(url="https://api.example.com/v1/chat/completions", json={"choices": [{"message": {"content": "b"}}]})
    h = await _login(client)

    body = {
        "name": "batch1", "mode": "api", "concurrency": 1,
        "samples": [
            {"id": "t1", "prompts": ["x"], "mode": "api", "target_profile": "p_api"},
            {"id": "t2", "prompts": ["y"], "mode": "api", "target_profile": "p_api"},
        ],
    }
    r = await client.post("/api/v1/batches", json=body, headers=h)
    assert r.status_code == 201
    batch_id = r.json()["batch_id"]

    final = await _wait_done(client, h, batch_id)
    assert final["done"] == 2 and final["failed"] == 0
    assert final["status"] == "done"

    r = await client.get(f"/api/v1/batches/{batch_id}/results", headers=h)
    assert r.status_code == 200
    lines = r.text.strip().splitlines()
    assert len(lines) == 2


async def test_file_upload_batch(client, httpx_mock: HTTPXMock, tmp_path):
    httpx_mock.add_response(url="https://api.example.com/v1/chat/completions", json={"choices": [{"message": {"content": "ok"}}]})
    h = await _login(client)
    jsonl = '{"id":"t1","prompts":["a"],"mode":"api","target_profile":"p_api"}\n'
    files = {"file": ("b.jsonl", jsonl, "application/x-ndjson")}
    data = {"name": "upl", "mode": "api", "concurrency": "1"}
    r = await client.post("/api/v1/batches/upload", files=files, data=data, headers=h)
    assert r.status_code == 201
    batch_id = r.json()["batch_id"]
    final = await _wait_done(client, h, batch_id)
    assert final["done"] == 1


async def test_mode_mismatch_rejected(client):
    h = await _login(client)
    body = {
        "name": "x", "mode": "api", "concurrency": 1,
        "samples": [{"id": "t1", "prompts": ["x"], "mode": "gui_pc_web", "target_profile": "p_api"}],
    }
    r = await client.post("/api/v1/batches", json=body, headers=h)
    assert r.status_code == 422  # pydantic validator rejects


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
async def test_list_batches(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://api.example.com/v1/chat/completions", json={"choices": [{"message": {"content": "x"}}]})
    h = await _login(client)
    body = {
        "name": "b1", "mode": "api", "concurrency": 1,
        "samples": [{"id": "t1", "prompts": ["x"], "mode": "api", "target_profile": "p_api"}],
    }
    await client.post("/api/v1/batches", json=body, headers=h)
    r = await client.get("/api/v1/batches", headers=h)
    assert r.status_code == 200
    assert len(r.json()) >= 1
