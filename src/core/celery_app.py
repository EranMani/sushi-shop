# src/core/celery_app.py
#
# Celery application configuration.
#
# The Celery app is the entry point for all async task execution in the
# kitchen simulation. Redis is used as both the broker (task submission)
# and the result backend (task status tracking).
#
# Queue layout:
#   kitchen.orders  — primary queue; all kitchen tasks land here
#   kitchen.dlq     — dead letter queue; tasks that exhaust retries are
#                     routed here so they do not block the primary queue
#
# The actual kitchen task (process_order) is defined in src/tasks/kitchen.py
# and imported at application start. This file only configures the Celery app
# instance — importing it never triggers DB or task execution.
#
# Celery task design rules (per Rex's standards):
#   - task_acks_late=True: task is acknowledged AFTER completion, not on receipt.
#     If a worker crashes mid-execution, the task is requeued — no silent loss.
#   - task_reject_on_worker_lost=True: complements acks_late; ensures the task
#     is rejected (not lost) if the worker process is killed unexpectedly.
#   - max_retries=1 on kitchen tasks: one retry before dead-lettering. Orders
#     are not retried indefinitely — the customer is notified of FAILED status.

from __future__ import annotations

from celery import Celery

from src.core.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "sushi_shop",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)

celery_app.conf.update(
    # ── Task acknowledgement ──────────────────────────────────────────────────
    # Acknowledge tasks only after they complete (not when received).
    # Prevents silent task loss if a worker crashes mid-execution.
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # ── Serialisation ─────────────────────────────────────────────────────────
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # ── Timezone ──────────────────────────────────────────────────────────────
    timezone="UTC",
    enable_utc=True,

    # ── Queue routing ─────────────────────────────────────────────────────────
    # All tasks default to the kitchen.orders queue.
    # The DLQ (kitchen.dlq) receives tasks that exhaust retries.
    task_default_queue="kitchen.orders",
    task_queues={
        "kitchen.orders": {
            "exchange": "kitchen",
            "exchange_type": "direct",
            "routing_key": "kitchen.orders",
        },
        "kitchen.dlq": {
            "exchange": "kitchen.dlq",
            "exchange_type": "direct",
            "routing_key": "kitchen.dlq",
        },
    },

    # ── Result expiry ─────────────────────────────────────────────────────────
    # Result backend entries expire after 1 hour. Task results are not the
    # source of truth — order status is read from Postgres, not from Celery.
    result_expires=3600,

    # ── Task autodiscovery ────────────────────────────────────────────────────
    # Register the kitchen task module so Celery can find process_order.
    include=["src.tasks.kitchen"],
)
