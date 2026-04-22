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
        return [DeviceInfo(serial="emulator-5554", online=True, enabled=True)]

    monkeypatch.setattr(mod, "refresh_devices_now", fake_refresh)
    h = await _h(client)
    r = await client.post("/api/v1/devices/refresh", headers=h)
    assert r.status_code == 200
    assert r.json()[0]["serial"] == "emulator-5554"


async def test_patch_label_404(client):
    h = await _h(client)
    r = await client.patch("/api/v1/devices/missing", json={"label": "x"}, headers=h)
    assert r.status_code == 404
