import pytest
from httpx import ASGITransport, AsyncClient

from autoagent.auth.passwords import hash_password
from autoagent.config.settings import get_settings
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


async def test_profile_builder_requires_auth(client):
    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
    )
    assert create.status_code == 401

    fetched = await client.get("/api/v1/profile-builder/sessions/missing")
    assert fetched.status_code == 401


async def test_profile_builder_session_lifecycle(client):
    headers = await _h(client)

    create = await client.post(
        "/api/v1/profile-builder/sessions",
        json={"platform": "android", "device_serial": "serial-1", "name": "qwen"},
        headers=headers,
    )

    assert create.status_code == 201
    session = create.json()
    expected_artifact_dir = str(get_settings().data_root / "profile_builder" / session["id"])

    assert session["platform"] == "android"
    assert session["device_serial"] == "serial-1"
    assert session["name"] == "qwen"
    assert session["status"] == "draft"
    assert session["steps"] == ["idle", "editing", "response"]
    assert session["artifact_dir"] == expected_artifact_dir

    fetched = await client.get(
        f"/api/v1/profile-builder/sessions/{session['id']}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.json() == session
