# src/services/meal_service.py
#
# Business logic for Meal CRUD operations.
#
# All functions are pure Python — no FastAPI imports, no HTTP concepts.
# The AsyncSession is passed in by the caller (route handler or test fixture).
# Cache invalidation is performed here, not in the route layer.
#
# Nova's agent tools call these functions directly. Function signatures are
# the API contract for the agent layer — treat them as stable.

from __future__ import annotations

import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.cache import (
    get_cached_menu,
    invalidate_menu_cache,
    set_cached_menu,
)
from src.models.meal import Meal
from src.schemas.meal import MealCreate, MealListResponse, MealRead

logger = logging.getLogger(__name__)


async def create_meal(db: AsyncSession, data: MealCreate) -> MealRead:
    """Create a new meal and persist it to the database.

    Invalidates the `menu:all` cache so the next list call reflects the new meal.

    Args:
        db:   An active async database session.
        data: Validated meal creation payload.

    Returns:
        A `MealRead` schema built from the newly created ORM object.

    Raises:
        sqlalchemy.exc.IntegrityError: If a meal with the same name already exists.
            The route layer is responsible for catching this and returning 409.
    """
    meal = Meal(
        name=data.name,
        description=data.description,
        price=data.price,
        tags=data.tags,
        is_available=data.is_available,
    )
    db.add(meal)
    await db.commit()
    await db.refresh(meal)
    await invalidate_menu_cache()
    logger.info("Created meal id=%d name='%s'", meal.id, meal.name)
    return MealRead.model_validate(meal)


async def get_meal(db: AsyncSession, meal_id: int) -> MealRead | None:
    """Fetch a single meal by primary key.

    Args:
        db:      An active async database session.
        meal_id: Primary key of the meal to retrieve.

    Returns:
        A `MealRead` schema if found, or `None` if no meal with that ID exists.
    """
    result = await db.execute(select(Meal).where(Meal.id == meal_id))
    meal = result.scalar_one_or_none()
    if meal is None:
        return None
    return MealRead.model_validate(meal)


async def list_meals(db: AsyncSession) -> MealListResponse:
    """Return all meals ordered by name ascending.

    Results are served from the Redis `menu:all` cache when available.
    On a cache miss, the database is queried and the result is stored in cache.

    Args:
        db: An active async database session (used only on cache miss).

    Returns:
        A `MealListResponse` containing all meals and the total count.
    """
    # Attempt cache hit first.
    cached = await get_cached_menu()
    if cached is not None:
        try:
            raw: list[dict[str, object]] = json.loads(cached)
            meals = [MealRead.model_validate(item) for item in raw]
            return MealListResponse(total=len(meals), meals=meals)
        except Exception as exc:
            # Corrupted cache entry — fall through to Postgres and rebuild.
            logger.warning("Failed to deserialise cached menu, rebuilding: %s", exc)

    result = await db.execute(select(Meal).order_by(Meal.name))
    meal_rows = result.scalars().all()
    meals = [MealRead.model_validate(m) for m in meal_rows]

    # Populate cache for the next call.
    # model_dump(mode="json") converts Decimal to float-compatible JSON values.
    await set_cached_menu([m.model_dump(mode="json") for m in meals])

    return MealListResponse(total=len(meals), meals=meals)


async def search_meals(db: AsyncSession, query: str) -> MealListResponse:
    """Full-text search over meal names and tags.

    Uses Postgres `to_tsvector` / `plainto_tsquery` for ranked, case-insensitive
    matching. The search vector combines the `name` column and the array-joined
    `tags` column so a query like "spicy" matches both meals named "Spicy Tuna"
    and meals tagged with "spicy".

    The FTS match is intentionally unranked for now — results are sorted by
    name ascending. A future enhancement could use `ts_rank` for relevance
    ordering if Nova's agent needs it.

    Args:
        db:    An active async database session.
        query: Free-text search string. Passed directly to `plainto_tsquery`
               which handles tokenisation and stemming. Empty or whitespace-only
               strings return an empty result rather than all meals.

    Returns:
        A `MealListResponse` containing matching meals and the total count.
    """
    stripped = query.strip()
    if not stripped:
        return MealListResponse(total=0, meals=[])

    # Build a combined tsvector from name (text) and tags (array → joined text).
    # array_to_string(tags, ' ') converts ["vegan", "spicy"] to "vegan spicy"
    # so it can participate in the tsvector.
    name_vector = func.to_tsvector("english", Meal.name)
    tags_vector = func.to_tsvector(
        "english",
        func.coalesce(func.array_to_string(Meal.tags, " "), ""),
    )
    combined_vector = name_vector.op("||")(tags_vector)
    ts_query = func.plainto_tsquery("english", stripped)

    stmt = (
        select(Meal)
        .where(combined_vector.op("@@")(ts_query))
        .order_by(Meal.name)
    )

    result = await db.execute(stmt)
    meal_rows = result.scalars().all()
    meals = [MealRead.model_validate(m) for m in meal_rows]
    return MealListResponse(total=len(meals), meals=meals)


async def get_meal_by_name(db: AsyncSession, name: str) -> MealRead | None:
    """Fetch a single meal by exact name match (case-sensitive).

    Provided for Nova's agent tools that may need to resolve a meal name
    to an ID before adding it to an order.

    Args:
        db:   An active async database session.
        name: Exact meal name to look up.

    Returns:
        A `MealRead` schema if found, or `None` if no meal with that name exists.
    """
    result = await db.execute(select(Meal).where(Meal.name == name))
    meal = result.scalar_one_or_none()
    if meal is None:
        return None
    return MealRead.model_validate(meal)
