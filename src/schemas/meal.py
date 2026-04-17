# src/schemas/meal.py
#
# Pydantic v2 schemas for Meal request/response shapes.
# These are the API contract — no business logic lives here.
#
# MealCreate   — body for POST /meals
# MealRead     — response shape for GET /meals and GET /meals/{id}
# MealListResponse — paginated (or full) list of meals

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MealCreate(BaseModel):
    """Request body for creating a new meal.

    All fields are required at creation time. Tags default to an empty list
    so callers do not have to supply them for meals with no categorisation.
    `is_available` defaults to True — a newly created meal is available unless
    explicitly marked otherwise.
    """

    name: str = Field(
        description="Display name of the meal. Must be unique across the menu.",
        min_length=1,
        max_length=200,
    )
    description: str | None = Field(
        default=None,
        description="Optional longer description shown to the customer.",
    )
    price: Decimal = Field(
        description="Price of a single serving, in the restaurant's currency. "
                    "Stored with two decimal places of precision.",
        gt=0,
        decimal_places=2,
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Searchable tags applied to this meal (e.g. 'vegan', 'spicy', 'raw'). "
                    "Used by the AI assistant to match customer requests.",
    )
    is_available: bool = Field(
        default=True,
        description="Staff-controlled availability flag. When False, the meal cannot "
                    "be added to an order regardless of ingredient stock.",
    )


class MealRead(BaseModel):
    """Response shape for a single meal.

    Built from a `Meal` ORM object — `from_attributes=True` is required.
    `price` is returned as a Decimal so JSON serialisation preserves precision
    (FastAPI will render it as a string or number depending on the client, but
    the schema contract is always Decimal, never float).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Auto-incremented primary key of the meal.")
    name: str = Field(description="Display name of the meal.")
    description: str | None = Field(
        description="Optional longer description. Null if not provided."
    )
    price: Decimal = Field(
        description="Price of a single serving, with two decimal places."
    )
    tags: list[str] = Field(
        description="Searchable tags. Empty list if none were assigned."
    )
    is_available: bool = Field(
        description="Whether this meal is currently available for ordering. "
                    "False means staff have disabled it — ingredient stock is checked separately."
    )


class MealListResponse(BaseModel):
    """Response shape for the full menu listing.

    Wraps a list of `MealRead` objects with a total count so callers
    do not need to measure the list themselves. A future pagination
    extension would add `page` and `page_size` fields here.
    """

    model_config = ConfigDict(from_attributes=True)

    total: int = Field(
        description="Total number of meals returned in this response."
    )
    meals: list[MealRead] = Field(
        description="Ordered list of meals. Sorted by name ascending by default."
    )
