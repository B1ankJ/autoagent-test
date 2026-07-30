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


async def test_install_adb_keyboard_status_reread_failure_is_502_not_500(
    client, monkeypatch, tmp_path
):
    from autoagent.config.settings import get_settings
    from autoagent.devices.adb import AdbCommandError

    apk = tmp_path / "ADBKeyboard.apk"
    apk.write_bytes(b"fake")
    monkeypatch.setattr(get_settings(), "adb_keyboard_apk_path", apk)

    from autoagent.api import devices as mod

    # The install itself succeeds, but the device drops offline right after
    # — before this fix, the unguarded status re-read below would raise
    # AdbCommandError unguarded and 500 the endpoint instead of a clean 502.
    monkeypatch.setattr(mod, "install_apk", lambda serial, path: None)

    def _boom(serial: str, package: str) -> bool:
        raise AdbCommandError("device offline")

    monkeypatch.setattr(mod, "is_package_installed", _boom)

    h = await _h(client)
    r = await client.post("/api/v1/devices/emulator-5554/install-adb-keyboard", headers=h)
    assert r.status_code == 502
    assert "device offline" in r.json()["detail"]


async def test_enable_ime_status_reread_failure_is_502_not_500(client, monkeypatch):
    from autoagent.api import devices as mod
    from autoagent.devices.adb import AdbCommandError

    monkeypatch.setattr(mod, "enable_ime", lambda serial, ime: None)
    monkeypatch.setattr(mod, "set_ime", lambda serial, ime: None)

    def _boom(serial: str, package: str) -> bool:
        raise AdbCommandError("device offline")

    monkeypatch.setattr(mod, "is_package_installed", _boom)

    h = await _h(client)
    r = await client.post("/api/v1/devices/emulator-5554/enable-ime", headers=h)
    assert r.status_code == 502
    assert "device offline" in r.json()["detail"]


async def test_disable_ime_status_reread_failure_is_502_not_500(client, monkeypatch):
    from autoagent.api import devices as mod
    from autoagent.devices.adb import AdbCommandError

    # disable_ime_route imports get_current_ime/reset_ime locally (not at
    # module level), so patch the real source module rather than `mod`.
    monkeypatch.setattr("autoagent.devices.adb.get_current_ime", lambda serial: None)

    def _boom(serial: str, package: str) -> bool:
        raise AdbCommandError("device offline")

    monkeypatch.setattr(mod, "is_package_installed", _boom)

    h = await _h(client)
    r = await client.post("/api/v1/devices/emulator-5554/disable-ime", headers=h)
    assert r.status_code == 502
    assert "device offline" in r.json()["detail"]


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


async def test_release_session_endpoint(client):
    from autoagent.api._deps import get_device_pool

    h = await _h(client)
    r = await client.post("/api/v1/devices/sessions/never-existed/release", headers=h)
    assert r.status_code == 200
    assert r.json() == {"session_id": "never-existed", "released": False}

    pool = get_device_pool()
    pool._remember_pin("conv-1", "emulator-5554")
    r = await client.post("/api/v1/devices/sessions/conv-1/release", headers=h)
    assert r.status_code == 200
    assert r.json() == {"session_id": "conv-1", "released": True}
    assert pool._lookup_pin("conv-1") is None


async def test_list_device_sessions_endpoint(client):
    from autoagent.api._deps import get_device_pool

    h = await _h(client)
    r = await client.get("/api/v1/devices/sessions", headers=h)
    assert r.status_code == 200
    assert r.json() == []

    pool = get_device_pool()
    pool._remember_pin("conv-1", "emulator-5554")
    r = await client.get("/api/v1/devices/sessions", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["session_id"] == "conv-1"
    assert body[0]["serial"] == "emulator-5554"
    assert 0 < body[0]["expires_in_sec"] <= 1800

    # Released pins disappear from the listing.
    await client.post("/api/v1/devices/sessions/conv-1/release", headers=h)
    r = await client.get("/api/v1/devices/sessions", headers=h)
    assert r.json() == []
