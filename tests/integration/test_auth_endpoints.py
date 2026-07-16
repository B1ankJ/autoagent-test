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
    r = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin_pw_1234"}
    )
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


async def test_login_runs_password_check_even_for_unknown_user(client, monkeypatch):
    # Timing side-channel guard: an unknown username must not short-circuit
    # past the bcrypt check — otherwise an attacker can enumerate valid
    # usernames by how much slower a known-user response is than an
    # unknown-user one.
    from autoagent.api import auth as auth_module

    calls: list[str] = []
    original = auth_module.verify_password

    def spy(plaintext, hashed):
        calls.append(hashed)
        return original(plaintext, hashed)

    monkeypatch.setattr(auth_module, "verify_password", spy)

    r = await client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})

    assert r.status_code == 401
    assert calls == [auth_module._DUMMY_HASH]
