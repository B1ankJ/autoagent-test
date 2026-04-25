import pytest
from sqlalchemy import text

from autoagent.models.db import User
from autoagent.storage.database import get_engine, get_sessionmaker, init_db


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


@pytest.mark.asyncio
async def test_init_db_adds_llm_columns_to_samples_table():
    await init_db()
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(samples)"))
        columns = {row[1] for row in result.fetchall()}
    assert "llm_responses_json" in columns
    assert "llm_errors_json" in columns
