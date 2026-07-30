import asyncio
import io
import json
import zipfile
from datetime import datetime, timezone

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from pytest_httpx import HTTPXMock

from autoagent.auth.passwords import hash_password
from autoagent.models.api import Sample, SampleResult
from autoagent.profiles.registry import save_profile_yaml
from autoagent.storage.batches import (
    create_batch,
    get_batch,
    update_batch_progress,
    update_batch_status,
)
from autoagent.storage.database import get_sessionmaker, init_db
from autoagent.storage.samples import upsert_sample
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


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
async def test_list_batches_and_stats_filter_by_status_and_mode(client, httpx_mock: HTTPXMock):
    # Regression: GET /batches used to silently ignore ?status=/?mode= —
    # the frontend applied them client-side to whatever page was fetched,
    # which showed an empty table when the match wasn't on that page even
    # though matching batches existed. Filtering must happen server-side.
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "x"}}]},
    )
    h = await _login(client)
    body = {
        "name": "will-fail",
        "mode": "api",
        "concurrency": 1,
        "samples": [{"id": "t1", "prompts": ["x"], "mode": "api", "target_profile": "p_api"}],
    }
    created = await client.post("/api/v1/batches", json=body, headers=h)
    batch_id = created.json()["batch_id"]
    await _wait_done(client, h, batch_id)
    await update_batch_status(batch_id, "failed")

    r = await client.get("/api/v1/batches", params={"status": "failed"}, headers=h)
    assert r.status_code == 200
    assert [b["batch_id"] for b in r.json()] == [batch_id]

    r_done = await client.get("/api/v1/batches", params={"status": "done"}, headers=h)
    assert batch_id not in [b["batch_id"] for b in r_done.json()]

    r_mode = await client.get(
        "/api/v1/batches", params={"mode": "gui_android"}, headers=h
    )
    assert batch_id not in [b["batch_id"] for b in r_mode.json()]

    # /stats has no `status` filter (it groups by status) but must still
    # respect `mode`, mirroring /batches so the two stay consistent.
    stats = await client.get("/api/v1/batches/stats", params={"mode": "api"}, headers=h)
    assert stats.status_code == 200
    assert stats.json()["failed"] == 1
    stats_other_mode = await client.get(
        "/api/v1/batches/stats", params={"mode": "gui_android"}, headers=h
    )
    assert stats_other_mode.json()["total"] == 0


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
async def test_list_batches_and_stats_accept_multiple_status_and_mode_values(
    client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        url="https://api.example.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "x"}}]},
    )
    h = await _login(client)

    async def _make_batch(name: str, mode: str) -> str:
        body = {
            "name": name,
            "mode": mode,
            "concurrency": 1,
            "samples": [{"id": "t1", "prompts": ["x"], "mode": mode, "target_profile": "p"}],
        }
        created = await client.post("/api/v1/batches", json=body, headers=h)
        batch_id = created.json()["batch_id"]
        await _wait_done(client, h, batch_id)
        return batch_id

    api_batch = await _make_batch("api-one", "api")
    android_batch = await _make_batch("android-one", "gui_android")
    await update_batch_status(android_batch, "failed")

    # ?status=done&status=failed (repeated query param) should match both.
    r = await client.get(
        "/api/v1/batches",
        params=[("status", "done"), ("status", "failed")],
        headers=h,
    )
    assert r.status_code == 200
    ids = {b["batch_id"] for b in r.json()}
    assert api_batch in ids
    assert android_batch in ids

    # ?mode=api&mode=gui_android should match both too.
    r_mode = await client.get(
        "/api/v1/batches",
        params=[("mode", "api"), ("mode", "gui_android")],
        headers=h,
    )
    mode_ids = {b["batch_id"] for b in r_mode.json()}
    assert api_batch in mode_ids
    assert android_batch in mode_ids

    stats = await client.get(
        "/api/v1/batches/stats",
        params=[("mode", "api"), ("mode", "gui_android")],
        headers=h,
    )
    # Both created batches (one per mode) must be counted somewhere in the
    # combined breakdown — the exact status either landed in isn't the point
    # here (gui_android has no real device in this test environment and may
    # fail for reasons unrelated to the filter itself).
    assert sum(stats.json()[s] for s in ("queued", "running", "done", "failed", "cancelled")) >= 2


async def test_list_batches_rejects_limit_above_cap(client):
    h = await _login(client)
    r = await client.get("/api/v1/batches", params={"limit": 201}, headers=h)
    assert r.status_code == 422
    r = await client.get("/api/v1/batches", params={"limit": 200}, headers=h)
    assert r.status_code == 200
    r = await client.get("/api/v1/batches", params={"offset": -1}, headers=h)
    assert r.status_code == 422


async def test_list_batches_rejects_invalid_sort_params(client):
    h = await _login(client)
    r = await client.get("/api/v1/batches", params={"sort_by": "name"}, headers=h)
    assert r.status_code == 422
    r = await client.get(
        "/api/v1/batches", params={"sort_by": "avg_duration_ms", "sort_dir": "up"}, headers=h
    )
    assert r.status_code == 422


async def test_list_batches_sorts_by_avg_duration_ms(client):
    h = await _login(client)
    for batch_id, duration in [("b_fast", 100), ("b_slow", 5000), ("b_mid", 1000)]:
        await create_batch(
            batch_id=batch_id, name=batch_id, mode="api", concurrency=1, total=1,
            target_profile_default=None,
        )
        await update_batch_progress(batch_id, done=1, failed=0, avg_duration_ms=duration)

    r = await client.get(
        "/api/v1/batches", params={"sort_by": "avg_duration_ms", "sort_dir": "desc"}, headers=h
    )
    assert r.status_code == 200
    ids = [b["batch_id"] for b in r.json()]
    assert ids.index("b_slow") < ids.index("b_mid") < ids.index("b_fast")


async def test_list_batches_exposes_session_id_for_single_sample_batches(client):
    h = await _login(client)
    await create_batch(
        batch_id="b_session", name="b_session", mode="agent_android", concurrency=1,
        total=1, target_profile_default=None,
    )
    await upsert_sample(
        "b_session",
        SampleResult(
            id="s1", status="done", prompts_sent=["hi"], responses=["ok"],
            mode="agent_android", target_profile="p", session_id="conv-1",
        ),
    )

    r = await client.get("/api/v1/batches", headers=h)
    assert r.status_code == 200
    row = next(b for b in r.json() if b["batch_id"] == "b_session")
    assert row["session_id"] == "conv-1"


async def test_list_batches_flags_and_can_exclude_end_session_no_ops(client):
    h = await _login(client)
    await create_batch(
        batch_id="b_end_session", name="b_end_session", mode="agent_android", concurrency=1,
        total=1, target_profile_default=None,
    )
    await upsert_sample(
        "b_end_session",
        SampleResult(
            id="s1", status="done", prompts_sent=[], mode="agent_android", target_profile="p",
            metadata={"session_released": True},
        ),
    )
    await create_batch(
        batch_id="b_normal_turn", name="b_normal_turn", mode="agent_android", concurrency=1,
        total=1, target_profile_default=None,
    )
    await upsert_sample(
        "b_normal_turn",
        SampleResult(
            id="s1", status="done", prompts_sent=["hi"], responses=["ok"],
            mode="agent_android", target_profile="p",
        ),
    )

    r = await client.get("/api/v1/batches", headers=h)
    rows = {b["batch_id"]: b for b in r.json()}
    assert rows["b_end_session"]["is_end_session"] is True
    assert rows["b_normal_turn"]["is_end_session"] is False

    r_excluded = await client.get(
        "/api/v1/batches", params={"exclude_end_session": True}, headers=h
    )
    excluded_ids = [b["batch_id"] for b in r_excluded.json()]
    assert "b_end_session" not in excluded_ids
    assert "b_normal_turn" in excluded_ids


async def test_list_batches_flags_and_can_filter_duration_anomalies(client):
    h = await _login(client)

    async def _single_sample_batch(batch_id: str, profile: str, duration: int) -> None:
        await create_batch(
            batch_id=batch_id, name=batch_id, mode="api", concurrency=1, total=1,
            target_profile_default=None,
        )
        await update_batch_status(batch_id, "done")
        await update_batch_progress(batch_id, done=1, failed=0, avg_duration_ms=duration)
        await upsert_sample(
            batch_id,
            SampleResult(
                id="s1", status="done", prompts_sent=["hi"], responses=["ok"],
                mode="api", target_profile=profile, duration_ms=duration,
            ),
        )

    for i in range(3):
        await _single_sample_batch(f"dur_baseline_{i}", "p_api", 100)
    await _single_sample_batch("dur_slow", "p_api", 500)

    r = await client.get("/api/v1/batches", headers=h)
    rows = {b["batch_id"]: b for b in r.json()}
    assert rows["dur_slow"]["is_duration_anomaly"] is True
    assert rows["dur_baseline_0"]["is_duration_anomaly"] is False

    r_filtered = await client.get(
        "/api/v1/batches", params={"duration_anomaly_only": True}, headers=h
    )
    filtered_ids = [b["batch_id"] for b in r_filtered.json()]
    assert filtered_ids == ["dur_slow"]


async def test_session_conversation_endpoint_reconstructs_turns_across_batches(client):
    h = await _login(client)
    turns = [
        ("b1", "turn-1", "hi", "hello!", 1),
        ("b2", "turn-2", "how are you", "good, thanks", 2),
    ]
    for batch_id, sample_id, prompt, response, minute in turns:
        await create_batch(
            batch_id=batch_id, name=batch_id, mode="agent_android", concurrency=1,
            total=1, target_profile_default=None,
        )
        await upsert_sample(
            batch_id,
            SampleResult(
                id=sample_id, status="done", prompts_sent=[prompt], responses=[response],
                mode="agent_android", target_profile="p", session_id="conv-thread",
                started_at=datetime(2026, 1, 1, 0, minute, tzinfo=timezone.utc),
            ),
        )

    r = await client.get("/api/v1/batches/sessions/conv-thread", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert [t["batch_id"] for t in body] == ["b1", "b2"]
    assert [t["prompt"] for t in body] == ["hi", "how are you"]
    assert [t["response"] for t in body] == ["hello!", "good, thanks"]


async def test_session_conversation_endpoint_empty_for_unknown_session(client):
    h = await _login(client)
    r = await client.get("/api/v1/batches/sessions/never-existed", headers=h)
    assert r.status_code == 200
    assert r.json() == []
