# src/models/order.py
#
# Order ORM model and OrderStatus enum.
# The order is the central object in the system. Its status field is the
# state machine that the Celery kitchen workers drive forward.
#
# Valid transitions (enforced in order_service, NOT here at the ORM level):
#   PENDING → PREPARING   (worker picks up the task)
#   PREPARING → READY     (worker completes)
#   PENDING | PREPARING → FAILED  (DLQ handler)
#
# Any other transition raises ValueError in the service layer.

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base

if TYPE_CHECKING:
    from src.models.order_item import OrderItem


class OrderStatus(str, enum.Enum):
    """State machine states for an order.

    Inherits from str so that FastAPI/Pydantic can serialise it as a plain
    string in JSON responses without extra configuration.
    """

    PENDING = "PENDING"
    PREPARING = "PREPARING"
    READY = "READY"
    FAILED = "FAILED"


class Order(Base):
    """A customer order.

    `customer_name` is the only customer identifier in the current phase
    (no auth, no customer accounts). It is used for display and for the
    kitchen-ready notification.

    `status` starts as PENDING when the order is created. The Celery
    kitchen worker advances it to PREPARING and then READY. The DLQ
    handler sets it to FAILED if the worker cannot process it.

    `updated_at` is managed by the database via `onupdate=func.now()` —
    the application does not need to set it manually.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="orderstatus", create_type=True),
        nullable=False,
        default=OrderStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )
