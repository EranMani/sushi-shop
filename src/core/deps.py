# src/core/deps.py
#
# Shared FastAPI dependencies — the single home for all `Depends(...)` callables
# used across route handlers.
#
# Why a separate file?
# Route files import dependencies from here, not from each other. This prevents
# circular imports (routes/meals.py importing from routes/orders.py to get get_db)
# and gives every route a consistent, predictable import path.
#
# Usage in a route handler:
#   from src.core.deps import get_db
#   from sqlalchemy.ext.asyncio import AsyncSession
#   from fastapi import Depends
#
#   async def my_route(db: AsyncSession = Depends(get_db)) -> ...:

from src.core.database import get_db

__all__ = ["get_db"]
