# src/models/meal.py
#
# Meal ORM model.
# A meal is what the customer orders. It is composed of ingredients via
# the MealIngredient association table.

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base

if TYPE_CHECKING:
    from src.models.meal_ingredient import MealIngredient
    from src.models.order_item import OrderItem


class Meal(Base):
    """A menu item available for ordering.

    `tags` is a Postgres-native string array (e.g. ["vegan", "spicy", "raw"]).
    This avoids a separate Tag table for what is purely a read-side filter.
    `is_available` is the manual flag set by staff — independent of ingredient stock.
    Both checks (is_available AND stock) must pass before the agent can add a meal
    to an order.
    """

    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default="{}"
    )
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    ingredients: Mapped[list[MealIngredient]] = relationship(
        "MealIngredient",
        back_populates="meal",
        cascade="all, delete-orphan",
    )
    order_items: Mapped[list[OrderItem]] = relationship(
        "OrderItem",
        back_populates="meal",
    )
