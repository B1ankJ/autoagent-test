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
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"})
    return r.json()["token"]


async def test_profiles_crud(client):
    token = await _login(client)
    h = {"Authorization": f"Bearer {token}"}

    profile_yaml = yaml.safe_dump({
        "name": "openai_gpt4", "platform": "api",
        "api": {"base_url": "https://api.openai.com/v1", "model": "gpt-4o", "api_key_env": "OPENAI_KEY"},
    })

    # List initially empty
    r = await client.get("/api/v1/profiles", headers=h)
    assert r.status_code == 200
    assert r.json()["names"] == []

    # Create
    r = await client.post("/api/v1/profiles/openai_gpt4", json={"yaml": profile_yaml}, headers=h)
    assert r.status_code == 201

    # List shows it
    r = await client.get("/api/v1/profiles", headers=h)
    assert "openai_gpt4" in r.json()["names"]

    # Get
    r = await client.get("/api/v1/profiles/openai_gpt4", headers=h)
    assert r.status_code == 200
    assert "openai_gpt4" in r.json()["yaml"]

    # Validate (good)
    r = await client.post("/api/v1/profiles/validate", json={"yaml": profile_yaml}, headers=h)
    assert r.json() == {"ok": True, "error": None}

    # Validate (bad)
    r = await client.post("/api/v1/profiles/validate", json={"yaml": "name: x\nplatform: ios\n"}, headers=h)
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
