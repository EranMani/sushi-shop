# src/models/ingredient.py
#
# Ingredient ORM model.
# Tracks what is in stock and how much. Stock quantity is the source of truth
# for availability checks — the agent reads this via ingredient_service.

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base

if TYPE_CHECKING:
    from src.models.meal_ingredient import MealIngredient


class Ingredient(Base):
    """A raw ingredient used in one or more meals.

    `stock_quantity` is tracked in `unit` units (e.g., 200 grams of salmon,
    10 sheets of nori). The availability check compares this against
    `MealIngredient.quantity_required` × order quantity.
    """

    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "grams", "pieces", "ml"
    stock_quantity: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0.0
    )

    # Relationships
    meal_ingredients: Mapped[list[MealIngredient]] = relationship(
        "MealIngredient",
        back_populates="ingredient",
        cascade="all, delete-orphan",
    )
