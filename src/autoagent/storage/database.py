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
            result = await conn.execute(text("PRAGMA table_info(batches)"))
            batch_columns = {row[1] for row in result.fetchall()}
            if "samples_request_json" not in batch_columns:
                await conn.execute(
                    text("ALTER TABLE batches ADD COLUMN samples_request_json TEXT")
                )
            # Indexes so list/count/stats/retention queries don't full-scan
            # as batches/samples accumulate — create_all() adds these for
            # fresh DBs; this covers upgrades of existing dev/prod databases.
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_batches_created_at ON batches (created_at)")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_batches_status ON batches (status)")
            )
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_samples_status ON samples (status)")
            )
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_samples_target_profile "
                    "ON samples (target_profile)"
                )
            )
            # Backfill: prompts_sent_json used to be written with ensure_ascii
            # (default), so non-ASCII prompts were stored as \uXXXX escapes and
            # the batch search LIKE could never match a Chinese query. Re-dump
            # any still-escaped rows as literal UTF-8. Idempotent: converted
            # rows no longer contain "\u" so they're skipped next boot.
            await _backfill_prompts_ensure_ascii(conn)


async def _backfill_prompts_ensure_ascii(conn) -> None:
    import json as _json

    rows = (
        await conn.execute(
            text(
                "SELECT batch_id, id, prompts_sent_json FROM samples "
                "WHERE prompts_sent_json LIKE '%\\u%'"
            )
        )
    ).fetchall()
    for batch_id, sample_id, raw in rows:
        try:
            fixed = _json.dumps(_json.loads(raw), ensure_ascii=False)
        except (TypeError, ValueError):
            continue
        if fixed != raw:
            await conn.execute(
                text(
                    "UPDATE samples SET prompts_sent_json = :v "
                    "WHERE batch_id = :b AND id = :s"
                ),
                {"v": fixed, "b": batch_id, "s": sample_id},
            )


async def reset_db_for_tests() -> None:
    """Drop all and recreate. ONLY for tests."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
