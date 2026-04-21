# src/tasks/kitchen.py
#
# Celery kitchen worker task(s).
#
# This file is the Celery task module for the kitchen simulation.
# The `process_order` task advances an order through the state machine:
#   PENDING → PREPARING → READY
# If the task fails after exhausting retries, the DLQ handler sets the order
# to FAILED so the customer is not left waiting with no status update.
#
# NOTE: The task body is a stub in Commit 07. Full implementation is built in
# Commit 09 (`kitchen-worker`). The stub must exist now so that the import chain
#   celery_app.conf.include=["src.tasks.kitchen"]
# resolves without error during `celery_app.py` module load.

from src.core.celery_app import celery_app


@celery_app.task(name="kitchen.process_order")
def process_order(order_id: int) -> None:
    """Process a kitchen order through PENDING → PREPARING → READY.

    Called immediately after an order is created via `process_order.delay(order_id)`.
    The task is acknowledged only after completion (`task_acks_late=True`), so a
    worker crash mid-execution causes the task to be requeued rather than lost.

    Full implementation is in Commit 09. This stub allows the import chain to
    resolve cleanly so routes and services can call `process_order.delay()` now.

    Args:
        order_id: Primary key of the order to process.
    """
    pass  # implemented in Commit 09
