import pytest

from autoagent.storage.database import get_sessionmaker, init_db
from autoagent.models.db import User


@pytest.mark.asyncio
async def test_init_db_creates_users_table():
    await init_db()
    sm = get_sessionmaker()
    async with sm() as s:
        u = User(username="x", password_hash="h")
        s.add(u)
        await s.commit()

    async with sm() as s:
        result = await s.get(User, "x")
        assert result is not None
        assert result.username == "x"
