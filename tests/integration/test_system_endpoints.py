from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.storage.configs import put_config
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user
from autoagent.system import updater
from autoagent.system.updater import ApplyResult, UpdateStatus


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


async def _enable(enabled: bool) -> None:
    await put_config("defaults", {"self_update_enabled": enabled})


async def test_status_requires_auth(client):
    r = await client.get("/api/v1/system/update/status")
    assert r.status_code == 401


async def test_status_reports_disabled_by_default(client, monkeypatch):
    monkeypatch.setattr(
        updater, "check_for_update", lambda **k: UpdateStatus(enabled=False, up_to_date=True)
    )
    r = await client.get("/api/v1/system/update/status", headers=await _h(client))
    assert r.status_code == 200
    assert r.json()["enabled"] is False


async def test_check_forbidden_when_disabled(client):
    r = await client.post("/api/v1/system/update/check", headers=await _h(client))
    assert r.status_code == 403


async def test_apply_forbidden_when_disabled(client):
    r = await client.post(
        "/api/v1/system/update/apply", json={"force": False}, headers=await _h(client)
    )
    assert r.status_code == 403


async def test_apply_conflict_when_active_batches(client, monkeypatch):
    await _enable(True)
    monkeypatch.setattr("autoagent.api.system.count_active_batches", _fake_active(3))
    r = await client.post(
        "/api/v1/system/update/apply", json={"force": False}, headers=await _h(client)
    )
    assert r.status_code == 409
    assert r.json()["detail"]["active_batches"] == 3


async def test_apply_force_runs_update(client, monkeypatch):
    await _enable(True)
    monkeypatch.setattr("autoagent.api.system.count_active_batches", _fake_active(2))
    monkeypatch.setattr(
        updater,
        "apply_update",
        lambda: ApplyResult(ok=True, restarting=True, steps=["ok"]),
    )
    r = await client.post(
        "/api/v1/system/update/apply", json={"force": True}, headers=await _h(client)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["restarting"] is True
    assert body["active_batches"] == 2


def _fake_active(n: int):
    async def _count() -> int:
        return n

    return _count
