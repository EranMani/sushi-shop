# src/api/routes/meals.py
#
# FastAPI route handlers for Meal resources.
#
# Routes are thin: they validate via Pydantic schemas, delegate to
# meal_service, and return responses. No business logic lives here.
#
# Endpoints:
#   POST   /meals                  — create a new meal
#   GET    /meals                  — list all meals (cached)
#   GET    /meals/search?q=        — full-text search over name + tags
#   GET    /meals/{meal_id}        — get a single meal by ID
#
# NOTE: GET /meals/search MUST be declared before GET /meals/{meal_id}.
# FastAPI matches routes in declaration order. If {meal_id} comes first,
# the literal path segment "search" is matched as an integer and fails
# with a 422 validation error instead of hitting the search route.

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.core.deps import get_db
from src.schemas.meal import MealCreate, MealListResponse, MealRead
from src.services.meal_service import (
    create_meal,
    get_meal,
    list_meals,
    search_meals,
)

router = APIRouter(prefix="/meals", tags=["meals"])


@router.post(
    "",
    response_model=MealRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new meal",
)
async def create_meal_route(
    data: MealCreate,
    db: AsyncSession = Depends(get_db),
) -> MealRead:
    """Create a new meal entry in the database.

    Returns 409 if a meal with the same name already exists.
    """
    try:
        return await create_meal(db, data)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A meal named '{data.name}' already exists. "
                   f"Meal names must be unique across the menu.",
        )


@router.get(
    "",
    response_model=MealListResponse,
    summary="List all meals",
)
async def list_meals_route(
    db: AsyncSession = Depends(get_db),
) -> MealListResponse:
    """Return all meals sorted by name ascending.

    Results are served from the Redis `menu:all` cache when available.
    Cache is rebuilt from Postgres on a miss and on every write operation.
    """
    return await list_meals(db)


@router.get(
    "/search",
    response_model=MealListResponse,
    summary="Full-text search over meals",
)
async def search_meals_route(
    q: str = Query(
        description="Search term. Matched against meal names and tags using "
                    "Postgres full-text search. Case-insensitive.",
        min_length=1,
    ),
    db: AsyncSession = Depends(get_db),
) -> MealListResponse:
    """Search meals by name and tags using Postgres FTS.

    Returns meals where the search term appears in the meal name or tags.
    An empty query (whitespace only) returns an empty result set — it does
    not fall back to returning all meals.
    """
    return await search_meals(db, q)


@router.get(
    "/{meal_id}",
    response_model=MealRead,
    summary="Get a single meal by ID",
)
async def get_meal_route(
    meal_id: int,
    db: AsyncSession = Depends(get_db),
) -> MealRead:
    """Fetch a single meal by its integer primary key.

    Returns 404 if no meal with that ID exists.
    """
    meal = await get_meal(db, meal_id)
    if meal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meal with id={meal_id} not found.",
        )
    return meal
