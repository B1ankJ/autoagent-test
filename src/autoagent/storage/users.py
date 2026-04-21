from sqlalchemy import select

from autoagent.models.db import User
from autoagent.storage.database import get_sessionmaker


async def get_user(username: str) -> User | None:
    sm = get_sessionmaker()
    async with sm() as s:
        r = await s.execute(select(User).where(User.username == username))
        return r.scalar_one_or_none()


async def create_user(username: str, password_hash: str) -> User:
    sm = get_sessionmaker()
    async with sm() as s:
        u = User(username=username, password_hash=password_hash)
        s.add(u)
        await s.commit()
        return u


async def upsert_user(username: str, password_hash: str) -> None:
    sm = get_sessionmaker()
    async with sm() as s:
        existing = await s.get(User, username)
        if existing is None:
            s.add(User(username=username, password_hash=password_hash))
        else:
            existing.password_hash = password_hash
        await s.commit()
