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


async def test_preflight_allowed_when_disabled(client, monkeypatch):
    # preflight is read-only diagnostics, so it works even with self-update off.
    from autoagent.system.updater import PreflightResult, ToolCheck

    monkeypatch.setattr(
        updater,
        "preflight",
        lambda: PreflightResult(
            ok=True,
            tools=[ToolCheck(name="git", ok=True, detail="git 2.0")],
            remote_ok=True,
            remote_detail="abc123",
            tree_clean=True,
            tree_detail="clean",
        ),
    )
    r = await client.get("/api/v1/system/update/preflight", headers=await _h(client))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["tools"][0]["name"] == "git"


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


def _set_log_file(monkeypatch, path) -> None:
    from autoagent.config.settings import get_settings

    monkeypatch.setenv("LOG_FILE", str(path))
    get_settings.cache_clear()


async def test_log_requires_auth(client):
    r = await client.get("/api/v1/system/log")
    assert r.status_code == 401


async def test_log_reports_not_exists_for_missing_file(client, monkeypatch, tmp_path):
    _set_log_file(monkeypatch, tmp_path / "does-not-exist.log")
    r = await client.get("/api/v1/system/log", headers=await _h(client))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is False
    assert body["content"] == ""
    assert body["size_bytes"] == 0


async def test_log_tails_last_n_lines(client, monkeypatch, tmp_path):
    log_path = tmp_path / "app.log"
    log_path.write_text("\n".join(f"line {i}" for i in range(1, 201)) + "\n")
    _set_log_file(monkeypatch, log_path)

    r = await client.get("/api/v1/system/log", params={"lines": 50}, headers=await _h(client))
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert body["truncated"] is True
    assert body["content"].splitlines() == [f"line {i}" for i in range(151, 201)]


async def test_log_not_truncated_when_file_has_fewer_lines_than_requested(
    client, monkeypatch, tmp_path
):
    log_path = tmp_path / "app.log"
    log_path.write_text("only line\n")
    _set_log_file(monkeypatch, log_path)

    r = await client.get("/api/v1/system/log", params={"lines": 500}, headers=await _h(client))
    body = r.json()
    assert body["truncated"] is False
    assert body["content"] == "only line"


async def test_log_download_streams_the_file(client, monkeypatch, tmp_path):
    log_path = tmp_path / "app.log"
    log_path.write_text("hello world\n")
    _set_log_file(monkeypatch, log_path)

    r = await client.get("/api/v1/system/log/download", headers=await _h(client))
    assert r.status_code == 200
    assert r.text == "hello world\n"


async def test_log_download_404_when_missing(client, monkeypatch, tmp_path):
    _set_log_file(monkeypatch, tmp_path / "nope.log")
    r = await client.get("/api/v1/system/log/download", headers=await _h(client))
    assert r.status_code == 404
