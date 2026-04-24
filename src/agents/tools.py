# src/agents/tools.py
#
# Tool output schemas and tool function stubs for the LangGraph assistant.
#
# COMMIT 11: This file contains typed output schemas and stub implementations.
# The stubs return predictable dummy values so the graph can be compiled and
# branch-routing can be tested without a live database.
#
# COMMIT 12: search_meals, check_ingredients, find_substitutes will be replaced
# with real implementations that call Rex's service functions directly via
# async_session_factory.
#
# COMMIT 13: dispatch_order will be replaced with the real httpx POST /orders
# implementation.
#
# Schema design rationale:
# - MealResult is a standalone schema — NOT imported from src.schemas.meal.MealRead.
#   The agent tool output contract must be independent of Rex's service schema.
#   If Rex adds or removes fields from MealRead, my tool output is unaffected.
#   Both happen to have the same fields now, but the boundary is intentional.
# - AvailabilityResult returns `missing: list[str]` — ingredient NAMES, not IDs.
#   The agent's LLM needs to communicate to the customer which ingredients are
#   out of stock. Names are directly usable in natural language; IDs are not.
# - OrderResult returns `order_id: int` so the agent can report the order number
#   to the customer and the graph can store it in state.order_id.

from __future__ import annotations

from decimal import Decimal

from langchain_core.tools import tool
from pydantic import BaseModel, Field


# ─── Tool output schemas ───────────────────────────────────────────────────────


class MealResult(BaseModel):
    """A single meal returned by search_meals or find_substitutes.

    Structured output that the agent's LLM can reason about directly.
    Fields mirror the minimal information needed for the ordering flow:
    the ID (needed for subsequent tool calls), display name, description,
    price, tags (for explaining why a meal was suggested), and availability
    (for a final sanity check before dispatch).
    """

    id: int = Field(description="Primary key of the meal.")
    name: str = Field(description="Display name of the meal.")
    description: str | None = Field(
        default=None, description="Optional longer description of the meal."
    )
    price: Decimal = Field(description="Price per serving with two decimal places.")
    tags: list[str] = Field(
        default_factory=list,
        description="Searchable tags applied to this meal (e.g. 'vegan', 'spicy').",
    )
    is_available: bool = Field(
        description="Whether the meal is currently available for ordering."
    )


class AvailabilityResult(BaseModel):
    """Structured availability check result from check_ingredients.

    Returning `available: bool` alone was rejected because the agent's LLM
    needs to know WHICH ingredients are missing in order to:
    1. Explain to the customer why their meal isn't available.
    2. Make intelligent substitute suggestions (prefer meals that don't share
       the missing ingredient).

    `missing` contains ingredient names (not IDs) — the LLM can use them
    directly in natural language responses without a secondary lookup.
    """

    available: bool = Field(
        description="True if all required ingredients are in stock for this meal."
    )
    missing: list[str] = Field(
        default_factory=list,
        description="Names of ingredients that are out of stock. "
                    "Empty list when available=True.",
    )


class OrderResult(BaseModel):
    """Result of a successful order dispatch via dispatch_order.

    Contains the minimum information the agent needs to confirm the order
    to the customer: the order ID (for tracking) and the initial status
    (always PENDING at creation time).
    """

    order_id: int = Field(description="Primary key of the created order.")
    status: str = Field(
        description="Initial order status. Always 'PENDING' at creation time."
    )


# ─── Tool stubs (Commit 11) ────────────────────────────────────────────────────
# These stubs return typed dummy values so the graph compiles and branch-routing
# tests can be written against predictable data.
#
# Real implementations replace these in Commits 12 and 13.
# The function signatures and return types are FINAL — Commit 12 must not
# change them, only the body.


@tool
async def search_meals(query: str) -> list[MealResult]:
    """Search for meals matching the customer's natural language query.

    Uses Postgres full-text search over meal names and tags.
    Returns an empty list if no meals match.

    Args:
        query: Natural language search string from the customer
               (e.g., "spicy tuna roll", "vegan options", "salmon").

    Returns:
        List of matching MealResult objects. Empty list on no match.
    """
    # STUB — Commit 12 replaces this with:
    # async with async_session_factory() as db:
    #     response = await meal_service.search_meals(db, query)
    #     return [MealResult(...) for meal in response.meals]
    return [
        MealResult(
            id=1,
            name="Spicy Tuna Roll",
            description="Fresh tuna with spicy mayo and cucumber",
            price=Decimal("12.50"),
            tags=["spicy", "raw", "tuna"],
            is_available=True,
        )
    ]


@tool
async def check_ingredients(meal_id: int) -> AvailabilityResult:
    """Check whether all required ingredients for a meal are in stock.

    Queries the MealIngredient join table to get required quantities,
    then compares against current Ingredient.stock_quantity values.

    Args:
        meal_id: Primary key of the meal to check.

    Returns:
        AvailabilityResult with available=True if all ingredients are
        sufficiently stocked, or available=False with missing ingredient
        names if any are out of stock.
    """
    # STUB — Commit 12 replaces this with real ingredient stock checks:
    # async with async_session_factory() as db:
    #     meal_ingredients = await db.execute(
    #         select(MealIngredient).where(MealIngredient.meal_id == meal_id)
    #         .options(selectinload(MealIngredient.ingredient))
    #     )
    #     missing = [mi.ingredient.name for mi in ... if stock < required]
    #     return AvailabilityResult(available=len(missing) == 0, missing=missing)
    return AvailabilityResult(available=True, missing=[])


@tool
async def find_substitutes(meal_id: int) -> list[MealResult]:
    """Find available substitute meals for an unavailable meal.

    Searches for other available meals with overlapping tags to suggest
    alternatives that match the customer's preferences.

    Args:
        meal_id: Primary key of the unavailable meal to find substitutes for.

    Returns:
        List of substitute MealResult objects. Empty list if no substitutes found.
    """
    # STUB — Commit 12 replaces this with:
    # async with async_session_factory() as db:
    #     return await meal_service.find_substitutes(db, meal_id)
    return []


@tool
async def dispatch_order(
    meal_ids: list[int],
    quantities: list[int],
    customer_name: str,
) -> OrderResult:
    """Place a confirmed order by calling POST /orders via httpx.

    Uses httpx (not a direct service call) to maintain the same API contract
    as any external client and to stay decoupled from internal order creation
    logic. This means the agent respects the same validation, state machine,
    and Celery enqueue logic as any other order source.

    Args:
        meal_ids:      List of meal primary keys to include in the order.
        quantities:    Corresponding quantities for each meal_id.
                       Must be the same length as meal_ids.
        customer_name: Customer's name for the order record and kitchen notification.

    Returns:
        OrderResult with the created order_id and initial status ('PENDING').

    Raises:
        Exception: If the httpx call fails, returns with an error message
                   that the confirm_and_dispatch node can surface to the customer.
    """
    # STUB — Commit 13 replaces this with:
    # async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
    #     response = await client.post(
    #         f"{settings.api_base_url}/orders",
    #         json={"customer_name": customer_name, "items": [...]},
    #     )
    #     response.raise_for_status()
    #     data = response.json()
    #     return OrderResult(order_id=data["id"], status=data["status"])
    return OrderResult(order_id=999, status="PENDING")
