import asyncio
import io
import json
import zipfile

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.auth.passwords import hash_password
from autoagent.models.api import Sample
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.batches import get_batch
from autoagent.storage.database import get_sessionmaker, init_db
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


async def _wait_done(client, h, batch_id, n=40):
    for _ in range(n):
        await asyncio.sleep(0.1)
        r = await client.get(f"/api/v1/batches/{batch_id}", headers=h)
        if r.json()["status"] in ("done", "failed", "cancelled"):
            return r.json()
    raise AssertionError("batch did not finish in time")


async def test_json_batch_flow(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "a"}}]},
    )
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "b"}}]},
    )
    h = await _login(client)

    body = {
        "name": "batch1",
        "mode": "api",
        "concurrency": 1,
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
    assert final["concurrency"] == 1

    r = await client.get(f"/api/v1/batches/{batch_id}/results", headers=h)
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        jsonl_text = zf.read(f"{batch_id}.jsonl").decode("utf-8")
    lines = jsonl_text.strip().splitlines()
    assert len(lines) == 2


async def test_replay_reproduces_original_request_verbatim(client, httpx_mock: HTTPXMock):
    for _ in range(2):
        httpx_mock.add_response(
            url="https://api.example.com/v1/chat/completions",
            json={"choices": [{"message": {"content": "a"}}]},
        )
    h = await _login(client)

    body = {
        "name": "replay-me",
        "mode": "api",
        "concurrency": 1,
        "samples": [
            {
                "id": "t1",
                "prompts": ["x"],
                "mode": "api",
                "target_profile": "p_api",
                "new_session": True,
                "timeout_sec": 42,
                "retry": 3,
            },
        ],
    }
    r = await client.post("/api/v1/batches", json=body, headers=h)
    assert r.status_code == 201
    original_id = r.json()["batch_id"]
    await _wait_done(client, h, original_id)

    r = await client.post(f"/api/v1/batches/{original_id}/replay", headers=h)
    assert r.status_code == 201
    replay_id = r.json()["batch_id"]
    final = await _wait_done(client, h, replay_id)
    assert final["name"] == "replay-me (replay)"
    assert final["concurrency"] == 1
    assert final["total"] == 1

    # The replay's own submission is recorded too — confirm the fields that
    # /rerun would have dropped (new_session/timeout_sec/retry) survived the
    # round trip byte-for-byte, not just prompts/mode/target_profile.
    replayed_batch = await get_batch(replay_id)
    replayed_samples = json.loads(replayed_batch.samples_request_json)
    expected = Sample.model_validate(body["samples"][0]).model_dump(mode="json")
    assert replayed_samples == [expected]


async def test_replay_rejects_batch_without_recorded_request(client):
    h = await _login(client)
    sm = get_sessionmaker()
    from autoagent.models.db import Batch

    async with sm() as s:
        s.add(
            Batch(
                id="legacy_batch",
                name="pre-replay",
                mode="api",
                status="done",
                concurrency=1,
                total=0,
                samples_request_json=None,
            )
        )
        await s.commit()

    r = await client.post("/api/v1/batches/legacy_batch/replay", headers=h)
    assert r.status_code == 400
    assert "predates replay support" in r.json()["detail"]


async def test_replay_missing_batch_404(client):
    h = await _login(client)
    r = await client.post("/api/v1/batches/does-not-exist/replay", headers=h)
    assert r.status_code == 404


async def test_file_upload_batch(client, httpx_mock: HTTPXMock, tmp_path):
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "ok"}}]},
    )
    h = await _login(client)
    jsonl = '{"id":"t1","prompts":["a"],"mode":"api","target_profile":"p_api"}\n'
    files = {"file": ("b.jsonl", jsonl, "application/x-ndjson")}
    data = {"name": "upl", "mode": "api", "concurrency": "1"}
    r = await client.post("/api/v1/batches/upload", files=files, data=data, headers=h)
    assert r.status_code == 201
    batch_id = r.json()["batch_id"]
    final = await _wait_done(client, h, batch_id)
    assert final["done"] == 1


async def test_file_upload_rejects_oversized_file(client, monkeypatch):
    import autoagent.api.batches as batches_mod

    monkeypatch.setattr(batches_mod, "_MAX_UPLOAD_BYTES", 10)
    h = await _login(client)
    jsonl = '{"id":"t1","prompts":["a"],"mode":"api","target_profile":"p_api"}\n'
    files = {"file": ("b.jsonl", jsonl, "application/x-ndjson")}
    data = {"name": "upl-big", "mode": "api", "concurrency": "1"}
    r = await client.post("/api/v1/batches/upload", files=files, data=data, headers=h)
    assert r.status_code == 413


async def test_mode_mismatch_rejected(client):
    h = await _login(client)
    body = {
        "name": "x",
        "mode": "api",
        "concurrency": 1,
        "samples": [
            {"id": "t1", "prompts": ["x"], "mode": "gui_pc_web", "target_profile": "p_api"}
        ],
    }
    r = await client.post("/api/v1/batches", json=body, headers=h)
    assert r.status_code == 422  # pydantic validator rejects


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
async def test_list_batches(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "x"}}]},
    )
    h = await _login(client)
    body = {
        "name": "b1",
        "mode": "api",
        "concurrency": 1,
        "samples": [{"id": "t1", "prompts": ["x"], "mode": "api", "target_profile": "p_api"}],
    }
    await client.post("/api/v1/batches", json=body, headers=h)
    r = await client.get("/api/v1/batches", headers=h)
    assert r.status_code == 200
    assert len(r.json()) >= 1


async def test_list_batches_rejects_limit_above_cap(client):
    h = await _login(client)
    r = await client.get("/api/v1/batches", params={"limit": 201}, headers=h)
    assert r.status_code == 422
    r = await client.get("/api/v1/batches", params={"limit": 200}, headers=h)
    assert r.status_code == 200
    r = await client.get("/api/v1/batches", params={"offset": -1}, headers=h)
    assert r.status_code == 422
