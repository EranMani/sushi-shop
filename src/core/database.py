# src/core/database.py
#
# Async SQLAlchemy engine, session factory, and FastAPI dependency.
#
# All database access in this project goes through AsyncSession. Lazy loading
# is not available in async context — every relationship must be loaded
# explicitly using selectinload() or joinedload() in the query.
#
# NOTE: This file reads DATABASE_URL and APP_ENV directly from environment
# variables. In Commit 05, `settings.py` (Pydantic Settings) will be wired
# in and this direct os.getenv call will be replaced with get_settings().

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_database_url: str = os.environ["DATABASE_URL"]
_app_env: str = os.getenv("APP_ENV", "development")

# ─── Engine ───────────────────────────────────────────────────────────────────

async_engine = create_async_engine(
    _database_url,
    # Pool sizing: two replicas behind Nginx, default pool_size=5 each is fine
    # for development. Tune via env in production.
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # cheap liveness check before handing a connection to a caller
    echo=_app_env == "development",  # SQL logging in dev only
)

# ─── Session factory ──────────────────────────────────────────────────────────

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    # expire_on_commit=False: after session.commit(), ORM objects remain
    # accessible without triggering implicit I/O. Services that need fresh
    # data after a commit must call session.refresh(obj) explicitly.
)

# ─── FastAPI dependency ────────────────────────────────────────────────────────


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession for use as a FastAPI dependency.

    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_db)) -> ...:

    The session is closed in the finally block regardless of whether the
    route handler raises an exception. Rollback on error is the caller's
    responsibility (or handled by the service layer).
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
