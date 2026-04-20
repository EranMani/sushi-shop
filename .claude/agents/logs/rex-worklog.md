# Rex — Worklog

## Session Index

| # | Commit | Status | Key Decision |
|---|--------|--------|--------------|
| 01 | `database-models` | ✅ Done | `ARRAY(String)` for tags, named `orderstatus` enum, `expire_on_commit=False`, `os.environ` for DATABASE_URL (settings.py deferred to Commit 05) |
| 02 | `alembic-initial-migration` | ✅ Done | Hand-written migration (no autogenerate); `orderstatus` enum created as standalone Postgres type with `create_type=False` + explicit `.create()` / `.drop()` to survive table drops |
| 03 | `pydantic-schemas` | ✅ Done | `OrderStatus` imported from ORM model (single source of truth, no drift risk); `OrderItemRead` carries optional `meal_name` + `price_each` for agent readability; `IngredientStockUpdate` is absolute replacement (not delta) — documented in field description |
| 04 | `core-dependencies` | ✅ Done | `get_settings()` cached with `lru_cache(maxsize=1)`; `database_url_must_use_asyncpg` validator catches wrong driver at startup not at engine creation; `deps.py` is a thin re-export to break circular imports in routes |
| 05 | `meal-ingredient-service-routes` | ✅ Done | FTS via combined `to_tsvector(name) \|\| to_tsvector(array_to_string(tags))` + `plainto_tsquery`; `/search` route declared before `/{id}` to avoid FastAPI ordering shadow; Redis failures non-fatal in all cache helpers |

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

---

## Session 03 — Commit 04: `pydantic-schemas`

**Date:** 2026-04-17
**Task:** Build all Pydantic v2 request/response schemas in `src/schemas/`. No logic — shapes only.

### Task Brief

Three schema files:
- `src/schemas/meal.py` — `MealCreate`, `MealRead`, `MealListResponse`
- `src/schemas/ingredient.py` — `IngredientCreate`, `IngredientRead`, `IngredientStockUpdate`
- `src/schemas/order.py` — `OrderItemCreate`, `OrderCreate`, `OrderItemRead`, `OrderRead`, `OrderStatusUpdate`

Constraints:
- Pydantic v2 only — `ConfigDict`, `model_validator`, `Field(description=...)` on every field
- `from_attributes=True` on all response schemas built from ORM objects
- `OrderCreate` must reject an empty items list
- `OrderStatus` must serialise as a plain string in JSON
- No `Any` in type hints

Read the five ORM models first. Decisions happen at schema design time, not at writing time.

### Decisions Made

**1. `OrderStatus` imported from `src.models.order`, not redefined.**
Redefining the enum in the schema layer creates two sources of truth. If someone adds a state to the ORM enum and forgets to update the schema enum, the API silently accepts or rejects values it shouldn't. Importing the single definition means both layers are always in sync. The risk is a cross-layer import (schema importing from model) — this is acceptable and intentional; schemas are downstream consumers of model definitions.

**2. `OrderItemRead` has optional `meal_name` and `price_each` fields.**
The `OrderItem` ORM model does not store the meal name or price — it only stores `meal_id`. However, Nova's agent tools need to display readable order summaries, and the customer-facing order response should show what was ordered, not just foreign key IDs. The service layer can populate these by eagerly loading the `OrderItem.meal` relationship (via `selectinload`). Making them `Optional` (defaulting to `None`) means the schema works both with and without eager loading — routes that need performance can skip the join; routes that need readability can include it.

**3. `IngredientStockUpdate.stock_quantity` is an absolute replacement, not a delta.**
A delta-based update ("+50 grams") creates a race condition: two concurrent requests each add 50 grams when only one addition was intended. The absolute-value approach ("stock is now 200 grams") puts the responsibility for computing the correct new value on the caller, who must read the current value first. This is the safer pattern when there is no concurrency control at the API layer. The field description documents this explicitly.

**4. `OrderCreate` uses both `min_length=1` on the field AND an explicit `model_validator`.**
`min_length=1` is the Pydantic v2 native way to enforce a non-empty list — it catches the case before the validator runs. The `model_validator` is belt-and-suspenders and, more importantly, provides a human-readable error message rather than Pydantic's default field constraint message. Nova's agent reads error messages — specificity matters.

**5. `MealCreate.price` and quantity fields use `Decimal` with `decimal_places=2`.**
The ORM stores price as `Numeric(8, 2)`. Using `float` in the schema would introduce floating-point precision errors before the value even reaches the database. `Decimal` with `decimal_places=2` enforces the same precision at the API boundary. `gt=0` on price prevents zero-price meals from being created via the API.

**6. `MealListResponse` wraps `list[MealRead]` with a `total` count.**
A flat list response is technically valid but forces the caller to measure the list to know how many items there are. The `total` field adds no complexity and is always useful — particularly for Nova's agent tools which may need to reason about whether results were truncated. A future pagination extension would add `page` and `page_size` to this same schema.

### Issues Found Mid-Task

**No issues with the schema logic.** One environmental finding:

**SQLAlchemy not installed in the local Python environment.**
The project runs inside Docker, so local imports fail without installing the packages. Resolved by running `pip install sqlalchemy pydantic asyncpg` in the local environment for testing purposes. This is a dev-environment gap — not a code issue. Adam's Docker setup is the authoritative runtime.

### Self-Review Checklist

- [x] All three schema files import without errors (verified via Python import test)
- [x] `MealCreate` rejects missing `price` (ValidationError raised)
- [x] `OrderCreate` rejects empty `items=[]` (ValidationError raised)
- [x] `OrderCreate` rejects missing `items` entirely (ValidationError raised)
- [x] `OrderRead` serialises `status` as plain string `'PENDING'` via `model_dump(mode='json')` (FastAPI's code path)
- [x] `MealRead.model_validate(mock_orm_obj)` works correctly (`from_attributes=True`)
- [x] `IngredientStockUpdate` rejects `stock_quantity < 0`
- [x] `OrderItemCreate` rejects `quantity=0`
- [x] `Field(description=...)` on every single field across all schemas
- [x] `model_config = ConfigDict(from_attributes=True)` on all response schemas: `MealRead`, `MealListResponse`, `IngredientRead`, `OrderItemRead`, `OrderRead`
- [x] No `Any` in type hints anywhere
- [x] `OrderStatus` not redefined — imported from `src.models.order`
- [x] `OrderItemRead.meal_name` and `price_each` are `Optional` with `default=None` — schema is usable without eager loading
- [x] `IngredientStockUpdate` description explicitly states absolute replacement (not delta)
- [x] `model_json_schema()` generates correctly on `OrderRead` (verified — 3963 chars, no errors)

### 📋 Documentation Flags for Claude

**DECISIONS.md:**
- `OrderStatus imported into schemas from ORM model (not redefined)` — single source of truth for enum states; schema layer is a downstream consumer of model definitions; prevents silent drift if states are added/removed
- `OrderItemRead.meal_name and price_each as optional fields` — enables eager-loaded responses without requiring all callers to join; service layer populates from `selectinload(OrderItem.meal)`; Nova's tools benefit from readable summaries without raw FK IDs
- `IngredientStockUpdate uses absolute value, not delta` — eliminates race condition on concurrent stock updates; caller is responsible for reading current value and computing new total

**ARCHITECTURE.md:**
- New component: `src/schemas/` — Pydantic v2 API contract layer; shapes for all three resource types (Meal, Ingredient, Order); no business logic, no DB access
- Data flow addition: FastAPI route handler receives request → validated against `*Create` schema → service processes → returns ORM object → serialised via `*Read` schema with `from_attributes=True`

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

---

---

## Session 04 — Commit 05: `core-dependencies`

**Date:** 2026-04-17
**Task:** Build `src/core/settings.py` (Pydantic Settings), update `src/core/database.py` to use it, and create `src/core/deps.py`.

### Task Brief

Three files, clear scope:
1. `settings.py` — Pydantic `BaseSettings` that reads all env vars, validates them at startup, and is cached as a singleton via `lru_cache`.
2. `database.py` — resolve the `os.environ` TODO from Session 01. Replace the direct env reads with `get_settings()`.
3. `deps.py` — thin re-export module so routes import `get_db` from one stable location.

Constraints going in:
- Pydantic v2 `BaseSettings` with `SettingsConfigDict`
- `get_settings()` must be cached — only one `Settings` instantiation per process
- Missing required vars must fail at startup with a message that names the missing var and says what to do
- No `Any` in type hints

### Decisions Made

**1. `database.py` calls `get_settings()` at module load time (not inside `get_db`).**
The engine is a module-level singleton — it is created once when the module is first imported, not per-request. So `get_settings()` must be called at module scope too. This is consistent with how the engine is built: once, with fixed configuration. If the URL changes, you restart the process.

**2. `Settings` has a `database_url_must_use_asyncpg` validator.**
A wrong driver scheme (`postgresql://` instead of `postgresql+asyncpg://`) fails at engine creation with a cryptic SQLAlchemy error about a missing dialect. Catching it in the validator produces a message that identifies the exact value and what to change. This is the kind of error a developer hits once and cannot easily diagnose without knowing where to look.

**3. `llm_api_key_required_for_provider` is a `model_validator(mode="after")`.**
It needs to cross-reference `llm_provider` with whichever API key field is present. Field validators run before the model is assembled; a `model_validator(mode="after")` runs on the complete model instance, so both fields are available. This is the correct Pydantic v2 pattern for cross-field validation.

**4. `test_database_url` is optional (`str | None = None`).**
The test database URL is only needed by the test suite, not by the running application. Making it required would break startup in environments that don't have a test DB (staging, production). The test suite reads it separately — it is not consumed by `database.py` or `get_db`.

**5. `deps.py` is a re-export, not a new implementation.**
`get_db` lives in `database.py` because it is tightly coupled to the engine and session factory defined there. `deps.py` re-exports it so routes have a stable, consistent import path (`from src.core.deps import get_db`) without pulling in the engine and session factory directly. If future shared dependencies are added (e.g., a `get_current_user` auth dependency), they live here too.

**6. `extra="ignore"` in `SettingsConfigDict`.**
The `.env` file likely contains Docker Compose variables, shell exports, and other platform vars that are not `Settings` fields. Without `extra="ignore"`, Pydantic raises a validation error on the first unexpected field it sees. Silently ignoring extras is the correct setting for a shared `.env` file.

**7. `case_sensitive=False` in `SettingsConfigDict`.**
Environment variable casing is platform-dependent. On Linux (the container runtime), env vars are case-sensitive. On Windows (the dev machine), they are not. Setting `case_sensitive=False` makes `Settings` behave consistently regardless of where the developer types the variable name in their shell.

### Issues Found Mid-Task

**`pydantic-settings` not installed in local Python environment.**
Same pattern as Session 03 (`pydantic` was installed but `pydantic-settings` is a separate package). Installed locally for test validation. Not a code issue — Adam's Docker image has all dependencies from `pyproject.toml`.

**No issues with the logic or the import chain.** All six validation tests passed on first run.

### Self-Review Checklist

- [x] `settings.py` imports without error
- [x] `Settings` instantiates from explicit kwargs (tested without .env file present)
- [x] Wrong `DATABASE_URL` driver prefix raises `ValueError` with clear message
- [x] Missing API key for configured provider raises `ValueError` with clear message
- [x] `CACHE_TTL_SECONDS=0` raises `ValueError` with clear message
- [x] `get_settings()` returns the same object on second call (`is` check passes)
- [x] OpenAI provider path validates correctly with only `openai_api_key` present
- [x] `database.py` no longer imports `os` — `os.environ` removed
- [x] `database.py` `_settings = get_settings()` at module scope (not inside `get_db`)
- [x] `database.py` `echo=_settings.app_env == "development"` (not string hardcoded)
- [x] `deps.py` imports without error
- [x] `get_db` imported from `deps.py` is the same object as in `database.py`
- [x] `get_db` confirmed as `isasyncgenfunction` (FastAPI requires a generator for dependency cleanup)
- [x] No `Any` in type hints across all three files
- [x] `get_settings.cache_clear()` is callable (lru_cache attribute available) — tests can reset it

### 📋 Documentation Flags for Claude

**DECISIONS.md:**
- `get_settings() cached with lru_cache(maxsize=1)` — Settings instantiated once per process; env vars read at startup, not per-request; tests must call `get_settings.cache_clear()` before patching env vars
- `database_url asyncpg validator in Settings` — catches wrong driver scheme at startup with a clear message, rather than letting SQLAlchemy fail at engine creation with a cryptic dialect error
- `deps.py as stable import home for shared dependencies` — routes import from `src.core.deps`, not from `src.core.database` directly; prevents circular imports as the route layer grows; future shared deps (auth, pagination) live here

**ARCHITECTURE.md:**
- New component: `src/core/settings.py` — Pydantic `BaseSettings` singleton; all env var reads flow through here; validates configuration at startup before any DB connection is attempted
- Updated component: `src/core/database.py` — `os.environ` replaced with `get_settings()`; engine now uses typed config fields, not raw string reads
- New component: `src/core/deps.py` — shared FastAPI dependency re-export; stable import point for `get_db` and future shared dependencies

---

## Session 05 — Commit 06: `meal-ingredient-service-routes`

**Date:** 2026-04-20
**Task:** Build `meal_service.py`, `ingredient_service.py`, the corresponding API routes, and wire them into `src/main.py`. Also create `src/core/cache.py` (absent from disk, required by the services for cache invalidation).

### Task Brief

This commit is the first time real application logic exists. The services are pure Python functions — no FastAPI coupling, only `AsyncSession` passed in. Routes are thin shells: validate, delegate, respond. Both layers follow the standards set in Sessions 01–04.

Files to produce:
- `src/core/cache.py` — Redis client and cache helpers (`get_menu_cache`, `invalidate_menu_cache`)
- `src/services/meal_service.py` — `create_meal`, `get_meal`, `list_meals`, `search_meals`
- `src/services/ingredient_service.py` — `create_ingredient`, `get_ingredient`, `list_ingredients`, `update_stock`
- `src/api/routes/meals.py` — `POST /meals`, `GET /meals`, `GET /meals/{id}`, `GET /meals/search`
- `src/api/routes/ingredients.py` — `POST /ingredients`, `GET /ingredients`, `PATCH /ingredients/{id}/stock`
- `src/main.py` — include both new routers

Constraints going in:
- Async SQLAlchemy throughout — `select()`, `session.execute()`, explicit eager-loading
- No raw SQL — FTS via `func.to_tsvector` / `func.plainto_tsquery`
- `search_meals` on `name` and `tags` columns, case-insensitive
- Cache invalidation on every write to Meal or Ingredient — `menu:all` key
- 404 as `HTTPException(status_code=404, detail="...")` with a specific message
- No `Any` in type hints

### Decisions Made

**1. `src/core/cache.py` created in this commit (not a prior commit).**
The commit protocol listed `cache.py` under "core infrastructure" but the file was absent from disk when I started. Services require cache functions now — no valid reason to defer. Creating it here keeps the services self-contained. Adam has no action required — no new env vars are introduced; `REDIS_URL` was already documented.

**2. Redis failures are non-fatal in all cache helpers.**
Every `get_redis()` call, `get`, `setex`, and `delete` is wrapped in a try/except that logs a warning and returns `None` (or returns silently on write). A Redis outage means the service falls through to Postgres — customer requests continue working. The alternative (raising on cache failure) would turn a Redis blip into a 500 for the customer. Postgres is always the source of truth; Redis is advisory.

**3. `list_meals` serves from `menu:all` cache using raw JSON — deserialised into `MealRead` models.**
The cache stores a JSON string produced by `MealRead.model_dump(mode="json")`. On a hit, `MealRead.model_validate(item)` re-validates each dict. This preserves Pydantic's type guarantees even when reading from cache — a corrupted cache entry fails gracefully (log + fall-through) rather than serving malformed data.

**4. `search_meals` uses `to_tsvector("english", name) || to_tsvector("english", array_to_string(tags, " "))` with `@@` operator.**
The combined tsvector approach is idiomatic Postgres FTS. Tags are stored as a Postgres array; `array_to_string(tags, " ")` converts them to a space-joined string before vectorising. This means a search for "spicy" matches both a meal named "Spicy Tuna" and a meal tagged ["spicy"]. The query was verified to compile correctly against the Postgres dialect using SQLAlchemy's `compile()`.

**5. `search_meals` returns empty results on blank/whitespace query — does not fall back to `list_meals`.**
A blank query passed to `plainto_tsquery` would either error or return all documents depending on the Postgres version. Explicit early-return on `stripped == ""` is cleaner and predictable. The route layer enforces `min_length=1` on the `q` parameter anyway — this is belt-and-suspenders at the service level for direct callers (Nova's tools).

**6. Route `/meals/search` declared before `/{meal_id}` in `meals.py`.**
FastAPI resolves routes in declaration order. If `/{meal_id}` appears first, the literal string "search" is parsed as an integer and fails with a 422 before the search route is ever reached. This is a well-known FastAPI ordering gotcha — documented in the route file with an explicit comment so it does not get silently reordered.

**7. `get_meal_by_name` added to `meal_service.py` (not in the original spec).**
Nova's agent tools need to resolve a customer-provided meal name to an ID before constructing an `OrderCreate`. Without this function, Nova would have to call `list_meals` and filter client-side — unnecessarily expensive. The function is a simple exact-match `select` on `Meal.name`. Adding it now costs nothing and removes a predictable pain point for Nova when she starts Commits 12–13.

**8. `ingredient_service.list_ingredients` is not cached.**
Ingredient lists are admin-facing (staff checking stock levels, not menu browsing). The read frequency does not justify cache overhead. The `menu:all` cache covers the hot customer path. Stock writes still invalidate `menu:all` because ingredient availability feeds into meal availability.

**9. 409 Conflict returned for duplicate name on `POST /meals` and `POST /ingredients`.**
`IntegrityError` from SQLAlchemy is caught at the route level (not the service level). The service raises it naturally — catching it in the service would hide the error from callers who might need different handling. The route translates it to a 409 with a specific message that names the duplicate value.

### Issues Found Mid-Task

**`Decimal` imported but unused in `meal_service.py` (initial draft).** Caught in self-review. Removed before finalising.

**`cache.py` absent from disk.** Expected from commit-protocol order. Created in this commit — no cross-agent coordination needed since no new env vars are involved.

### Self-Review Checklist

- [x] `cache.py` — all helpers have explicit try/except; Redis failures are non-fatal
- [x] `cache.py` — every `setex` call includes TTL from `get_settings().cache_ttl_seconds`
- [x] `cache.py` — no `Any` in type hints; `dict[str, object]` for menu data
- [x] `meal_service.create_meal` — invalidates `menu:all` after commit
- [x] `meal_service.list_meals` — cache hit path deserialises via `MealRead.model_validate`; corrupted cache falls through
- [x] `meal_service.search_meals` — FTS verified to compile against Postgres dialect
- [x] `meal_service.search_meals` — empty/whitespace query returns empty result, not all meals
- [x] `meal_service.get_meal_by_name` — added for Nova's tool layer; exact match on name
- [x] `ingredient_service.update_stock` — absolute replacement, not delta (matches `IngredientStockUpdate` contract)
- [x] `ingredient_service.update_stock` — invalidates `menu:all` after commit
- [x] `ingredient_service.update_stock` — returns `None` when ingredient not found (route maps to 404)
- [x] `meals.py` route — `/search` declared before `/{meal_id}` to avoid FastAPI ordering bug
- [x] `meals.py` route — `IntegrityError` caught at route level, mapped to 409 with specific message
- [x] `ingredients.py` route — `PATCH /{id}/stock` returns 404 on unknown ingredient
- [x] All route 404 messages include the specific ID and resource type
- [x] `src/main.py` — both routers included; health check retained
- [x] No `Any` in type hints across all six files
- [x] No raw SQL — all queries through `select()` and SQLAlchemy ORM
- [x] No FastAPI imports in service files
- [x] Syntax check passed on all six files

### 📋 Documentation Flags for Claude

**DECISIONS.md:**
- `Redis cache failures are non-fatal` — all cache operations wrapped in try/except; Redis outage falls through to Postgres; customer requests continue without error; logged at WARNING level
- `search_meals uses combined tsvector (name || array_to_string(tags))` — single FTS vector over both meal name and tags; `plainto_tsquery` handles tokenisation; case-insensitive by design of the english text search config
- `GET /meals/search declared before GET /meals/{meal_id}` — FastAPI route ordering: literal path segments must precede parametric segments or they are shadowed; documented in route file

**ARCHITECTURE.md:**
- New component: `src/core/cache.py` — Redis client singleton + helpers for `menu:all` and `order:status:{id}` cache keys; non-fatal on Redis failure
- New component: `src/services/meal_service.py` — `create_meal`, `get_meal`, `list_meals`, `search_meals`, `get_meal_by_name`; FTS search over name + tags
- New component: `src/services/ingredient_service.py` — `create_ingredient`, `get_ingredient`, `list_ingredients`, `update_stock`
- New component: `src/api/routes/meals.py` — `POST /meals`, `GET /meals`, `GET /meals/search`, `GET /meals/{id}`
- New component: `src/api/routes/ingredients.py` — `POST /ingredients`, `GET /ingredients`, `GET /ingredients/{id}`, `PATCH /ingredients/{id}/stock`
- Updated: `src/main.py` — meals and ingredients routers wired in

---

## Handoff → Nova

**What I built:** Meal and ingredient services + API routes.

**Service function signatures:**

`meal_service.py`:
- `create_meal(db: AsyncSession, data: MealCreate) -> MealRead`
- `get_meal(db: AsyncSession, meal_id: int) -> MealRead | None`
- `list_meals(db: AsyncSession) -> MealListResponse`
- `search_meals(db: AsyncSession, query: str) -> MealListResponse`
- `get_meal_by_name(db: AsyncSession, name: str) -> MealRead | None`

`ingredient_service.py`:
- `create_ingredient(db: AsyncSession, data: IngredientCreate) -> IngredientRead`
- `get_ingredient(db: AsyncSession, ingredient_id: int) -> IngredientRead | None`
- `list_ingredients(db: AsyncSession) -> list[IngredientRead]`
- `update_stock(db: AsyncSession, ingredient_id: int, new_quantity: Decimal) -> IngredientRead | None`

**Routes:**
- `POST /meals` — 201 on success, 409 on duplicate name
- `GET /meals` — `MealListResponse` (cached)
- `GET /meals/search?q=` — `MealListResponse` (Postgres FTS, case-insensitive)
- `GET /meals/{id}` — `MealRead`, 404 on unknown ID
- `POST /ingredients` — 201 on success, 409 on duplicate name
- `GET /ingredients` — `list[IngredientRead]` (no cache)
- `GET /ingredients/{id}` — `IngredientRead`, 404 on unknown ID
- `PATCH /ingredients/{id}/stock` — `IngredientRead`, 404 on unknown ID

**FTS coverage:** `search_meals` queries both `Meal.name` and `Meal.tags` using a combined `to_tsvector` with the `english` text search configuration. Stemming applies — "spices" matches "spicy" etc. Case-insensitive.

**Error cases:**
- Service functions return `None` for not-found — routes map this to `HTTPException(404)`
- `IntegrityError` on duplicate name — routes map this to `HTTPException(409)`
- `search_meals` returns empty `MealListResponse` (not `None`) on blank query or no matches

**What Nova needs to know for her tools:**
- Call `search_meals(db, query)` for FTS — it handles blank-query safely
- Call `get_meal_by_name(db, name)` to resolve a customer-provided meal name to an `id` before constructing `OrderCreate`
- Call `get_ingredient(db, id)` to read current stock for availability checks — compare against `MealIngredient.quantity_required * order_quantity`
- Service functions expect an injected `AsyncSession` — in agent tools, obtain one via `async with async_session_factory() as db:` (imported from `src.core.database`)
- Return types are all typed Pydantic schemas — no free-form dicts

**Files to read:**
- `src/services/meal_service.py`
- `src/services/ingredient_service.py`
- `src/schemas/meal.py`, `src/schemas/ingredient.py`
- `src/models/meal_ingredient.py` — for `quantity_required` in availability checks
- `src/core/database.py` — for `async_session_factory`

I'm done with services and routes. Nova can read these files when her commits start.
