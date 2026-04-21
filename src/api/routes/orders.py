# src/api/routes/orders.py
#
# FastAPI route handlers for Order resources.
#
# Routes are thin: they validate via Pydantic schemas, delegate to
# order_service, and return responses. No business logic lives here.
#
# Endpoints:
#   POST  /orders             — create a new order (enqueues kitchen task)
#   GET   /orders             — list all orders, newest first
#   GET   /orders/{order_id}  — get a single order by ID
#
# Note: PATCH /orders/{order_id}/status is intentionally absent from the
# public API. Status transitions are driven exclusively by the Celery kitchen
# worker (via order_service.update_order_status). Exposing a status-update
# route to the customer or agent would allow illegal state transitions.

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db
from src.schemas.order import OrderCreate, OrderRead
from src.services.order_service import create_order, get_order, list_orders

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post(
    "",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
    summary="Place a new order",
)
async def create_order_route(
    data: OrderCreate,
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    """Place a new order for one or more meals.

    Validates that every meal ID in the request exists and is currently
    available. On success, the order is persisted and immediately enqueued
    for kitchen processing (PENDING status). Returns the created order with
    all line items and computed total price.

    Returns 422 if any meal ID is invalid or unavailable — the response
    `detail` field contains the specific meal ID and the reason for rejection.
    """
    try:
        return await create_order(db, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.get(
    "",
    response_model=list[OrderRead],
    summary="List all orders",
)
async def list_orders_route(
    db: AsyncSession = Depends(get_db),
) -> list[OrderRead]:
    """Return all orders sorted by creation time, newest first.

    Each order includes its line items with meal names and live prices.
    Results are always read from Postgres — the order list is not cached
    because kitchen status updates are frequent.
    """
    return await list_orders(db)


@router.get(
    "/{order_id}",
    response_model=OrderRead,
    summary="Get a single order by ID",
)
async def get_order_route(
    order_id: int,
    db: AsyncSession = Depends(get_db),
) -> OrderRead:
    """Fetch a single order by its integer primary key.

    Returns the order with all line items, meal names, and computed total price.
    Returns 404 if no order with that ID exists.
    """
    order = await get_order(db, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id={order_id} not found.",
        )
    return order
