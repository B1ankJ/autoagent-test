import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
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

    new_vals = {"api_timeout_sec": 30, "gui_timeout_sec": 300, "retry": 5, "concurrency": 2, "verbose_logs": False}
    r = await client.put("/api/v1/config/defaults", json=new_vals, headers=h)
    assert r.status_code == 200

    r = await client.get("/api/v1/config/defaults", headers=h)
    assert r.json() == new_vals


async def test_vlm_config_roundtrip(client):
    h = await _h(client)
    r = await client.get("/api/v1/config/vlm", headers=h)
    assert r.status_code == 200
    assert r.json() is None

    body = {"base_url": "https://vlm.example.com/v1", "model": "v1", "api_key_env": "VLM_KEY"}
    r = await client.put("/api/v1/config/vlm", json=body, headers=h)
    assert r.status_code == 200

    r = await client.get("/api/v1/config/vlm", headers=h)
    assert r.json()["model"] == "v1"


async def test_devices_stub(client):
    h = await _h(client)
    r = await client.get("/api/v1/devices", headers=h)
    assert r.status_code == 200
    assert r.json() == []
