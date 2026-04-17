# src/schemas/ingredient.py
#
# Pydantic v2 schemas for Ingredient request/response shapes.
#
# IngredientCreate     — body for POST /ingredients
# IngredientRead       — response shape for GET /ingredients and GET /ingredients/{id}
# IngredientStockUpdate — body for PATCH /ingredients/{id}/stock

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class IngredientCreate(BaseModel):
    """Request body for creating a new ingredient.

    `stock_quantity` defaults to 0.0 — ingredients are typically created
    before stock is received. A separate stock-update operation sets the
    initial (and subsequent) quantities.
    """

    name: str = Field(
        description="Name of the ingredient. Must be unique (e.g. 'salmon', 'nori sheet').",
        min_length=1,
        max_length=100,
    )
    unit: str = Field(
        description="Unit of measurement for stock quantities "
                    "(e.g. 'grams', 'pieces', 'ml'). Used in availability checks.",
        min_length=1,
        max_length=50,
    )
    stock_quantity: Decimal = Field(
        default=Decimal("0.00"),
        description="Current stock level, expressed in the ingredient's unit. "
                    "Defaults to 0 — stock is added via a separate update operation.",
        ge=0,
        decimal_places=2,
    )


class IngredientRead(BaseModel):
    """Response shape for a single ingredient.

    Built from an `Ingredient` ORM object — `from_attributes=True` is required.
    The `stock_quantity` is returned as Decimal to preserve the numeric
    precision stored in the database (`Numeric(10, 2)`).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Auto-incremented primary key of the ingredient.")
    name: str = Field(description="Name of the ingredient.")
    unit: str = Field(
        description="Unit of measurement (e.g. 'grams', 'pieces', 'ml')."
    )
    stock_quantity: Decimal = Field(
        description="Current stock level in the ingredient's unit. "
                    "The availability check compares this against "
                    "MealIngredient.quantity_required × order quantity."
    )


class IngredientStockUpdate(BaseModel):
    """Request body for updating the stock level of an existing ingredient.

    Only `stock_quantity` is mutable via this endpoint — name and unit
    changes are intentionally excluded (they require a separate admin
    operation to keep historical data consistent).

    The value replaces the current stock level entirely; it is not a delta.
    Callers that want to add to existing stock must read the current value
    first and compute the new total themselves.
    """

    stock_quantity: Decimal = Field(
        description="New absolute stock level, in the ingredient's unit. "
                    "This replaces the current value — it is not an increment.",
        ge=0,
        decimal_places=2,
    )
