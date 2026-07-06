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
        url = _db_url()
        # timeout (seconds) → sqlite busy_timeout on every pooled connection,
        # so a transient WAL lock waits instead of raising "database is locked".
        connect_args = {"timeout": 5} if url.startswith("sqlite") else {}
        _engine = create_async_engine(
            url, echo=False, future=True, connect_args=connect_args
        )
        _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        if engine.url.get_backend_name().startswith("sqlite"):
            # WAL lets readers (2s UI polling) run concurrently with writers
            # (per-sample upserts) instead of blocking on a whole-db lock.
            # journal_mode is persistent (stored in the db file); setting it
            # once at boot is enough. Per-connection busy waiting comes from
            # the engine connect_args timeout above.
            await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name().startswith("sqlite"):
            result = await conn.execute(text("PRAGMA table_info(devices)"))
            device_columns = {row[1] for row in result.fetchall()}
            if "adb_keyboard_installed" not in device_columns:
                await conn.execute(
                    text("ALTER TABLE devices ADD COLUMN adb_keyboard_installed BOOLEAN")
                )
            if "adb_keyboard_enabled" not in device_columns:
                await conn.execute(
                    text("ALTER TABLE devices ADD COLUMN adb_keyboard_enabled BOOLEAN")
                )
            result = await conn.execute(text("PRAGMA table_info(samples)"))
            sample_columns = {row[1] for row in result.fetchall()}
            if "llm_responses_json" not in sample_columns:
                await conn.execute(text("ALTER TABLE samples ADD COLUMN llm_responses_json TEXT"))
            if "llm_errors_json" not in sample_columns:
                await conn.execute(text("ALTER TABLE samples ADD COLUMN llm_errors_json TEXT"))
            # Index on batches.created_at so list/count/stats ORDER BY
            # doesn't full-scan the table. create_all() adds it for fresh
            # DBs; this covers upgrades of existing dev/prod databases.
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_batches_created_at ON batches (created_at)")
            )


async def reset_db_for_tests() -> None:
    """Drop all and recreate. ONLY for tests."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
