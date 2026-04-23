# src/tasks/kitchen.py
#
# Celery kitchen worker tasks.
#
# Two tasks are defined here:
#
#   process_order  — primary task on kitchen.orders; advances an order through
#                    PENDING → PREPARING → READY; retried once on failure before
#                    the DLQ failure path fires.
#
#   order_failed   — DLQ tombstone task on kitchen.dlq; receives the order ID
#                    and error reason after process_order exhausts its retries;
#                    logs the permanent failure; no side effects (order status is
#                    already set to FAILED by the on_failure hook before this task
#                    is dispatched).
#
# ── Async bridge ──────────────────────────────────────────────────────────────
#
# Celery tasks run in a sync worker process with no event loop. The business
# logic (`update_order_status`) is async. The bridge pattern used here:
#
#   1. The Celery task function is a regular `def` (required by Celery).
#   2. All async work is factored into a private `async def` coroutine that
#      manages its own `AsyncSession`.
#   3. `asyncio.run(<coroutine>)` is called once per logical operation, creating
#      one event loop for the full operation lifetime.
#
# ── Failure path (Commit 10) ──────────────────────────────────────────────────
#
# When process_order raises an unhandled exception:
#   1. Celery retries once (max_retries=1, delay=10s).
#   2. If the retry also fails, Celery calls KitchenTask.on_failure.
#   3. on_failure sets the order status to FAILED in Postgres via
#      _async_set_order_failed (same asyncio.run() bridge pattern).
#   4. on_failure dispatches a kitchen.order_failed tombstone to kitchen.dlq.
#
# on_failure must NOT call self.retry() — it fires after retries are exhausted.
# on_failure must NOT re-raise exceptions — re-raising from on_failure is
# undefined behaviour in Celery and would produce a secondary unhandled failure.
#
# ── Idempotency ───────────────────────────────────────────────────────────────
#
# If the task is retried after a partial execution (e.g. worker crash after
# PENDING → PREPARING but before PREPARING → READY), calling
# `update_order_status(db, order_id, PREPARING)` a second time would raise
# `ValueError` because the transition is no longer valid.
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

from celery import Task
from sqlalchemy import select

from src.core.celery_app import celery_app
from src.core.database import async_session_factory
from src.core.settings import get_settings
from src.models.order import Order, OrderStatus
from src.services.order_service import update_order_status

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

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


async def _async_set_order_failed(order_id: int) -> None:
    """Set an order's status to FAILED in Postgres — async body of the DLQ handler.

    Runs inside `asyncio.run()` from `KitchenTask.on_failure`. Opens its own
    `AsyncSession` — completely independent of the session used by the original
    `process_order` task (that session is long closed by the time on_failure fires).

    Wraps the `update_order_status` call in a try/except because the most likely
    exception at this point is a duplicate FAILED transition: if on_failure was
    called on a retry that itself followed a prior on_failure execution, the order
    may already be FAILED. In that case the state machine raises ValueError, which
    is caught and logged here. The order is already in the correct state — no
    further action is needed.

    Args:
        order_id: Primary key of the order to mark as FAILED.
    """
    async with async_session_factory() as db:
        try:
            await update_order_status(db, order_id, OrderStatus.FAILED)
            logger.error(
                "Order id=%d marked as FAILED in Postgres (DLQ handler).", order_id
            )
        except ValueError as exc:
            # Most likely: order is already FAILED from a prior on_failure call.
            # Log and continue — the state is already correct.
            logger.error(
                "Could not set order id=%d to FAILED — state machine rejected the "
                "transition (order may already be in a terminal state): %s",
                order_id,
                exc,
            )
        except Exception as exc:
            # Unexpected DB error. Log at ERROR — the DLQ tombstone will still be
            # dispatched so monitoring has a record even if the DB write failed.
            logger.error(
                "Unexpected error setting order id=%d to FAILED in Postgres: %s",
                order_id,
                exc,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# KitchenTask — Task subclass with on_failure hook
# ---------------------------------------------------------------------------

class KitchenTask(Task):
    """Celery Task subclass that overrides `on_failure` for the kitchen worker.

    Subclassing `Task` and setting `base=KitchenTask` on the `process_order`
    decorator is the official Celery mechanism for attaching lifecycle hooks to
    function-based tasks. Post-decoration attribute patching is fragile and
    undocumented; this approach is explicit and maintainable.

    `on_failure` fires after all retries are exhausted. It:
      1. Sets the order status to FAILED in Postgres.
      2. Dispatches a `kitchen.order_failed` tombstone to the `kitchen.dlq` queue.

    Both operations are wrapped in independent try/except blocks so a failure in
    step 1 does not prevent step 2. The tombstone is always dispatched even if
    the Postgres write fails, ensuring the DLQ has a record for monitoring.
    """

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: list[Any],
        kwargs: dict[str, Any],
        einfo: Any,  # celery.app.task.Context.einfo — typed Any to avoid importing Celery internals
    ) -> None:
        """Handle a permanently failed kitchen task.

        Called by Celery after `process_order` has exhausted its retry budget
        (max_retries=1). Must NOT call `self.retry()` and must NOT re-raise
        exceptions — re-raising from on_failure is undefined behaviour in Celery.

        Args:
            exc:     The exception that caused the final failure.
            task_id: Celery task UUID (for log correlation).
            args:    Positional arguments passed to the task. `args[0]` is the
                     `order_id` when called as `process_order.delay(order_id)`.
            kwargs:  Keyword arguments passed to the task. Used as a fallback if
                     `order_id` is not in `args` (e.g. `apply_async(kwargs={...})`).
            einfo:   Celery `ExceptionInfo` object (not used in this implementation
                     but required by the on_failure signature).
        """
        # Extract order_id from args (positional call) or kwargs (named call).
        order_id: int | None = args[0] if args else kwargs.get("order_id")

        logger.error(
            "Kitchen task FAILED permanently for order id=%s — task_id=%s, error: %s",
            order_id,
            task_id,
            exc,
        )

        if order_id is None:
            # Cannot identify the order — log and bail. Nothing useful to update.
            logger.error(
                "on_failure called with no resolvable order_id — "
                "args=%r, kwargs=%r. Cannot set order status to FAILED.",
                args,
                kwargs,
            )
            return

        # ── Step 1: Set order status to FAILED in Postgres ────────────────────
        try:
            asyncio.run(_async_set_order_failed(order_id))
        except Exception as db_exc:
            # asyncio.run() itself failed (e.g. event loop conflict). This is
            # unexpected in a Celery worker process (no running loop). Log at
            # ERROR and continue so the DLQ tombstone is still dispatched.
            logger.error(
                "asyncio.run() failed while setting order id=%d to FAILED: %s",
                order_id,
                db_exc,
                exc_info=True,
            )

        # ── Step 2: Dispatch tombstone to kitchen.dlq ─────────────────────────
        # The tombstone task (kitchen.order_failed) is routed to kitchen.dlq via
        # task_routes in celery_app.py. It carries the order_id and error reason
        # as a permanent audit record for monitoring tools.
        # str(exc) is used because Celery serialises task args as JSON — an
        # exception object is not JSON-serialisable.
        try:
            celery_app.send_task(
                "kitchen.order_failed",
                args=[order_id, str(exc)],
                queue="kitchen.dlq",
            )
            logger.error(
                "Dispatched DLQ tombstone for order id=%d to kitchen.dlq.", order_id
            )
        except Exception as dlq_exc:
            # DLQ dispatch failure must not mask the original failure or crash
            # the on_failure hook. Log and return.
            logger.error(
                "Failed to dispatch DLQ tombstone for order id=%d: %s",
                order_id,
                dlq_exc,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Kitchen tasks
# ---------------------------------------------------------------------------

@celery_app.task(
    name="kitchen.process_order",
    base=KitchenTask,
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
    a `KitchenTask` instance at runtime (which inherits from `celery.app.task.Task`).

    All async work (DB access, cache writes, status transitions) is executed via
    `asyncio.run(_async_process_order(...))`, which creates a single event loop
    for the full task lifetime.

    The task is idempotent: if it is retried after a partial execution, status
    transitions that already succeeded are detected and skipped.

    Failure path:
    - On any unhandled exception, `self.retry(exc=exc)` triggers a single retry
      after a 10-second delay (max_retries=1, default_retry_delay=10).
    - If the retry also fails, Celery invokes `KitchenTask.on_failure`, which
      sets the order to FAILED in Postgres and dispatches a tombstone to kitchen.dlq.

    Args:
        self:     KitchenTask instance (injected by `bind=True`).
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
        # After max_retries=1 is exhausted, KitchenTask.on_failure is invoked.
        raise self.retry(exc=exc)

    elapsed = time.monotonic() - start
    logger.info(
        "Kitchen task completed for order id=%d in %.2fs", order_id, elapsed
    )


@celery_app.task(name="kitchen.order_failed", queue="kitchen.dlq")
def order_failed(order_id: int, error: str) -> None:
    """DLQ tombstone task — permanent audit record for a failed kitchen order.

    This task is dispatched by `KitchenTask.on_failure` after `process_order`
    has exhausted its retry budget and the order status has been set to FAILED
    in Postgres. It is routed to the `kitchen.dlq` queue by `task_routes` in
    `celery_app.py`.

    This task has NO side effects. It does not update the order status (that is
    already done by on_failure before this task is dispatched). Its sole purpose
    is to create a durable record in the DLQ queue that monitoring and alerting
    tools can consume.

    Args:
        order_id: Primary key of the failed order.
        error:    String representation of the exception that caused the failure.
    """
    logger.error(
        "DLQ: order id=%d failed permanently and could not be recovered. "
        "Reason: %s",
        order_id,
        error,
    )
