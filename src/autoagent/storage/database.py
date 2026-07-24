import asyncio
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from autoagent.config.settings import get_settings
from autoagent.models.db import Base

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

_REPO_ROOT = Path(__file__).resolve().parents[3]
# alembic/versions/<this>_baseline_schema.py — the "create everything from
# scratch" migration. Pre-existing (pre-Alembic) DBs get stamped here, not
# to head, so migrations after the baseline (e.g. the ensure_ascii
# backfill) still actually run once for them instead of being silently
# skipped.
_BASELINE_REVISION = "e40685cf4319"


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


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


def _alembic_stamp_head() -> None:
    from alembic import command

    command.stamp(_alembic_config(), "head")


def _alembic_stamp_baseline_then_upgrade_head() -> None:
    from alembic import command

    cfg = _alembic_config()
    command.stamp(cfg, _BASELINE_REVISION)
    command.upgrade(cfg, "head")


def _alembic_upgrade_head() -> None:
    from alembic import command

    command.upgrade(_alembic_config(), "head")


async def init_db() -> None:
    """Create/migrate the schema, then bring it to Alembic's latest head.

    Schema changes going forward are Alembic migrations under alembic/
    (see CLAUDE.md), not hand-rolled ALTER TABLE checks here. Three cases:

      - Fresh DB (every pytest run, and any brand-new install): create the
        full current schema directly from the ORM models — fast, no need
        to replay migration history step by step — then stamp so Alembic
        considers it fully migrated. This only stays correct as long as
        models/db.py and the latest migration describe the same schema.
      - Pre-existing DB with no alembic_version table: a database that
        predates this project using Alembic. Its schema already matches
        (or was hand-migrated via the old ad-hoc ALTER TABLE/CREATE INDEX
        checks this replaced to match) what the baseline migration
        produces — stamp to *baseline*, not head, so we don't try to
        re-create tables/columns/indexes that already exist, then run a
        normal upgrade so anything after baseline (e.g. the ensure_ascii
        backfill) still actually executes once for this DB instead of
        being silently skipped.
      - Already alembic-managed: apply anything newer than what's recorded.
    """
    engine = get_engine()
    is_sqlite = engine.url.get_backend_name().startswith("sqlite")

    async with engine.begin() as conn:
        if is_sqlite:
            # WAL lets readers (2s UI polling) run concurrently with writers
            # (per-sample upserts) instead of blocking on a whole-db lock.
            # journal_mode is persistent (stored in the db file); setting it
            # once at boot is enough. Per-connection busy waiting comes from
            # the engine connect_args timeout above.
            await conn.execute(text("PRAGMA journal_mode=WAL"))

    if not is_sqlite:
        await asyncio.to_thread(_alembic_upgrade_head)
        return

    async with engine.begin() as conn:
        existing = (
            await conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('batches', 'alembic_version')"
                )
            )
        ).fetchall()
    names = {row[0] for row in existing}

    if not names:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await asyncio.to_thread(_alembic_stamp_head)
    elif "alembic_version" not in names:
        await asyncio.to_thread(_alembic_stamp_baseline_then_upgrade_head)
    else:
        await asyncio.to_thread(_alembic_upgrade_head)


async def reset_db_for_tests() -> None:
    """Drop all and recreate. ONLY for tests."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
