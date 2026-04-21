# src/services/order_service.py
#
# Business logic for Order CRUD and state machine transitions.
#
# All functions are pure Python — no FastAPI imports, no HTTP concepts.
# The AsyncSession is passed in by the caller (route handler, Celery task,
# or test fixture). Cache invalidation is performed here, not in the route layer.
#
# Nova's agent tools call these functions directly. Function signatures are
# the API contract for the agent layer — treat them as stable.
#
# State machine (enforced in update_order_status — nowhere else):
#   PENDING    → PREPARING  (Celery worker picks up the task)
#   PREPARING  → READY      (Celery worker completes)
#   PENDING    → FAILED     (DLQ handler on irrecoverable failure)
#   PREPARING  → FAILED     (DLQ handler on irrecoverable failure)
# Any other transition raises ValueError with the full context.

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.cache import invalidate_order_status_cache, set_cached_order_status
from src.models.meal import Meal
from src.models.order import Order, OrderStatus
from src.models.order_item import OrderItem
from src.schemas.order import OrderCreate, OrderItemRead, OrderRead
from src.tasks.kitchen import process_order

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid state machine transitions.
# Checked in update_order_status — any transition not in this map is illegal.
# ---------------------------------------------------------------------------
_VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PREPARING, OrderStatus.FAILED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.FAILED},
    OrderStatus.READY: set(),
    OrderStatus.FAILED: set(),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_order_read(order: Order) -> OrderRead:
    """Construct an `OrderRead` from an ORM `Order` with items eagerly loaded.

    Populates `meal_name` and `price_each` on each `OrderItemRead` from the
    eagerly-loaded `OrderItem.meal` relationship. Computes `total_price` as the
    sum of (price_each × quantity) across all line items.

    This function must only be called after the `items` and `items.meal`
    relationships have been eagerly loaded (via `selectinload`). Calling it on
    an order with unloaded relationships will raise a `MissingGreenlet` error
    in the async SQLAlchemy context.

    Args:
        order: An `Order` ORM object with `items` + `items.meal` loaded.

    Returns:
        A fully populated `OrderRead` schema.
    """
    item_reads: list[OrderItemRead] = []
    total: Decimal = Decimal("0.00")

    for item in order.items:
        meal_name: str | None = None
        price_each: Decimal | None = None

        if item.meal is not None:
            meal_name = item.meal.name
            # Meal.price is stored as Numeric(8,2) — ORM returns it as float
            # on some backends. Normalise to Decimal for consistent arithmetic.
            price_each = Decimal(str(item.meal.price))
            total += price_each * item.quantity

        item_reads.append(
            OrderItemRead(
                order_id=item.order_id,
                meal_id=item.meal_id,
                quantity=item.quantity,
                meal_name=meal_name,
                price_each=price_each,
            )
        )

    return OrderRead(
        id=order.id,
        customer_name=order.customer_name,
        status=order.status,
        items=item_reads,
        total_price=total if item_reads else None,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

async def create_order(db: AsyncSession, data: OrderCreate) -> OrderRead:
    """Create a new order and enqueue it for kitchen processing.

    Validates that every meal ID in `data.items` exists and is currently
    available (`is_available=True`). If any meal fails validation, raises
    `ValueError` with the specific meal ID and reason — no order is created.

    On success:
    - Persists the `Order` and all `OrderItem` rows in a single transaction.
    - Calls `process_order.delay(order_id)` to enqueue the Celery kitchen task.
    - Returns the full `OrderRead` with items and prices populated.

    Args:
        db:   An active async database session.
        data: Validated order creation payload (at least one item, guaranteed
              by `OrderCreate.items_must_not_be_empty`).

    Returns:
        An `OrderRead` schema representing the newly created order.

    Raises:
        ValueError: If any `meal_id` in `data.items` does not exist in the
            database, or if the meal exists but `is_available=False`.
    """
    # ── 1. Validate all meal IDs up front — fail fast before touching DB ─────
    # Collect unique meal IDs from the request.
    requested_meal_ids = {item.meal_id for item in data.items}

    result = await db.execute(
        select(Meal).where(Meal.id.in_(requested_meal_ids))
    )
    found_meals: dict[int, Meal] = {
        meal.id: meal for meal in result.scalars().all()
    }

    # Check existence and availability for every requested meal ID.
    for meal_id in requested_meal_ids:
        if meal_id not in found_meals:
            raise ValueError(
                f"Meal id={meal_id} does not exist. "
                f"Verify the meal ID against GET /meals before placing an order."
            )
        meal = found_meals[meal_id]
        if not meal.is_available:
            raise ValueError(
                f"Meal id={meal_id} ('{meal.name}') is currently unavailable. "
                f"It cannot be added to an order until staff marks it available again."
            )

    # ── 2. Create the Order row ───────────────────────────────────────────────
    order = Order(
        customer_name=data.customer_name,
        status=OrderStatus.PENDING,
    )
    db.add(order)
    # Flush to get the auto-generated order.id before creating OrderItems.
    await db.flush()

    # ── 3. Create OrderItem rows ──────────────────────────────────────────────
    for item_data in data.items:
        order_item = OrderItem(
            order_id=order.id,
            meal_id=item_data.meal_id,
            quantity=item_data.quantity,
        )
        db.add(order_item)

    await db.commit()
    logger.info(
        "Created order id=%d for customer='%s' with %d item(s)",
        order.id,
        order.customer_name,
        len(data.items),
    )

    # ── 4. Enqueue the kitchen task ───────────────────────────────────────────
    # Called after commit so the Celery worker sees the committed order in Postgres.
    # If Celery is unavailable, this raises — the order is already in PENDING state
    # in Postgres and can be requeued manually or picked up on worker restart.
    process_order.delay(order.id)
    logger.info("Enqueued kitchen task for order id=%d", order.id)

    # ── 5. Reload the order with relationships for the response ───────────────
    # The order was flushed/committed above; reload it with selectinload so
    # _build_order_read can populate meal_name and price_each without lazy I/O.
    reloaded = await db.execute(
        select(Order)
        .where(Order.id == order.id)
        .options(selectinload(Order.items).selectinload(OrderItem.meal))
    )
    order_with_items = reloaded.scalar_one()
    return _build_order_read(order_with_items)


async def get_order(db: AsyncSession, order_id: int) -> OrderRead | None:
    """Fetch a single order by primary key, with items and meal names.

    Args:
        db:       An active async database session.
        order_id: Primary key of the order to retrieve.

    Returns:
        An `OrderRead` schema (with items eagerly loaded) if the order exists,
        or `None` if no order with that ID is found.
    """
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).selectinload(OrderItem.meal))
    )
    order = result.scalar_one_or_none()
    if order is None:
        return None
    return _build_order_read(order)


async def list_orders(db: AsyncSession) -> list[OrderRead]:
    """Return all orders sorted by creation time, newest first.

    Each order includes its line items with meal names and prices populated.
    Results are always served from Postgres — the order list is not cached
    because status changes are frequent (Celery writes) and a stale list would
    mislead the customer or Nova's agent.

    Args:
        db: An active async database session.

    Returns:
        A list of `OrderRead` schemas, sorted descending by `created_at`.
    """
    result = await db.execute(
        select(Order)
        .order_by(Order.created_at.desc())
        .options(selectinload(Order.items).selectinload(OrderItem.meal))
    )
    orders = result.scalars().all()
    return [_build_order_read(order) for order in orders]


async def update_order_status(
    db: AsyncSession,
    order_id: int,
    new_status: OrderStatus,
) -> OrderRead:
    """Advance an order to a new status, enforcing the state machine.

    Called by the Celery kitchen worker — not by the route layer. The route
    layer does not expose a status-update endpoint to customers; status
    transitions are driven entirely by the kitchen worker.

    Valid transitions:
        PENDING    → PREPARING  (worker picks up the task)
        PREPARING  → READY      (worker completes)
        PENDING    → FAILED     (DLQ handler)
        PREPARING  → FAILED     (DLQ handler)

    Any other transition — including READY → anything, FAILED → anything,
    and backwards transitions — raises `ValueError` with the full context.

    On success, invalidates the `order:status:{id}` Redis cache key and sets
    a fresh cache entry so status-polling clients see the new value immediately.

    Args:
        db:         An active async database session.
        order_id:   Primary key of the order to update.
        new_status: The target status to transition to.

    Returns:
        The updated `OrderRead` schema with the new status.

    Raises:
        ValueError: If `order_id` does not exist in the database.
        ValueError: If the requested transition from the current status to
            `new_status` is not in the valid transition table.
    """
    result = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).selectinload(OrderItem.meal))
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise ValueError(
            f"Order id={order_id} does not exist. "
            f"Cannot update status to '{new_status.value}'."
        )

    current_status = order.status
    allowed_targets = _VALID_TRANSITIONS[current_status]

    if new_status not in allowed_targets:
        if allowed_targets:
            valid_str = ", ".join(s.value for s in sorted(allowed_targets, key=lambda s: s.value))
            raise ValueError(
                f"Cannot transition order id={order_id} from '{current_status.value}' "
                f"to '{new_status.value}'. "
                f"Valid transitions from '{current_status.value}': {valid_str}."
            )
        else:
            raise ValueError(
                f"Cannot transition order id={order_id} from '{current_status.value}' "
                f"to '{new_status.value}'. "
                f"'{current_status.value}' is a terminal state — no further transitions are allowed."
            )

    order.status = new_status
    await db.commit()

    logger.info(
        "Order id=%d status transition: %s → %s",
        order_id,
        current_status.value,
        new_status.value,
    )

    # Invalidate and refresh the order status cache so pollers see the new value.
    await invalidate_order_status_cache(order_id)
    await set_cached_order_status(order_id, new_status.value)

    # Re-fetch with selectinload to populate items and meal names for the response.
    # db.refresh() does not re-apply selectinload chains, so a fresh execute is
    # required to guarantee the relationships are present in async context.
    reloaded = await db.execute(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).selectinload(OrderItem.meal))
    )
    updated_order = reloaded.scalar_one()
    return _build_order_read(updated_order)
