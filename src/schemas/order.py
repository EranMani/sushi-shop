# src/schemas/order.py
#
# Pydantic v2 schemas for Order request/response shapes.
#
# OrderItemCreate  — one line item in an order creation request
# OrderCreate      — body for POST /orders (contains a list of OrderItemCreate)
# OrderItemRead    — one line item in an order response
# OrderRead        — full order response (with embedded items)
# OrderStatusUpdate — body for PATCH /orders/{id}/status (DLQ handler + internal use)
#
# The `OrderStatus` enum is imported from the ORM model rather than redefined here.
# Both the ORM layer and the schema layer share the same enum type — no risk of
# drift between database-level values and API-level values.

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.order import OrderStatus


class OrderItemCreate(BaseModel):
    """A single line item submitted as part of a new order.

    `meal_id` references the meal being ordered. The service layer validates
    that the meal exists and is available — the schema only enforces structure.
    `quantity` must be at least 1; ordering zero of something is not meaningful.
    """

    meal_id: int = Field(
        description="Primary key of the meal being ordered.",
        gt=0,
    )
    quantity: int = Field(
        description="Number of servings of this meal. Must be at least 1.",
        ge=1,
    )


class OrderCreate(BaseModel):
    """Request body for creating a new order.

    `customer_name` is the only customer identifier in the current phase —
    no auth, no customer accounts. It is used for display and for the
    kitchen-ready notification.

    `items` must contain at least one line item — an empty order is rejected
    at the schema level so the service layer never needs to handle that case.
    """

    customer_name: str = Field(
        description="Name of the customer placing the order. Used for display "
                    "and kitchen-ready notifications.",
        min_length=1,
        max_length=200,
    )
    items: list[OrderItemCreate] = Field(
        description="List of meals being ordered. Must contain at least one item.",
        min_length=1,
    )

    @model_validator(mode="after")
    def items_must_not_be_empty(self) -> "OrderCreate":
        """Reject orders with an empty items list.

        Pydantic's `min_length=1` on a `list` field handles this in v2,
        but the explicit validator provides a descriptive error message
        rather than the generic field constraint message.
        """
        if not self.items:
            raise ValueError(
                "An order must contain at least one item. "
                "Provide a non-empty 'items' list."
            )
        return self


class OrderItemRead(BaseModel):
    """A single line item in an order response.

    `meal_id` and `quantity` mirror what was submitted at creation time.
    The `order_id` is included so this schema can be used standalone
    (e.g. by Nova's tools) without needing the parent `OrderRead` context.

    `price_each` is the live meal price at the time this schema is serialised —
    it is not stored on the `OrderItem` row (snapshot pricing is a future
    enhancement). The service layer must populate this from the joined `Meal`.
    Because the service populates it from the ORM relationship, `from_attributes`
    is set to True, but `price_each` is optional (None if the meal was not
    eagerly loaded).
    """

    model_config = ConfigDict(from_attributes=True)

    order_id: int = Field(description="Primary key of the parent order.")
    meal_id: int = Field(description="Primary key of the meal on this line item.")
    quantity: int = Field(
        description="Number of servings of this meal in the order."
    )
    meal_name: str | None = Field(
        default=None,
        description="Display name of the meal. Populated when the meal relationship "
                    "is eagerly loaded; None otherwise.",
    )
    price_each: Decimal | None = Field(
        default=None,
        description="Live price of a single serving of this meal at response time. "
                    "Not stored on the order — populated from the Meal relationship. "
                    "None if the meal was not eagerly loaded.",
    )


class OrderRead(BaseModel):
    """Full order response, including embedded line items.

    Built from an `Order` ORM object with its `items` relationship eagerly
    loaded (via `selectinload`). `from_attributes=True` is required.

    `status` uses the shared `OrderStatus` enum (imported from `src.models.order`).
    Because `OrderStatus` inherits from `str`, FastAPI serialises it as a plain
    string in JSON — no additional configuration needed.

    `total_price` is a computed field: the sum of
    `item.price_each * item.quantity` across all items. It is populated by
    the service layer, not stored in the database.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Auto-incremented primary key of the order.")
    customer_name: str = Field(
        description="Name of the customer who placed the order."
    )
    status: OrderStatus = Field(
        description="Current state of the order in the kitchen state machine. "
                    "One of: PENDING, PREPARING, READY, FAILED."
    )
    items: list[OrderItemRead] = Field(
        description="Line items in this order. Requires the 'items' relationship "
                    "to be eagerly loaded on the ORM object."
    )
    total_price: Decimal | None = Field(
        default=None,
        description="Sum of (price_each × quantity) for all items. "
                    "Populated by the service layer when meal prices are available; "
                    "None if prices were not loaded.",
    )
    created_at: datetime = Field(
        description="UTC timestamp when the order was created. "
                    "Set by the database server on insert."
    )
    updated_at: datetime = Field(
        description="UTC timestamp of the last status update. "
                    "Managed by the database via onupdate=func.now()."
    )


class OrderStatusUpdate(BaseModel):
    """Request body for updating the status of an existing order.

    Used internally by the Celery kitchen worker (via the DLQ handler)
    and by any admin endpoint that needs to advance or fail an order manually.

    The valid state machine transitions are enforced in `order_service`,
    not here — the schema accepts any `OrderStatus` value and lets the
    service reject illegal transitions with a descriptive error.
    """

    status: OrderStatus = Field(
        description="New status for the order. Valid transitions are: "
                    "PENDING → PREPARING, PREPARING → READY, "
                    "PENDING | PREPARING → FAILED. "
                    "The service layer rejects any other transition."
    )
