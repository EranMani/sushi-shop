# src/services/ingredient_service.py
#
# Business logic for Ingredient CRUD and stock management.
#
# All functions are pure Python — no FastAPI imports, no HTTP concepts.
# The AsyncSession is passed in by the caller (route handler or test fixture).
# Cache invalidation is performed here because ingredient stock changes affect
# meal availability, which flows through the `menu:all` cache.
#
# Nova's `check_ingredients` agent tool calls these functions directly.
# Function signatures are stable — treat them as the agent tool API contract.

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.cache import invalidate_menu_cache
from src.models.ingredient import Ingredient
from src.schemas.ingredient import IngredientCreate, IngredientRead

logger = logging.getLogger(__name__)


async def create_ingredient(db: AsyncSession, data: IngredientCreate) -> IngredientRead:
    """Create a new ingredient and persist it to the database.

    Invalidates the `menu:all` cache because the new ingredient may be
    linked to meals that are now differently available.

    Args:
        db:   An active async database session.
        data: Validated ingredient creation payload.

    Returns:
        An `IngredientRead` schema built from the newly created ORM object.

    Raises:
        sqlalchemy.exc.IntegrityError: If an ingredient with the same name already
            exists. The route layer catches this and returns 409.
    """
    ingredient = Ingredient(
        name=data.name,
        unit=data.unit,
        stock_quantity=data.stock_quantity,
    )
    db.add(ingredient)
    await db.commit()
    await db.refresh(ingredient)
    await invalidate_menu_cache()
    logger.info(
        "Created ingredient id=%d name='%s' unit='%s'",
        ingredient.id,
        ingredient.name,
        ingredient.unit,
    )
    return IngredientRead.model_validate(ingredient)


async def get_ingredient(db: AsyncSession, ingredient_id: int) -> IngredientRead | None:
    """Fetch a single ingredient by primary key.

    Args:
        db:            An active async database session.
        ingredient_id: Primary key of the ingredient to retrieve.

    Returns:
        An `IngredientRead` schema if found, or `None` if no ingredient with
        that ID exists.
    """
    result = await db.execute(
        select(Ingredient).where(Ingredient.id == ingredient_id)
    )
    ingredient = result.scalar_one_or_none()
    if ingredient is None:
        return None
    return IngredientRead.model_validate(ingredient)


async def list_ingredients(db: AsyncSession) -> list[IngredientRead]:
    """Return all ingredients ordered by name ascending.

    No caching applied here — ingredient lists are typically only queried by
    staff or admin operations, not on the hot menu-read path. The `menu:all`
    cache covers meal reads; ingredient lists go straight to Postgres.

    Args:
        db: An active async database session.

    Returns:
        List of `IngredientRead` schemas for all ingredients.
    """
    result = await db.execute(select(Ingredient).order_by(Ingredient.name))
    ingredients = result.scalars().all()
    return [IngredientRead.model_validate(i) for i in ingredients]


async def update_stock(
    db: AsyncSession,
    ingredient_id: int,
    new_quantity: Decimal,
) -> IngredientRead | None:
    """Replace the stock level of an existing ingredient.

    This is an absolute replacement — the new value becomes the current stock.
    It is not an increment. Callers that need to add to existing stock must
    read the current value first and compute the new total themselves
    (see IngredientStockUpdate schema for the documented contract).

    Invalidates the `menu:all` cache because a stock change may alter which
    meals are fulfillable — Nova's availability tool reads from Postgres, but
    a stale menu cache could serve outdated `is_available` state.

    Args:
        db:            An active async database session.
        ingredient_id: Primary key of the ingredient to update.
        new_quantity:  New absolute stock level in the ingredient's unit.

    Returns:
        An `IngredientRead` schema reflecting the updated stock level,
        or `None` if no ingredient with that ID exists.
    """
    result = await db.execute(
        select(Ingredient).where(Ingredient.id == ingredient_id)
    )
    ingredient = result.scalar_one_or_none()
    if ingredient is None:
        return None

    old_quantity = ingredient.stock_quantity
    ingredient.stock_quantity = new_quantity
    await db.commit()
    await db.refresh(ingredient)
    await invalidate_menu_cache()
    logger.info(
        "Updated stock for ingredient id=%d name='%s': %s -> %s %s",
        ingredient.id,
        ingredient.name,
        old_quantity,
        new_quantity,
        ingredient.unit,
    )
    return IngredientRead.model_validate(ingredient)
