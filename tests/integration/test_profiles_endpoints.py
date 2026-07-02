import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.storage.database import init_db
from autoagent.storage.users import upsert_user


@pytest.fixture
async def client():
    await init_db()
    await upsert_user("admin", hash_password("admin_pw_1234"))
    from autoagent.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def _login(client) -> str:
    r = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"}
    )
    return r.json()["token"]


async def test_profiles_crud(client):
    token = await _login(client)
    h = {"Authorization": f"Bearer {token}"}

    profile_yaml = yaml.safe_dump(
        {
            "name": "openai_gpt4",
            "platform": "api",
            "api": {
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
                "api_key": "OPENAI_KEY",
            },
        }
    )

    # List initially empty
    r = await client.get("/api/v1/profiles", headers=h)
    assert r.status_code == 200
    assert r.json() == []

    # Create
    r = await client.post("/api/v1/profiles/openai_gpt4", json={"yaml": profile_yaml}, headers=h)
    assert r.status_code == 201

    # List shows it
    r = await client.get("/api/v1/profiles", headers=h)
    assert r.json() == [{"name": "openai_gpt4", "platform": "api", "serials": []}]

    # Get
    r = await client.get("/api/v1/profiles/openai_gpt4", headers=h)
    assert r.status_code == 200
    assert "openai_gpt4" in r.json()["yaml"]

    # Validate (good)
    r = await client.post("/api/v1/profiles/validate", json={"yaml": profile_yaml}, headers=h)
    assert r.json() == {"ok": True, "error": None}

    # Validate (bad)
    r = await client.post(
        "/api/v1/profiles/validate", json={"yaml": "name: x\nplatform: ios\n"}, headers=h
    )
    assert r.json()["ok"] is False

    # Delete
    r = await client.delete("/api/v1/profiles/openai_gpt4", headers=h)
    assert r.status_code == 204

    # Gone
    r = await client.get("/api/v1/profiles/openai_gpt4", headers=h)
    assert r.status_code == 404


async def test_profiles_require_auth(client):
    r = await client.get("/api/v1/profiles")
    assert r.status_code == 401


async def test_android_device_binding(client):
    token = await _login(client)
    h = {"Authorization": f"Bearer {token}"}

    android_yaml = yaml.safe_dump(
        {
            "name": "and1",
            "platform": "android",
            "package": "com.example",
            "input_locator": {"type": "class", "value": "c"},
            "response_extraction": {
                "method": "ui_tree_only",
                "response_container_locator": {"type": "class", "value": "c"},
                "scroll_container_locator": {"type": "class", "value": "c"},
                "latest_bubble_match": {"type": "class", "value": "c"},
            },
            "serial": "old-serial",
        }
    )
    r = await client.post("/api/v1/profiles/and1", json={"yaml": android_yaml}, headers=h)
    assert r.status_code == 201

    # Effective binding starts as the legacy serial.
    r = await client.get("/api/v1/profiles/and1/devices", headers=h)
    assert r.json()["serials"] == ["old-serial"]

    # Bind a pool of two (dedup + strip applied).
    r = await client.put(
        "/api/v1/profiles/and1/devices",
        json={"serials": ["A", "B", "A ", ""]},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["serials"] == ["A", "B"]

    # Summary reflects it and legacy serial is gone.
    r = await client.get("/api/v1/profiles", headers=h)
    summary = next(p for p in r.json() if p["name"] == "and1")
    assert summary["serials"] == ["A", "B"]

    # Clear.
    r = await client.put("/api/v1/profiles/and1/devices", json={"serials": []}, headers=h)
    assert r.json()["serials"] == []


async def test_device_binding_rejects_non_android(client):
    token = await _login(client)
    h = {"Authorization": f"Bearer {token}"}
    api_yaml = yaml.safe_dump(
        {
            "name": "apip",
            "platform": "api",
            "api": {"base_url": "https://x/v1", "model": "m", "api_key": "k"},
        }
    )
    await client.post("/api/v1/profiles/apip", json={"yaml": api_yaml}, headers=h)
    r = await client.put("/api/v1/profiles/apip/devices", json={"serials": ["A"]}, headers=h)
    assert r.status_code == 422
