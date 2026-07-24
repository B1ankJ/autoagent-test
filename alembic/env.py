import asyncio

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from autoagent.models.db import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Deliberately skip logging.config.fileConfig(config.config_file_name)
# here (the Alembic-generated default). It defaults to
# disable_existing_loggers=True, which would silently disable every
# logger the app already configured (utils/logging.py::configure_logging)
# every time init_db() runs Alembic — a real bug, not just a test
# artifact, since init_db() runs at every boot. Alembic's own loggers
# still reach the console fine via normal propagation to the root
# logger's handler.
target_metadata = Base.metadata

# The app's DB path is only known at runtime (Settings.data_root), not a
# static ini value — default sqlalchemy.url to it so both the CLI
# (`alembic revision --autogenerate`, `alembic upgrade head`) and
# storage/database.py's programmatic invocation (via asyncio.to_thread,
# since this module's own asyncio.run() can't nest inside the caller's
# already-running loop) resolve to the same DB the app actually uses.
if not config.get_main_option("sqlalchemy.url"):
    from autoagent.config.settings import get_settings

    _db_path = get_settings().data_root / "db.sqlite"
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{_db_path}")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
