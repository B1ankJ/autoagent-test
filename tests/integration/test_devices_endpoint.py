import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.models.api import DeviceInfo
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


async def test_refresh_returns_devices(client, monkeypatch):
    from autoagent.api import devices as mod

    async def fake_refresh():
        return [
            DeviceInfo(
                serial="emulator-5554",
                online=True,
                enabled=True,
                adb_keyboard_installed=True,
                adb_keyboard_enabled=False,
            )
        ]

    monkeypatch.setattr(mod, "refresh_devices_now", fake_refresh)
    h = await _h(client)
    r = await client.post("/api/v1/devices/refresh", headers=h)
    assert r.status_code == 200
    assert r.json()[0]["serial"] == "emulator-5554"
    assert r.json()[0]["adb_keyboard_installed"] is True


async def test_install_adb_keyboard_route(client, monkeypatch):
    from autoagent.api import devices as mod

    async def fake_install(_serial: str):
        return DeviceInfo(
            serial="emulator-5554",
            online=True,
            enabled=True,
            adb_keyboard_installed=True,
            adb_keyboard_enabled=False,
        )

    monkeypatch.setattr(mod, "install_adb_keyboard_for_device", fake_install)
    h = await _h(client)
    r = await client.post("/api/v1/devices/emulator-5554/install-adb-keyboard", headers=h)
    assert r.status_code == 200
    assert r.json()["adb_keyboard_installed"] is True


async def test_patch_label_404(client):
    h = await _h(client)
    r = await client.patch("/api/v1/devices/missing", json={"label": "x"}, headers=h)
    assert r.status_code == 404


async def test_delete_device(client):
    from datetime import datetime, timezone

    from autoagent.storage.devices import upsert_discovered_device

    h = await _h(client)
    await upsert_discovered_device(
        serial="stale-1",
        model="X",
        android_version=None,
        adb_keyboard_installed=None,
        adb_keyboard_enabled=None,
        online=False,
        seen_at=datetime.now(timezone.utc),
    )
    # Present in the list.
    r = await client.get("/api/v1/devices", headers=h)
    assert any(d["serial"] == "stale-1" for d in r.json())
    # Delete it.
    r = await client.delete("/api/v1/devices/stale-1", headers=h)
    assert r.status_code == 204
    # Gone.
    r = await client.get("/api/v1/devices", headers=h)
    assert not any(d["serial"] == "stale-1" for d in r.json())
    # Deleting again 404s.
    r = await client.delete("/api/v1/devices/stale-1", headers=h)
    assert r.status_code == 404
