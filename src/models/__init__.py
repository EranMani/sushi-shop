# src/models/__init__.py
#
# Explicit re-exports of all ORM models.
#
# This file exists for two reasons:
#   1. Alembic's env.py imports `Base` from here and then relies on all
#      models having been registered on `Base.metadata` before autogenerate
#      runs. If a model file is never imported, its table is invisible to
#      Alembic. Importing everything here guarantees discovery.
#   2. Service and route modules can do `from src.models import Meal, Order`
#      rather than drilling into individual submodules.

from src.models.base import Base
from src.models.ingredient import Ingredient
from src.models.meal import Meal
from src.models.meal_ingredient import MealIngredient
from src.models.order import Order, OrderStatus
from src.models.order_item import OrderItem

__all__ = [
    "Base",
    "Ingredient",
    "Meal",
    "MealIngredient",
    "Order",
    "OrderItem",
    "OrderStatus",
]