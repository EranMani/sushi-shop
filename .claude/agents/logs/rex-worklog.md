# Rex — Worklog

## Session Index

| # | Commit | Status | Key Decision |
|---|--------|--------|--------------|
| 01 | `database-models` | ✅ Done | `ARRAY(String)` for tags, named `orderstatus` enum, `expire_on_commit=False`, `os.environ` for DATABASE_URL (settings.py deferred to Commit 05) |
| 02 | `alembic-initial-migration` | ✅ Done | Hand-written migration (no autogenerate); `orderstatus` enum created as standalone Postgres type with `create_type=False` + explicit `.create()` / `.drop()` to survive table drops |

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

---

## Session 02 — Commit 03: `alembic-initial-migration`

**Date:** 2026-04-16
**Task:** Configure Alembic for async SQLAlchemy and write the initial schema migration by hand.

### Task Brief

No live database available, so this is a hand-written migration that replicates the ORM models exactly. The goal is a reviewable DDL record that Alembic can run against a fresh Postgres instance and produce the exact schema the models expect.

Files to produce:
- `alembic.ini` — Alembic CLI configuration (DB URL intentionally omitted, read from env)
- `alembic/env.py` — async bridge pattern (`run_async_migrations` + `run_sync`)
- `alembic/versions/0001_initial_schema.py` — all five tables + orderstatus enum
- `alembic/script.py.mako` — template for future `alembic revision` calls

### Decisions Made

**1. `alembic.ini` does not contain the database URL.**
The URL would be a credential. `env.py` reads `DATABASE_URL` from the environment at runtime and raises a clear `RuntimeError` if it is not set. This is safer than a placeholder that might accidentally be committed or used.

**2. Async bridge uses `connection.run_sync(_run_migrations_with_connection)` pattern.**
Alembic's `context.run_migrations()` is synchronous. The correct bridge is: create `AsyncEngine`, connect via `async with connectable.connect()`, then call `await connection.run_sync(...)` which executes a sync callable with a sync-compatible connection. This is the pattern documented in the official Alembic async cookbook.

**3. `orderstatus` Postgres enum handled with `create_type=False` + explicit `.create()` / `.drop()`.**
The problem with letting Alembic manage a named enum implicitly: it may or may not drop the type when the table referencing it is dropped, depending on version and context. The explicit pattern gives full control:
- `upgrade()`: creates the enum standalone before creating `orders`, so even if table creation fails the enum can be cleaned up independently.
- `downgrade()`: drops the enum after dropping `orders`, with `checkfirst=True` so it does not error if already absent.
This matches the ORM definition (`create_type=True` on the `Enum(...)` column — Alembic handles the creation coordination at the column level during ORM-driven DDL, but in migration files the explicit pattern is safer and more transparent).

**4. Imports go before module-level revision variables.**
PEP 8 requires module-level imports at the top. The `from __future__ import annotations` enables the `str | None` union syntax used in the revision identifiers on Python 3.12 (already the minimum version, so this is belt-and-suspenders).

**5. `downgrade()` drop order is reverse of `upgrade()` create order.**
Dropping order: `order_items` → `orders` → `meal_ingredients` → `meals` → `ingredients`. This is the only order that satisfies FK constraints without needing `CASCADE` on the drops themselves.

**6. No `alembic/versions/__init__.py` needed.**
Alembic loads migration files as standalone scripts, not as a Python package. Adding `__init__.py` would confuse Alembic's script loader. Left intentionally absent.

### Issues Found Mid-Task

**No existing `alembic.ini` or `alembic/env.py`.**
The commit protocol assumed these files existed (from a standard `alembic init`). They did not — the project had the `alembic/` directory in the spec but nothing on disk. Created them from scratch. This is not a problem; it is actually better — a clean `alembic init` output has comments and patterns that assume sync SQLAlchemy. Writing from scratch means the async pattern is correct from the start and there is no dead code to clean up.

**`script.py.mako` was also missing.**
Without this template, `alembic revision` fails. Added the standard Alembic mako template so future migration generation works correctly.

### Self-Review Checklist

- [x] `alembic.ini` — no credentials, correct `script_location`, correct `file_template`
- [x] `env.py` — `target_metadata = Base.metadata` set correctly
- [x] `env.py` — all models imported via `from src.models import Base` (which imports all model files)
- [x] `env.py` — async bridge uses `run_sync` pattern, not a bare `asyncio.run(context.run_migrations())`
- [x] `env.py` — `get_database_url()` raises clear `RuntimeError` if env var missing
- [x] `0001_initial_schema.py` — all five tables created
- [x] `meals.tags` — `postgresql.ARRAY(sa.String())` with `server_default="{}"`
- [x] `meals.is_available` — `Boolean`, `server_default=sa.text("true")`
- [x] `ingredients.stock_quantity` — `Numeric(10, 2)`, `server_default=sa.text("0")`
- [x] `meal_ingredients` — composite PK `(meal_id, ingredient_id)`, both FKs `ondelete="CASCADE"`
- [x] `orders.status` — `orderstatus` enum, `server_default="PENDING"`, `create_type=False`
- [x] `orders.created_at` / `updated_at` — `DateTime(timezone=True)`, `server_default=sa.text("now()")`
- [x] `order_items` — composite PK `(order_id, meal_id)`, `order_id` FK `CASCADE`, `meal_id` FK `RESTRICT`
- [x] `downgrade()` drops tables in correct reverse order
- [x] `downgrade()` explicitly drops the `orderstatus` enum after `orders` is dropped
- [x] `orderstatus_enum` created with `checkfirst=True` (safe to run twice), dropped with `checkfirst=True`
- [x] No `Any` in type hints (except the intentional `# type: ignore` on `_run_migrations_with_connection` parameter — documented inline)
- [x] No raw SQL — all DDL through `op.create_table()`, `op.drop_table()`, Alembic column/constraint objects

### 📋 Documentation Flags for Claude

**DECISIONS.md:**
- `Alembic async bridge pattern` — `env.py` uses `AsyncEngine` + `connection.run_sync()` (not deprecated `strategy="threadlocal"` or bare `asyncio.run()`); this is the officially documented pattern for SQLAlchemy 2.x async migrations
- `orderstatus enum explicit create/drop in migration` — using `create_type=False` + `.create()` / `.drop()` rather than letting Alembic infer enum lifecycle; prevents silent failures on partial upgrades and ensures clean downgrade path
- `alembic.ini has no database URL` — URL is read from `DATABASE_URL` env var at runtime; config file never contains credentials

**ARCHITECTURE.md:**
- New component: `alembic/` — migration layer; all schema changes tracked here; `env.py` is the async bridge between Alembic runner and the asyncpg engine
- New component: `alembic.ini` — CLI configuration (points to `alembic/` as `script_location`)
- Data flow addition: `alembic upgrade head` → `env.py` → `AsyncEngine (asyncpg)` → Postgres DDL

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
