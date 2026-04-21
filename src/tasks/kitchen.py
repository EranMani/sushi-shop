# src/tasks/kitchen.py
#
# Celery kitchen worker task(s).
#
# This file is the Celery task module for the kitchen simulation.
# The `process_order` task advances an order through the state machine:
#   PENDING → PREPARING → READY
#
# If the task fails after exhausting retries (max_retries=1), the DLQ handler
# sets the order to FAILED so the customer is not left waiting with no status
# update. DLQ routing and FAILED handling are implemented in Commit 10.
#
# ── Async bridge ──────────────────────────────────────────────────────────────
#
# Celery tasks run in a sync worker process with no event loop. The business
# logic (`update_order_status`) is async. The bridge pattern used here:
#
#   1. `process_order` is a regular `def` function (required by Celery).
#   2. The entire async body is factored into `_async_process_order`, an
#      `async def` coroutine that manages its own `AsyncSession`.
#   3. `asyncio.run(_async_process_order(order_id))` is called once, creating a
#      single event loop for the full task lifetime — two status transitions,
#      one session, one loop. This is cheaper and safer than calling
#      `asyncio.run()` twice (once per transition).
#
# ── Idempotency ───────────────────────────────────────────────────────────────
#
# If the task is retried after a partial execution (e.g. worker crash after
# PENDING → PREPARING but before PREPARING → READY), calling
# `update_order_status(db, order_id, PREPARING)` a second time would raise
# `ValueError` because PREPARING is a terminal state for that transition.
#
# Guard: read the current status before each transition and skip any transition
# that has already been applied. This makes the task safe to retry at any point.
#
# ── Session management ────────────────────────────────────────────────────────
#
# The Celery worker does not have FastAPI's `get_db` dependency injection.
# Sessions are created manually via `async_session_factory` from `src.core.database`.

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select

from src.core.celery_app import celery_app
from src.core.database import async_session_factory
from src.core.settings import get_settings
from src.models.order import Order, OrderStatus
from src.services.order_service import update_order_status

logger = logging.getLogger(__name__)


async def _async_process_order(order_id: int) -> None:
    """Async body of the kitchen task — runs inside `asyncio.run()`.

    Advances the order through PENDING → PREPARING → READY, with a configurable
    simulated prep time between the two transitions.

    Each transition is guarded by a current-status check so the function is safe
    to call on retry after a partial execution:
    - If the order is already PREPARING (first transition completed on a prior
      attempt), the PENDING → PREPARING step is skipped and we proceed directly
      to the prep-time sleep + PREPARING → READY.
    - If the order is already READY (both transitions completed), the function
      returns immediately without writing anything.

    Args:
        order_id: Primary key of the order to process.

    Raises:
        ValueError: Propagated from `update_order_status` if the order does not
            exist or an invalid transition is attempted. The caller (`process_order`)
            re-raises to trigger Celery retry/DLQ routing.
    """
    settings = get_settings()
    prep_time: int = settings.kitchen_prep_time_seconds

    async with async_session_factory() as db:
        # ── Step 1: PENDING → PREPARING ───────────────────────────────────────
        # Read the current status to determine whether this transition is still
        # needed (idempotency guard for retries).
        result = await db.execute(select(Order.status).where(Order.id == order_id))
        current_status: OrderStatus | None = result.scalar_one_or_none()

        if current_status is None:
            raise ValueError(
                f"Order id={order_id} not found in the database. "
                f"Cannot process a kitchen task for a non-existent order."
            )

        if current_status == OrderStatus.READY:
            logger.info(
                "Order id=%d is already READY — kitchen task is a no-op (idempotent retry).",
                order_id,
            )
            return

        if current_status == OrderStatus.PENDING:
            logger.info(
                "Kitchen task: transitioning order id=%d PENDING → PREPARING.", order_id
            )
            await update_order_status(db, order_id, OrderStatus.PREPARING)
            logger.info(
                "Order id=%d transitioned to PREPARING. Starting prep (sleep %ds).",
                order_id,
                prep_time,
            )
        else:
            # Already PREPARING — first transition must have completed on a prior attempt.
            logger.info(
                "Order id=%d is already PREPARING (retry path). "
                "Skipping PENDING → PREPARING and proceeding to prep sleep.",
                order_id,
            )

        # ── Simulate kitchen prep time ─────────────────────────────────────────
        # asyncio.sleep is used here (not time.sleep) because this coroutine runs
        # inside an asyncio event loop. time.sleep would block the loop thread,
        # preventing any other coroutines from running during the wait.
        await asyncio.sleep(prep_time)

        # ── Step 2: PREPARING → READY ─────────────────────────────────────────
        logger.info(
            "Kitchen task: transitioning order id=%d PREPARING → READY.", order_id
        )
        await update_order_status(db, order_id, OrderStatus.READY)
        logger.info(
            "Order id=%d transitioned to READY. Kitchen task complete.", order_id
        )


@celery_app.task(
    name="kitchen.process_order",
    bind=True,
    max_retries=1,
    default_retry_delay=10,
    # task_acks_late and task_reject_on_worker_lost are set globally in celery_app.py.
    # Repeating them here as a reminder: this task is acknowledged only after it
    # completes, so a worker crash mid-execution causes requeue rather than silent loss.
)
def process_order(self: Any, order_id: int) -> None:
    """Process a kitchen order through PENDING → PREPARING → READY.

    This is a synchronous Celery task. `bind=True` is used so that `self`
    (the Celery Task instance) is available for `self.retry()` — the only safe
    and unambiguous way to trigger retry from inside the task body without
    relying on the module-level name being resolved at call time.

    `self` is typed `Any` because Celery's Task class requires importing from
    celery internals just for the annotation. `bind=True` guarantees `self` is
    a `celery.app.task.Task` instance at runtime.

    All async work (DB access, cache writes, status transitions) is executed via
    `asyncio.run(_async_process_order(...))`, which creates a single event loop
    for the full task lifetime.

    The task is idempotent: if it is retried after a partial execution, status
    transitions that already succeeded are detected and skipped.

    Retry policy:
    - `max_retries=1` — one retry on unhandled exception before the task is
      routed to the DLQ by Commit 10's failure handler.
    - `default_retry_delay=10` — 10-second backoff before the retry attempt.

    Args:
        self:     Celery Task instance (injected by `bind=True`).
        order_id: Primary key of the order to process.
    """
    start = time.monotonic()
    logger.info("Kitchen worker received task for order id=%d", order_id)

    try:
        asyncio.run(_async_process_order(order_id))
    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "Kitchen task failed for order id=%d after %.2fs: %s",
            order_id,
            elapsed,
            exc,
            exc_info=True,
        )
        # Re-raise to trigger Celery's retry machinery.
        # `self.retry(exc=exc)` always raises `celery.exceptions.Retry`, so the
        # outer `raise` is a safety net only — the retry machinery handles propagation.
        # After max_retries=1, the exception propagates to the failure handler
        # (Commit 10) which routes the task to kitchen.dlq and sets the order
        # status to FAILED.
        raise self.retry(exc=exc)

    elapsed = time.monotonic() - start
    logger.info(
        "Kitchen task completed for order id=%d in %.2fs", order_id, elapsed
    )
