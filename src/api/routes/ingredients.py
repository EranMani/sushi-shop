# src/api/routes/ingredients.py
#
# FastAPI route handlers for Ingredient resources.
#
# Routes are thin: validate via Pydantic schemas, delegate to
# ingredient_service, return responses. No business logic here.
#
# Endpoints:
#   POST   /ingredients                   — create a new ingredient
#   GET    /ingredients                   — list all ingredients
#   GET    /ingredients/{ingredient_id}   — get a single ingredient by ID
#   PATCH  /ingredients/{ingredient_id}/stock — update stock level

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, status

from src.core.deps import get_db
from src.schemas.ingredient import IngredientCreate, IngredientRead, IngredientStockUpdate
from src.services.ingredient_service import (
    create_ingredient,
    get_ingredient,
    list_ingredients,
    update_stock,
)

router = APIRouter(prefix="/ingredients", tags=["ingredients"])


@router.post(
    "",
    response_model=IngredientRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new ingredient",
)
async def create_ingredient_route(
    data: IngredientCreate,
    db: AsyncSession = Depends(get_db),
) -> IngredientRead:
    """Create a new ingredient entry in the database.

    Returns 409 if an ingredient with the same name already exists.
    """
    try:
        return await create_ingredient(db, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An ingredient named '{data.name}' already exists. "
                   f"Ingredient names must be unique.",
        )


@router.get(
    "",
    response_model=list[IngredientRead],
    summary="List all ingredients",
)
async def list_ingredients_route(
    db: AsyncSession = Depends(get_db),
) -> list[IngredientRead]:
    """Return all ingredients sorted by name ascending.

    Not cached — ingredient lists are an admin-facing operation,
    not on the hot customer read path.
    """
    return await list_ingredients(db)


@router.get(
    "/{ingredient_id}",
    response_model=IngredientRead,
    summary="Get a single ingredient by ID",
)
async def get_ingredient_route(
    ingredient_id: int,
    db: AsyncSession = Depends(get_db),
) -> IngredientRead:
    """Fetch a single ingredient by its integer primary key.

    Returns 404 if no ingredient with that ID exists.
    """
    ingredient = await get_ingredient(db, ingredient_id)
    if ingredient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingredient with id={ingredient_id} not found.",
        )
    return ingredient


@router.patch(
    "/{ingredient_id}/stock",
    response_model=IngredientRead,
    summary="Update the stock level of an ingredient",
)
async def update_stock_route(
    ingredient_id: int,
    data: IngredientStockUpdate,
    db: AsyncSession = Depends(get_db),
) -> IngredientRead:
    """Replace the current stock level of an ingredient.

    The new value is an absolute replacement — not an increment.
    Callers that want to add to existing stock must read the current value
    first (GET /ingredients/{id}) and compute the new total before calling
    this endpoint.

    Returns 404 if no ingredient with that ID exists.
    """
    updated = await update_stock(db, ingredient_id, data.stock_quantity)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ingredient with id={ingredient_id} not found.",
        )
    return updated
