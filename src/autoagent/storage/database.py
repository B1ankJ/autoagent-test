from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from autoagent.config.settings import get_settings
from autoagent.models.db import Base

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _db_url() -> str:
    settings = get_settings()
    db_path = settings.data_root / "db.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"


def get_engine():
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(_db_url(), echo=False, future=True)
        _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name().startswith("sqlite"):
            result = await conn.execute(text("PRAGMA table_info(devices)"))
            columns = {row[1] for row in result.fetchall()}
            if "adb_keyboard_installed" not in columns:
                await conn.execute(
                    text("ALTER TABLE devices ADD COLUMN adb_keyboard_installed BOOLEAN")
                )
            if "adb_keyboard_enabled" not in columns:
                await conn.execute(
                    text("ALTER TABLE devices ADD COLUMN adb_keyboard_enabled BOOLEAN")
                )


async def reset_db_for_tests() -> None:
    """Drop all and recreate. ONLY for tests."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
