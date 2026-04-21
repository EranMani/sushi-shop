# DECISIONS.md — Sushi Shop

> Non-obvious design and technical choices made during the build.
> Updated at commit time when a choice was made that future contributors would otherwise have to reverse-engineer.
> For architecture-level decisions (system boundaries, data flows), see ARCHITECTURE.md.

---

## Format

Each entry:
- **What:** the decision made
- **Why:** the reasoning — constraints, tradeoffs, alternatives rejected
- **Raised by:** who identified or drove the decision (Eran, Rex, Nova, etc.)

---

## Commit 01 — project-foundation

---

### D-01 · Python 3.12-slim as Dockerfile base image (not Alpine)

**What:** `python:3.12-slim` chosen over `python:3.12-alpine` as the container base.

**Why:** `asyncpg` — the async PostgreSQL driver — requires `gcc` and `musl` headers to compile its C extension on Alpine Linux. Using Alpine would require adding a build toolchain, increasing both image build time and complexity with minimal size saving for this stack. `slim` is smaller than the full image, avoids the Alpine compilation problem, and is the correct tradeoff here.

**Raised by:** Adam (Commit 01)

---

### D-02 · Nginx rate limiting deferred to Commit 15

**What:** The `nginx/nginx.conf` delivered in Commit 01 is a minimal passthrough proxy — upstream and `proxy_pass` only. No `limit_req_zone`, no per-route rules.

**Why:** Rate limiting is a distinct concern assigned to Commit 15 (`nginx-load-balancer-rate-limiter`). Combining it into Commit 01 would violate the one-concern-per-commit protocol. The proxy needs to exist so the stack starts; the rate limiting rules are a separate, purposeful step.

**Raised by:** Adam (Commit 01)

---

### D-02b · uv replacing pip as the container package installer

**What:** `pip install` replaced with `uv pip install` in the Dockerfile. `uv` is pulled via a multi-stage build from the official `ghcr.io/astral-sh/uv:0.6.14` image (pinned tag).

**Why:** `uv` is significantly faster than pip and eliminates the two-step `pip install --upgrade pip && pip install` dance. The binary is pulled via multi-stage `COPY --from` — no curl, no extra OS packages, no pip bootstrap. Tag is pinned so a version bump is an explicit, reviewable change rather than silent drift. `UV_SYSTEM_PYTHON=1` skips venv creation inside the container (the image itself is the isolation boundary). `UV_COMPILE_BYTECODE=1` pre-compiles `.pyc` files at build time for faster startup. Path to full lockfile reproducibility: once `uv.lock` is committed, swap `uv pip install .` for `uv sync --frozen --no-dev`.

**Raised by:** Eran + Adam (post Commit 01 review)

---

### D-02c · entrypoint.sh with `exec` so uvicorn is PID 1

**What:** Replaced `CMD ["sh", "-c", "alembic upgrade head && uvicorn ..."]` with a dedicated `entrypoint.sh` script that runs migrations then calls `exec uvicorn ...`. The `ENTRYPOINT` instruction runs the script.

**Why:** With `sh -c`, `sh` is PID 1 inside the container. Docker sends `SIGTERM` to PID 1 on `docker stop` — if that's `sh`, the signal may not be forwarded to uvicorn. The result is uvicorn getting hard-killed after the 10s timeout, dropping any in-flight requests. `exec` replaces the shell process with uvicorn, making uvicorn PID 1 directly. It receives `SIGTERM`, finishes in-flight requests, and exits cleanly. Acceptable in dev; required in production.

**Raised by:** Eran (identified during Commit 01 review)

---

## Commit 02 — database-models

---

### D-04 · `Meal.tags` as `ARRAY(String)` (Postgres native array)

**What:** Tags are stored as a Postgres native `ARRAY(String)` column rather than a separate `Tag` table or a JSON column.

**Why:** Tags have no relational identity — no tag-specific attributes, no many-to-many relationships beyond the meal itself. A separate table adds a join with no benefit. JSON would work but loses Postgres index support. `ARRAY(String)` is queryable, FTS-friendly, and the simplest correct choice for this use case.

**Raised by:** Rex (Commit 02)

---

### D-05 · `OrderStatus` enum named `"orderstatus"` explicitly

**What:** The SQLAlchemy `Enum` column is declared with `name="orderstatus"` explicitly rather than letting SQLAlchemy generate a name.

**Why:** Postgres creates a named enum type when a `SQLAlchemy.Enum` column is defined. Without an explicit name, Alembic autogenerate can produce collisions or inconsistent names across migration runs. Explicit naming makes the Postgres type name deterministic and predictable in migrations.

**Raised by:** Rex (Commit 02)

---

### D-06 · `expire_on_commit=False` on `AsyncSession`

**What:** The session factory is configured with `expire_on_commit=False`.

**Why:** In synchronous SQLAlchemy, `expire_on_commit=True` (the default) marks all ORM attributes as expired after a commit, triggering a lazy reload on next access. In async context, that lazy reload requires an implicit I/O operation which raises an error — async SQLAlchemy does not support implicit lazy loading. `expire_on_commit=False` keeps attributes accessible post-commit. Services that need guaranteed fresh data after a commit call `session.refresh(obj)` explicitly.

**Raised by:** Rex (Commit 02)

---

### D-08 · Explicit rollback in `get_db` on exception

**What:** Added `except Exception: await session.rollback(); raise` to `get_db` before the `finally` block.

**Why:** SQLAlchemy rolls back an uncommitted transaction implicitly when a session closes. Relying on that implicit behaviour is correct but non-obvious — a developer reading `get_db` has no signal that rollback is handled. The explicit pattern makes the intent clear, handles edge cases where partial session state might not clean up correctly on close, and is the safer production choice. The `raise` re-raises the original exception so FastAPI can return the correct error response.

**Raised by:** Eran (identified during Commit 02 review, raised via Rex)

---

## Commit 03 — alembic-initial-migration

---

### D-09 · Alembic async bridge pattern in `env.py`

**What:** `env.py` uses `asyncio.run(run_async_migrations())` → `AsyncEngine` → `connection.run_sync()` to bridge Alembic's synchronous migration runner into the async SQLAlchemy engine.

**Why:** Alembic's `context.run_migrations()` is synchronous — it cannot be called directly from an async context. The bridge pattern (`run_sync`) passes a sync-compatible connection into the migration runner while keeping the engine async. This is the officially documented SQLAlchemy 2.x + Alembic pattern. The deprecated `strategy="threadlocal"` approach was explicitly avoided.

**Raised by:** Rex (Commit 03)

---

### D-10 · `orderstatus` enum explicit `create()` / `drop()` in migration

**What:** The `orderstatus` Postgres enum is created with `orderstatus_enum.create(op.get_bind(), checkfirst=True)` before the `orders` table, and dropped explicitly in `downgrade()` after `orders` is dropped.

**Why:** Alembic does not reliably manage standalone Postgres enum type lifecycle implicitly. If the enum is created as a side-effect of `op.create_table()`, Alembic may fail to drop it on downgrade — leaving an orphaned type that blocks future migrations. Explicit `create()` and `drop()` with `checkfirst=True` gives full control and ensures a clean upgrade and downgrade path.

**Raised by:** Rex (Commit 03)

---

### D-11 · `alembic.ini` has no database URL

**What:** `sqlalchemy.url` is absent from `alembic.ini`. `env.py` reads `DATABASE_URL` from the environment at runtime and raises a clear `RuntimeError` if it is missing.

**Why:** `alembic.ini` is committed to version control. Database credentials must never appear in a committed file. Reading from the environment at runtime keeps credentials out of the repo entirely while still providing a helpful error message when the variable is missing.

**Raised by:** Rex (Commit 03)

---

### D-07 · `database.py` reads `os.environ` directly in Commit 02

**What:** `DATABASE_URL` is read via `os.environ["DATABASE_URL"]` rather than through `settings.py`.

**Why:** `settings.py` (Pydantic Settings) is Commit 05's work. Importing it here would create a dependency on code that doesn't exist yet. The `os.environ` call is a deliberate temporary bridge — documented inline with a TODO. Commit 05 will replace it with `get_settings()`.

**Raised by:** Rex (Commit 02)

---

## Commit 05 — core-dependencies

---

### D-15 · `get_settings()` cached with `lru_cache(maxsize=1)`

**What:** The `Settings` instance is wrapped in `@lru_cache(maxsize=1)` so it is constructed once per process lifetime and reused on every subsequent call.

**Why:** Env vars don't change at runtime — reading and validating them on every request would be wasteful and misleading. Caching makes the singleton nature explicit. **Test caveat:** tests that patch env vars must call `get_settings.cache_clear()` before patching to force re-instantiation; otherwise the cached instance with the old values is returned.

**Raised by:** Rex (Commit 05)

---

### D-16 · `DATABASE_URL` asyncpg scheme validator in `Settings`

**What:** A `@field_validator` on `database_url` rejects any URL that does not start with `postgresql+asyncpg://`.

**Why:** A plain `postgresql://` URL reaches SQLAlchemy's engine creation and fails with a dialect error that gives no pointer to the misconfigured env var. The validator catches it at startup with the exact value and the fix. This is a common misconfiguration on first setup.

**Raised by:** Rex (Commit 05)

---

### D-17 · `deps.py` as stable import home for shared FastAPI dependencies

**What:** `src/core/deps.py` re-exports `get_db` from `src.core.database`. Routes import from `deps`, not from `database` directly.

**Why:** As the route layer grows, routes importing from each other or from deep core modules creates circular import risk. A thin re-export file gives every route a consistent, circular-import-safe import path. Future shared dependencies (auth, rate-limit bypass, pagination params) slot in here without touching individual route files.

**Raised by:** Rex (Commit 05)

---

## Commit 04 — pydantic-schemas

---

### D-12 · `OrderStatus` imported from ORM model into schema layer (not redefined)

**What:** `src/schemas/order.py` imports `OrderStatus` from `src.models.order` rather than declaring a parallel enum.

**Why:** Two enum definitions for the same concept means two places to update when a state is added or renamed, and a non-zero risk that they drift silently. The schema layer is a downstream consumer of the model definition — it should read from it, not duplicate it.

**Raised by:** Rex (Commit 04)

---

### D-13 · `OrderItemRead.meal_name` and `price_each` as optional fields

**What:** `OrderItemRead` carries `meal_name: str | None` and `price_each: Decimal | None`, both defaulting to `None`.

**Why:** These values come from the eagerly-loaded `Meal` relationship (`selectinload`), not from the `OrderItem` row itself. Making them optional means the schema works with or without the join — routes that don't need the meal details skip `selectinload` and take the performance benefit. Nova's agent tools get readable order summaries when the join is included.

**Raised by:** Rex (Commit 04)

---

### D-15 · Postgres FTS over combined name + tags tsvector

**What:** `search_meals` builds a single tsvector by concatenating `to_tsvector('english', name)` and `to_tsvector('english', array_to_string(tags, ' '))`.

**Why:** A search for "spicy" should match both a meal called "Spicy Tuna Roll" and a meal tagged `["spicy"]`. Searching only the name column misses tag-only matches; searching tags as an array requires array-specific operators. Converting tags to a space-joined string and combining the two tsvectors into one expression gives a single ranked search over both fields. Nova's agent tool calls this function directly — the quality of the result directly affects what the agent presents to the customer.

**Raised by:** Rex (Commit 06)

---

### D-16 · `/meals/search` route declared before `/meals/{meal_id}`

**What:** In `src/api/routes/meals.py`, the `GET /meals/search` route is registered before `GET /meals/{meal_id}`.

**Why:** FastAPI resolves routes in declaration order. If `/{meal_id}` is declared first, a request to `/meals/search` is matched against it and FastAPI attempts to cast `"search"` to an integer, producing a 422 validation error instead of routing to the search handler. Declaration order is the correct fix — no path prefix tricks needed.

**Raised by:** Rex (Commit 06)

---

### D-17 · Redis cache operations are non-fatal

**What:** All cache reads and writes in `src/core/cache.py` are wrapped so that a Redis failure logs a warning and falls through to Postgres — no exception is raised to the caller.

**Why:** Redis is a performance layer, not the source of truth. A Redis outage should degrade performance (more Postgres load), not take down the API. Making cache failures fatal would create an unnecessary hard dependency on Redis availability for every read-heavy route.

**Raised by:** Rex (Commit 06)

---

### D-14 · `IngredientStockUpdate` replaces stock level absolutely (not a delta)

**What:** `PATCH /ingredients/{id}/stock` accepts an absolute target value, not an increment or decrement.

**Why:** A delta model (`+50g`) requires the API to perform a read-modify-write internally. Under concurrent requests this creates a race: two requests both read `100g`, both apply `+50g`, and both write `150g` instead of `200g`. An absolute value puts the read-compute-write responsibility on the caller — correct when there is no API-level locking or optimistic concurrency control.

**Raised by:** Rex (Commit 04)

---

## Commit 07 — order-service-routes

---

### D-18 · `db.flush()` before `OrderItem` creation in `create_order`

**What:** After inserting the `Order` row, `await db.flush()` is called before creating `OrderItem` rows — rather than committing immediately or relying on the ORM to resolve the FK.

**Why:** `flush()` sends the `INSERT Order` to Postgres within the current transaction and populates `order.id` from the database-generated primary key, without committing. The `OrderItem` rows need `order.id` as a foreign key. Without `flush()`, `order.id` is `None` at ORM level and the insert would fail. `flush()` keeps everything in one transaction — if any `OrderItem` insert fails, the whole order rolls back cleanly.

**Raised by:** Rex (Commit 07)

---

### D-19 · `process_order.delay()` called after `db.commit()`, not before

**What:** The Celery kitchen task is enqueued *after* the transaction commits, not inside it.

**Why:** If the task is enqueued before commit and the Celery worker picks it up immediately, it queries Postgres for the order and finds nothing — the row isn't committed yet. Enqueueing after commit guarantees the worker always finds the order in Postgres. The tradeoff: if Celery enqueue fails after a successful commit, the order sits in PENDING state with no worker assigned. This is recoverable — a manual requeue or worker restart can pick it up. A failed commit after successful enqueue would be far worse (task runs, no order exists).

**Raised by:** Rex (Commit 07)

---

### D-20 · `_VALID_TRANSITIONS` dict — terminal states map to `set()`

**What:** The state machine is encoded as `dict[OrderStatus, set[OrderStatus]]` where `READY` and `FAILED` map to empty sets rather than being excluded from the dict.

**Why:** A missing key would require a separate `if current_status not in _VALID_TRANSITIONS` guard before the transition lookup. Mapping terminal states to `set()` means the same lookup path handles all states — the empty set check is the terminal state signal, no special-casing needed. The error message branches on whether `allowed_targets` is empty to produce the correct message ("terminal state" vs "valid transitions are: X").

**Raised by:** Rex (Commit 07)

---

### D-21 · `update_order_status` re-fetches with `selectinload` instead of `db.refresh()`

**What:** After committing the status update, the function re-executes a `select` with `selectinload` rather than calling `await db.refresh(order)`.

**Why:** `db.refresh()` reloads scalar columns from the database but does not re-apply `selectinload` chains. In async SQLAlchemy, accessing relationship attributes that were not eagerly loaded raises `MissingGreenlet` — lazy loading is not permitted in async context. A fresh `select` with explicit `selectinload(Order.items).selectinload(OrderItem.meal)` guarantees the full object graph is present for `_build_order_read`.

**Raised by:** Rex (Commit 07)

---

### D-22 · No `PATCH /orders/{id}/status` route exposed

**What:** There is no public HTTP endpoint for updating order status. `update_order_status` is called only by the Celery kitchen worker.

**Why:** Exposing a status-update endpoint would allow any caller (including Nova's agent or a malicious client) to drive the order into any state — bypassing the state machine entirely. The kitchen worker is the only legitimate authority for status transitions. Keeping the transition function internal-only enforces this by design, not by access control.

**Raised by:** Rex (Commit 07)

---

### D-03 · Named Docker volumes for Postgres and Redis persistence

**What:** Data volumes are declared as named volumes (`postgres_data`, `redis_data`) rather than bind mounts to a local `data/` directory.

**Why:** Bind mounts to a local directory work, but they pollute the repo root and create git noise (the data directory needs to be gitignored, and any accidental `git add` is a risk). Named volumes are the idiomatic Docker Compose pattern — they persist across `down/up` cycles and are managed by Docker, not the filesystem. `docker-compose down -v` removes them explicitly when a clean state is needed.

**Raised by:** Adam (Commit 01)
