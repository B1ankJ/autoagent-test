import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.models.api import SampleResult
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("pw"))
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _h(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_sync_android_uses_longer_timeout(client, monkeypatch):
    from autoagent.api import tests as mod

    captured = {}

    class Scheduler:
        async def submit(self, **kwargs):
            captured.update(kwargs)
            return "b1"

        async def wait_done(self, batch_id, timeout_sec):
            captured["timeout_sec"] = timeout_sec

    async def fake_list(_batch_id):
        return [
            SampleResult(
                id="s1",
                status="done",
                prompts_sent=["hi"],
                responses=["echo: hi"],
                mode="gui_android",
                target_profile="fake_android",
            )
        ]

    monkeypatch.setattr(mod, "get_scheduler", lambda: Scheduler())
    monkeypatch.setattr(mod, "list_samples_for_batch", fake_list)

    h = await _h(client)
    r = await client.post(
        "/api/v1/tests/sync",
        json={
            "id": "s1",
            "prompts": ["hi"],
            "mode": "gui_android",
            "target_profile": "fake_android",
        },
        headers=h,
    )
    assert r.status_code == 200
    assert captured["timeout_sec"] == 210


async def test_sync_returns_429_when_all_devices_reserved(client, monkeypatch):
    from autoagent.api import tests as mod

    class Scheduler:
        async def submit(self, **kwargs):
            return "b1"

        async def wait_done(self, batch_id, timeout_sec):
            pass

    async def fake_list(_batch_id):
        return [
            SampleResult(
                id="s1",
                status="failed",
                prompts_sent=["hi"],
                mode="agent_android",
                target_profile="fake_android",
                error="all devices reserved by other session(s): ['conv-other']",
                metadata={"blocking_session_ids": ["conv-other"]},
            )
        ]

    monkeypatch.setattr(mod, "get_scheduler", lambda: Scheduler())
    monkeypatch.setattr(mod, "list_samples_for_batch", fake_list)

    h = await _h(client)
    r = await client.post(
        "/api/v1/tests/sync",
        json={
            "id": "s1",
            "prompts": ["hi"],
            "mode": "agent_android",
            "target_profile": "fake_android",
            "session_id": "conv-me",
            "new_session": True,
        },
        headers=h,
    )
    assert r.status_code == 429
    body = r.json()["detail"]
    assert body["blocking_session_ids"] == ["conv-other"]


async def test_sync_normal_failure_is_not_429(client, monkeypatch):
    # A plain failure (no blocking_session_ids in metadata) must not be
    # mistaken for a reservation conflict.
    from autoagent.api import tests as mod

    class Scheduler:
        async def submit(self, **kwargs):
            return "b1"

        async def wait_done(self, batch_id, timeout_sec):
            pass

    async def fake_list(_batch_id):
        return [
            SampleResult(
                id="s1",
                status="failed",
                prompts_sent=["hi"],
                mode="agent_android",
                target_profile="fake_android",
                error="something else went wrong",
            )
        ]

    monkeypatch.setattr(mod, "get_scheduler", lambda: Scheduler())
    monkeypatch.setattr(mod, "list_samples_for_batch", fake_list)

    h = await _h(client)
    r = await client.post(
        "/api/v1/tests/sync",
        json={
            "id": "s1",
            "prompts": ["hi"],
            "mode": "agent_android",
            "target_profile": "fake_android",
        },
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
