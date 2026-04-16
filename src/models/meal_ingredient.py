# src/models/meal_ingredient.py
#
# MealIngredient association table.
# Links meals to their ingredients and records how much of each ingredient
# is required per single serving of the meal.
#
# This is an explicit mapped class (not a bare Table()) because the payload
# column `quantity_required` must be accessible from service code and from
# Nova's availability-check tool.

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base

if TYPE_CHECKING:
    from src.models.ingredient import Ingredient
    from src.models.meal import Meal


class MealIngredient(Base):
    """Association between a Meal and an Ingredient.

    `quantity_required` is the amount of the ingredient consumed per
    single serving of this meal, expressed in the ingredient's own unit.
    For example: Salmon Nigiri requires 30 grams of salmon per piece.

    The availability check is:
        ingredient.stock_quantity >= quantity_required * order_item.quantity
    """

    __tablename__ = "meal_ingredients"

    meal_id: Mapped[int] = mapped_column(
        ForeignKey("meals.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[int] = mapped_column(
        ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True
    )
    quantity_required: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False
    )

    # Relationships
    meal: Mapped[Meal] = relationship("Meal", back_populates="ingredients")
    ingredient: Mapped[Ingredient] = relationship(
        "Ingredient", back_populates="meal_ingredients"
    )
