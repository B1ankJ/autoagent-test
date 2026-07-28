import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.executors.llm_checker import CheckResult
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


async def test_defaults_roundtrip(client):
    h = await _h(client)
    r = await client.get("/api/v1/config/defaults", headers=h)
    assert r.status_code == 200
    assert r.json()["retry"] == 2

    new_vals = {
        "api_timeout_sec": 30,
        "gui_timeout_sec": 300,
        "retry": 5,
        "concurrency": 2,
        "verbose_logs": False,
        "log_retention_days": 7,
        "archive_retention_days": 0,
        "self_update_enabled": False,
        "backup_retention_days": 14,
        "backup_interval_hours": 24,
    }
    r = await client.put("/api/v1/config/defaults", json=new_vals, headers=h)
    assert r.status_code == 200

    r = await client.get("/api/v1/config/defaults", headers=h)
    assert r.json() == new_vals


async def test_vlm_config_roundtrip(client):
    h = await _h(client)
    r = await client.get("/api/v1/config/vlm", headers=h)
    assert r.status_code == 200
    assert r.json() is None

    body = {"base_url": "https://vlm.example.com/v1", "model": "v1", "api_key": "VLM_KEY"}
    with patch(
        "autoagent.api.config.check_llm_api",
        new=AsyncMock(return_value=CheckResult(ok=True, stage="ok", message="ok", latency_ms=1)),
    ) as m:
        r = await client.put("/api/v1/config/vlm", json=body, headers=h)
    assert r.status_code == 200
    m.assert_awaited_once_with("https://vlm.example.com/v1", "v1", "VLM_KEY")

    r = await client.get("/api/v1/config/vlm", headers=h)
    assert r.json()["model"] == "v1"


async def test_devices_stub(client):
    h = await _h(client)
    r = await client.get("/api/v1/devices", headers=h)
    assert r.status_code == 200
    assert r.json() == []


async def test_backup_run_and_list(client):
    # conftest's autouse _env_defaults already points DATA_ROOT at an
    # isolated tmp_path, and the client fixture's init_db() already created
    # db.sqlite there.
    h = await _h(client)
    r = await client.get("/api/v1/config/backup/list", headers=h)
    assert r.status_code == 200
    assert r.json() == []

    r = await client.post("/api/v1/config/backup/run", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["path"] is not None
    assert body["bytes_written"] > 0

    r = await client.get("/api/v1/config/backup/list", headers=h)
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 1
    assert listed[0]["name"] == Path(body["path"]).name
    assert listed[0]["bytes"] == body["bytes_written"]


async def test_backup_download_and_delete(client):
    h = await _h(client)
    r = await client.post("/api/v1/config/backup/run", headers=h)
    assert r.status_code == 200
    name = Path(r.json()["path"]).name

    r = await client.get(f"/api/v1/config/backup/download/{name}", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert len(r.content) > 0

    r = await client.delete(f"/api/v1/config/backup/{name}", headers=h)
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    r = await client.get("/api/v1/config/backup/list", headers=h)
    assert r.json() == []

    # Already deleted — a repeat delete/download 404s instead of erroring.
    r = await client.delete(f"/api/v1/config/backup/{name}", headers=h)
    assert r.status_code == 404
    r = await client.get(f"/api/v1/config/backup/download/{name}", headers=h)
    assert r.status_code == 404


async def test_backup_download_rejects_path_traversal(client):
    h = await _h(client)
    r = await client.get("/api/v1/config/backup/download/..%2F..%2Fetc%2Fpasswd", headers=h)
    assert r.status_code == 404


async def test_backup_run_respects_zero_retention_by_not_pruning(client):
    from autoagent.config.settings import get_settings

    h = await _h(client)
    await client.put(
        "/api/v1/config/defaults",
        json={
            "api_timeout_sec": 60,
            "gui_timeout_sec": 180,
            "retry": 2,
            "concurrency": 1,
            "verbose_logs": True,
            "log_retention_days": 7,
            "archive_retention_days": 0,
            "self_update_enabled": False,
            "backup_retention_days": 0,
            "backup_interval_hours": 24,
        },
        headers=h,
    )

    # A stale zip that would be pruned under any positive retention window.
    backups_dir = get_settings().data_root / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    stale = backups_dir / "stale.zip"
    stale.write_bytes(b"x")
    old = time.time() - 3600 * 24 * 365
    os.utime(stale, (old, old))

    r = await client.post("/api/v1/config/backup/run", headers=h)
    assert r.status_code == 200
    assert r.json()["pruned"] == 0
    assert stale.exists()
