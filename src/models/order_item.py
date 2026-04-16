# src/models/order_item.py
#
# OrderItem association table.
# Links an order to the meals it contains and records how many of each
# meal was ordered.
#
# Explicit mapped class (not a bare Table()) because `quantity` is a payload
# column that the order_service and Nova's tools need to read.

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base

if TYPE_CHECKING:
    from src.models.meal import Meal
    from src.models.order import Order


class OrderItem(Base):
    """A line item in an order.

    Represents: "quantity X of meal Y in order Z."
    The price at time of order is not captured here — that is a future
    enhancement (snapshot pricing). Currently the live Meal.price is used.
    """

    __tablename__ = "order_items"

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    meal_id: Mapped[int] = mapped_column(
        ForeignKey("meals.id", ondelete="RESTRICT"), primary_key=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    order: Mapped[Order] = relationship("Order", back_populates="items")
    meal: Mapped[Meal] = relationship("Meal", back_populates="order_items")
