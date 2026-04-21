import pytest
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


async def test_login_success(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"})
    assert r.status_code == 200
    body = r.json()
    assert "token" in body
    assert body["expires_in_sec"] > 0


async def test_login_bad_password(client):
    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401


async def test_login_unknown_user(client):
    r = await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401
