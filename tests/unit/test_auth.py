import jwt
import pytest

from autoagent.auth.jwt import create_access_token, decode_token
from autoagent.auth.passwords import hash_password, verify_password
from autoagent.storage.database import init_db
from autoagent.storage.users import create_user, get_user


def test_hash_and_verify_password():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_verify_password_rejects_garbage_hash():
    assert verify_password("anything", "not-a-real-hash") is False


@pytest.mark.asyncio
async def test_user_round_trip():
    await init_db()
    h = hash_password("pw")
    await create_user("alice", h)
    u = await get_user("alice")
    assert u is not None
    assert u.username == "alice"
    assert u.password_hash == h


def test_jwt_round_trip():
    token = create_access_token("alice")
    payload = decode_token(token)
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_jwt_expired_rejected(monkeypatch):
    import autoagent.auth.jwt as jwt_mod

    # Force immediate expiry
    monkeypatch.setattr(jwt_mod, "_expiry_hours", lambda: -1)
    token = create_access_token("alice")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)
