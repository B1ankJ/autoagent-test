import pytest
from autoagent.auth.passwords import hash_password, verify_password


def test_hash_and_verify_password():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


from autoagent.storage.database import init_db
from autoagent.storage.users import create_user, get_user


@pytest.mark.asyncio
async def test_user_round_trip():
    await init_db()
    h = hash_password("pw")
    await create_user("alice", h)
    u = await get_user("alice")
    assert u is not None
    assert u.username == "alice"
