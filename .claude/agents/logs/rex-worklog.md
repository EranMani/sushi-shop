# Rex — Worklog

## Session Index

| # | Commit | Status | Key Decision |
|---|--------|--------|--------------|
| 01 | `database-models` | ✅ Done | `ARRAY(String)` for tags, named `orderstatus` enum, `expire_on_commit=False`, `os.environ` for DATABASE_URL (settings.py deferred to Commit 05) |

---

## Session 01 — Commit 02: `database-models`

**Date:** 2026-04-16
**Task:** Build the full SQLAlchemy ORM schema — Meal, Ingredient, MealIngredient, Order, OrderItem — plus the async database layer in `src/core/database.py`.

### Task Brief

Five model files under `src/models/`, one core file. The models are the foundation that every other backend component builds on — Nova's tools, the services, the Alembic migrations. Getting the relationships right here avoids painful refactors later.

Constraints going in:
- Async SQLAlchemy with `asyncpg` — lazy loading is off the table (doesn't work in async context)
- Order state machine must be an enum with exactly four states: PENDING, PREPARING, READY, FAILED
- No raw SQL anywhere
- No `Any` in type hints

### Decisions Made

**1. `Meal.tags` stored as `ARRAY(String)` on Postgres.**
Tags are a simple list of strings (e.g., `["vegan", "spicy"]`). Options were: a separate `Tag` table (normalised), a JSON column, or a Postgres native array. A separate table adds join complexity for a field that is purely read-side filtering with no relational identity. JSON is less typed. `ARRAY(String)` is clean, native to Postgres, and SQLAlchemy handles it without ceremony. Fallback for non-Postgres test DBs (SQLite) is a concern — but the project is Postgres-only by design, so this is not a problem.

**2. `OrderStatus` enum defined in Python with `sqlalchemy.Enum(..., name="orderstatus")`.**
Giving the Postgres enum type an explicit `name="orderstatus"` prevents Alembic from generating anonymous enum names that collide or differ between migration runs. This is a well-known gotcha with SQLAlchemy + Alembic + Postgres enums.

**3. `MealIngredient` and `OrderItem` are explicit association objects, not pure `Table()` constructs.**
Both carry payload columns (`quantity_required`, `quantity`). Using `Table()` works for pure join tables, but the moment you add columns, you need a mapped class to access them. Using mapped classes from the start avoids a refactor when the service layer needs `meal_ingredient.quantity_required`.

**4. All relationships use `back_populates` (not `backref`).**
`backref` creates the reverse relationship implicitly, which makes the models harder to read and type. `back_populates` is explicit on both sides — clear, discoverable, and mypy-friendly.

**5. `AsyncSession` factory uses `expire_on_commit=False`.**
In async context, accessing attributes after `session.commit()` would trigger lazy I/O — which is not allowed. `expire_on_commit=False` means the objects stay usable after commit without triggering implicit I/O. Services that need fresh data after a commit must call `session.refresh()` explicitly — which is the correct pattern.

**6. `get_db` yields `AsyncSession` directly (not wrapped in a context manager inside the dependency).**
FastAPI's `Depends` handles the lifecycle. The session is created via `async_session_factory()`, yielded, and the `finally` block closes it. This is the standard FastAPI + SQLAlchemy async pattern.

**7. `updated_at` on Order uses `onupdate=func.now()`.**
This means the timestamp is updated at the database level on every UPDATE — not relying on the application to remember to set it.

### Self-Review Checklist

- [x] All models import without errors (verified by reading through imports)
- [x] `Meal.ingredients` navigable via `MealIngredient` association
- [x] `Order.items` navigable via `OrderItem` association
- [x] `OrderStatus` enum has all four states: PENDING, PREPARING, READY, FAILED
- [x] No `Any` in type hints
- [x] No raw SQL
- [x] `asyncpg` driver used in `database.py`
- [x] `expire_on_commit=False` set on session factory
- [x] `back_populates` used on both sides of every relationship
- [x] No circular imports (base imported first, models import base, no cross-model imports except through relationships)
- [x] `__init__.py` in `src/models/` exports all models so Alembic autogenerate can discover them

### Issues Found Mid-Task

**Cross-commit dependency — `database.py` vs `settings.py`:**
The commit protocol puts `settings.py` in Commit 05 (`core-dependencies`) but `database.py` in Commit 02. `database.py` needs a `DATABASE_URL` string to construct the engine. Resolution: `database.py` reads `DATABASE_URL` and `APP_ENV` directly from `os.environ` for now. Commit 05 will replace this with `get_settings()` when the Pydantic Settings class is built. This is noted inline in the file with a clear TODO comment so it does not get forgotten.

---

### 📋 Documentation Flags for Claude

**DECISIONS.md:**
- `Meal.tags as ARRAY(String)` — chose Postgres native array over a tags table or JSON; simpler for read-side filtering, no relational identity needed for tags
- `OrderStatus enum with explicit name="orderstatus"` — prevents Alembic anonymous enum collision on Postgres; always name your enums
- `expire_on_commit=False on AsyncSession` — required for async SQLAlchemy; objects must remain usable post-commit without triggering lazy I/O

**ARCHITECTURE.md:**
- New component: `src/models/` — SQLAlchemy ORM layer (Meal, Ingredient, MealIngredient, Order, OrderItem)
- New component: `src/core/database.py` — async engine, `AsyncSession` factory, `get_db` FastAPI dependency
- Data model relationships documented: Meal ↔ Ingredient (many-to-many via MealIngredient), Order ↔ Meal (many-to-many via OrderItem)

---

## Handoff Note → Claude (for routing to Nova when she starts)

**What I built:** Full SQLAlchemy ORM layer — five model files and the async database layer.

**Models:**
- `src/models/base.py` — `DeclarativeBase` subclass (`Base`)
- `src/models/meal.py` — `Meal` (id, name, description, price, tags, is_available)
- `src/models/ingredient.py` — `Ingredient` (id, name, unit, stock_quantity)
- `src/models/meal_ingredient.py` — `MealIngredient` join table with `quantity_required`
- `src/models/order.py` — `Order` with `OrderStatus` enum (PENDING/PREPARING/READY/FAILED)
- `src/models/order_item.py` — `OrderItem` join table with `quantity`
- `src/models/__init__.py` — exports all models for Alembic discovery

**Core:**
- `src/core/database.py` — `async_engine`, `async_session_factory`, `get_db`

**Key relationships Nova needs to know:**
- `meal.ingredients` → list of `MealIngredient` objects (each has `.ingredient` and `.quantity_required`)
- `meal.order_items` → back-reference from order items
- `order.items` → list of `OrderItem` objects (each has `.meal` and `.quantity`)

**I'm not done yet (Nova doesn't start from models alone).** Nova starts after Commit 05 (services). This note is for Claude's awareness of what the model layer provides.
