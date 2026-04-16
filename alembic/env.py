# alembic/env.py
#
# Alembic environment configuration.
# Configured for async SQLAlchemy with asyncpg.
#
# The key pattern here is `run_async_migrations()` — Alembic's migration
# runner is synchronous by default, so we use `asyncio.run()` to bridge
# into the async engine. This is the official Alembic pattern for async drivers.
#
# Why we import from src.models here:
#   All model files must be imported before `target_metadata = Base.metadata`
#   is evaluated, otherwise their tables are not registered on the metadata
#   and Alembic's autogenerate will not see them. src/models/__init__.py
#   imports every model explicitly, so a single import is enough.

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Import Base (which has all models registered on its metadata via __init__.py)
from src.models import Base

# ─── Alembic Config object ────────────────────────────────────────────────────
# Gives access to the values in alembic.ini.
config = context.config

# Set up Python logging from the alembic.ini [loggers] section.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that Alembic uses to compare against the live DB.
# All five tables (meals, ingredients, meal_ingredients, orders, order_items)
# are registered on this metadata via src/models/__init__.py imports.
target_metadata = Base.metadata


# ─── Database URL ─────────────────────────────────────────────────────────────

def get_database_url() -> str:
    """Read the database URL from the environment.

    Raises a clear error if DATABASE_URL is not set — better than
    silently connecting to nothing or using a stale ini value.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Set it before running alembic commands, e.g.: "
            "DATABASE_URL=postgresql+asyncpg://sushi:sushi@localhost:5432/sushi alembic upgrade head"
        )
    return url


# ─── Offline migrations ───────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without a live DB).

    In offline mode, Alembic renders the migration SQL to stdout or a file.
    No database connection is made. Useful for generating DDL to review or
    hand to a DBA.

    We still read DATABASE_URL to set the dialect — this controls how SQL
    is rendered (e.g. Postgres-flavoured DDL, not SQLite).
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Compare server defaults so autogenerate catches server_default changes.
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ─── Online (async) migrations ────────────────────────────────────────────────

async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a sync-bridged context.

    Alembic's migration runner is synchronous — it uses `context.run_migrations()`
    which is a standard blocking call. The bridge pattern is:
      1. Create an AsyncEngine (asyncpg driver).
      2. Connect and get a raw sync-compatible connection via `.sync_connection`.
      3. Configure the Alembic context with that connection.
      4. Call `context.run_migrations()` inside the sync context.

    This is the officially documented Alembic pattern for async SQLAlchemy.
    See: https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic
    """
    url = get_database_url()
    connectable: AsyncEngine = create_async_engine(url, echo=False)

    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations_with_connection)

    await connectable.dispose()


def _run_migrations_with_connection(sync_connection) -> None:  # type: ignore[no-untyped-def]
    """Configure Alembic context and run migrations on a sync connection.

    Called inside `run_async_migrations()` via `connection.run_sync()`.
    This is the synchronous half of the async bridge — `context.run_migrations()`
    must be called here, not in the async context.

    The `sync_connection` argument has no stub type that Alembic exposes publicly,
    hence the `# type: ignore` on the signature. The runtime type is
    `sqlalchemy.engine.Connection`.
    """
    context.configure(
        connection=sync_connection,
        target_metadata=target_metadata,
        # Compare server defaults so autogenerate catches server_default changes.
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Entry point for online migration mode.

    Bridges from Alembic's synchronous runner into asyncio.
    Called by Alembic when running `alembic upgrade` or `alembic downgrade`.
    """
    asyncio.run(run_async_migrations())


# ─── Dispatch ─────────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
