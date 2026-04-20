# ARCHITECTURE.md — Sushi Shop

> Living document. Every non-obvious architectural decision lives here with its rationale and tradeoffs.
> Updated whenever a design choice is made that future contributors would otherwise have to reverse-engineer.

---

## System Overview

A sushi restaurant simulation where customers interact with an AI assistant to browse the menu,
place orders, and receive notifications when their meal is ready. The kitchen is modelled as
distributed Celery workers that process orders through a state machine.

```
Customer
  └─→ Nginx (rate limiter + load balancer)
        └─→ FastAPI instances (multiple replicas)
              ├─→ LangGraph Agent (AI assistant)
              │     ├─→ PostgreSQL (menu/ingredient lookup via FTS)
              │     └─→ httpx tool → FastAPI /orders route (order dispatch)
              ├─→ PostgreSQL (persistent data store)
              ├─→ Redis (Celery broker + in-memory menu cache)
              └─→ Celery workers (kitchen simulation)
                    └─→ DLQ (failed order handling)
```

---

## Infrastructure Layer

Five Docker Compose services make up the full local stack. Startup order is enforced via
`depends_on` with `condition: service_healthy` — no service starts before its dependencies
pass their health check.

| Service | Image | Health check | Role |
|---|---|---|---|
| `db` | `postgres:16` | `pg_isready -U sushi -d sushi` | Persistent data store |
| `redis` | `redis:7-alpine` | `redis-cli ping` | Celery broker + menu/order cache |
| `api` | Built from `Dockerfile` | `wget /health` → FastAPI | REST API + LangGraph agent |
| `worker` | Same image as `api` | None (worker, not a server) | Celery task processor |
| `nginx` | `nginx:alpine` | Depends on `api` healthy | Load balancer, proxies port 80 → api:8000 |

**Key implementation details:**
- `api` and `worker` share the same Docker image. They are differentiated by `command` override in `docker-compose.yml`.
- Alembic runs automatically on container start (`alembic upgrade head && uvicorn ...`) — schema is always current when the application starts, no manual migration step required.
- Named volumes (`postgres_data`, `redis_data`) persist data across `docker-compose down/up`. Use `docker-compose down -v` to wipe and start fresh.
- Nginx config in Commit 01 is a minimal passthrough proxy. Rate limiting and full upstream config is added in Commit 15.

---

## Decisions

---

### 1. FastAPI over Django / Flask

**Decision:** FastAPI

**Why:**
- Native async support — Celery task dispatch and httpx calls in the agent don't block the event loop
- Pydantic v2 built-in — schemas, validation, and serialization are first-class
- Auto-generated OpenAPI docs — useful for verifying routes during development

**Tradeoffs:**
- Less batteries-included than Django (no admin panel, no ORM out of the box)
- Requires explicit dependency injection (`Depends`) — more wiring than Django's magic

**What we gave up:** Django admin would be convenient for seeding menu data. We'll handle that with Alembic seed migrations instead.

---

### 2. PostgreSQL over MongoDB / SQLite

**Decision:** PostgreSQL

**Why:**
- The data model is clearly relational: Order → OrderItem → Meal → MealIngredient → Ingredient
- ACID transactions matter here — an order that partially writes is a corrupted order
- PostgreSQL full-text search (`tsvector`, `GIN` index) handles "find spicy sushi" well enough for this scale without adding Elasticsearch
- Alembic gives us proper schema migration history

**Tradeoffs:**
- More setup than SQLite, but we need real constraints and concurrent writes
- Schema changes require migrations — worth the discipline

**What we deferred:** Elasticsearch / vector embeddings for semantic search. Postgres FTS covers the current use case. When queries like "something light but filling" require semantic understanding, we'll add embeddings + pgvector or a dedicated search index.

---

### 3. Redis as Both Celery Broker and In-Memory Cache

**Decision:** Single Redis instance serving two roles

**Why:**
- Reduces infrastructure surface area — one service, two namespaces
- Celery broker and cache have different key patterns, no collision risk with proper prefixing
- Redis TTL handles cache expiry natively

**What we cache:**
- Full menu (meals + ingredients) — invalidated on any menu write
- Active order status per order ID — short TTL, source of truth remains Postgres

**Tradeoffs:**
- A Redis failure takes out both the cache and the message queue simultaneously
- For production this would split into two Redis instances (or use a managed broker like RabbitMQ)

**What we deferred:** Redis Sentinel / Cluster for HA. Out of scope for this phase.

---

### 4. Celery Workers as Kitchen Simulation

**Decision:** Celery for async order processing

**Why:**
- Models the real kitchen metaphor: orders are tasks, workers are chefs, the queue is the ticket rail
- Horizontal scaling is trivial — add more workers in `docker-compose.yml`
- Built-in retry logic and task state tracking

**Order State Machine:**
```
PENDING → PREPARING → READY
```
- `PENDING`: order received, task enqueued
- `PREPARING`: a worker has picked up the task, kitchen is working
- `READY`: task complete, customer is notified

`DELIVERED` is omitted — when the order is READY we notify the customer and the flow ends.
A pickup confirmation can be added in v2 if needed.

**DLQ (Dead Letter Queue):**
Failed tasks (e.g. a worker crash mid-preparation) are routed to a dead-letter queue.
The DLQ holds the failed task for inspection and can trigger a customer notification
("sorry, there was a problem with your order").

**Tradeoffs:**
- Celery adds operational complexity (worker process management, broker dependency)
- For truly high-throughput we'd evaluate Dramatiq or ARQ, but Celery's maturity wins here

---

### 5. LangGraph for the AI Assistant Agent

**Decision:** LangGraph with branching state machine

**Why:**
- The assistant has genuine conditional logic that maps naturally to a graph:
  - Can this order be fulfilled? → Yes → dispatch / No → find substitute
  - Is the meal in stock? → Yes → confirm / No → inform customer
- LangGraph's state + conditional edges make these branches explicit and testable
- Tool calling is first-class — the agent can call Postgres queries and HTTP endpoints as tools

**Agent Tools:**
| Tool | What it does |
|---|---|
| `search_meals` | Postgres FTS query on meal name + tags |
| `check_ingredients` | Verify all ingredients for a meal are in stock |
| `find_substitutes` | Find alternative meals when requested meal is unavailable |
| `dispatch_order` | httpx POST to `/orders` — places the confirmed order |

**Why httpx tool instead of direct DB call for dispatch:**
The order route has validation, authorization, and Celery task dispatch logic.
Calling it via HTTP keeps the agent decoupled from internal implementation details
and means the agent respects the same API contract as any external client.

**Circuit Breaker (LLM calls):**
The agent calls an external LLM (Anthropic/OpenAI). If the LLM is unavailable,
we fail fast with a clear customer message rather than hanging or cascading.
`pybreaker` or `tenacity` handles this at the agent invocation boundary.

**Tradeoffs:**
- LangGraph adds a learning curve and more moving parts than a simple function chain
- Worth it because the conditional branch logic is real and grows over time

**What we deferred:** RAG / vector embeddings for semantic meal search. Current scope uses Postgres FTS.

---

### 6. Nginx as Load Balancer + Rate Limiter

**Decision:** Nginx in front of multiple FastAPI instances

**Why:**
- A single config file handles both load balancing (round-robin across FastAPI replicas) and rate limiting (`limit_req_zone`)
- No additional service needed — Nginx is already a natural API gateway for this scale
- Docker Compose makes it easy to scale FastAPI: `docker-compose up --scale api=3`

**Rate limiting strategy:**
- Per-IP: 10 requests/second on all routes
- Per-IP: 2 requests/minute on `/agent/chat` (prevents LLM cost abuse)

**Tradeoffs:**
- Not a full API Gateway (no auth plugins, no analytics). Kong or Traefik would add those — deferred.
- Rate limit state is per-Nginx-instance. If Nginx is replicated, rate limits don't share state. Single Nginx is fine for this phase.

---

### 7. SQLAlchemy + Alembic over Raw SQL or Other ORMs

**Decision:** SQLAlchemy (async) + Alembic

**Why:**
- Async SQLAlchemy works natively with FastAPI's async request handlers
- Alembic provides a migration history — every schema change is tracked and reversible
- Industry standard — widely understood

**Tradeoffs:**
- More boilerplate than Tortoise ORM or SQLModel, but more control
- Alembic autogenerate requires careful review — it doesn't catch everything

---

### 8. Skipped Components and Why

| Component | Decision | Reason |
|---|---|---|
| **NoSQL database** | Skipped | No use case that Postgres + Redis doesn't already cover |
| **Read replica** | Deferred | No significant read load at this scale |
| **CDN** | Skipped | Backend API — no static assets to distribute |
| **Object storage** | Skipped | No files (images are out of scope for this phase) |
| **Elasticsearch** | Deferred | Postgres FTS handles current meal search needs |
| **Celery Beat (scheduler)** | Deferred | No scheduled tasks defined yet |
| **Kafka / event streaming** | Deferred | Redis Pub/Sub or SSE handles order status updates at this scale |
| **Docker Swarm / Kubernetes** | Deferred | Docker Compose is sufficient for the demo phase |

---

## Data Model

```
Meal
  id, name, description, price, tags (ARRAY(String)), is_available

Ingredient
  id, name, unit, stock_quantity (Numeric 10,2)

MealIngredient  (explicit association class)
  meal_id → Meal, ingredient_id → Ingredient, quantity_required (Numeric 10,2)

Order
  id, customer_name (String 200), status (OrderStatus enum), created_at, updated_at

OrderItem  (explicit association class)
  order_id → Order, meal_id → Meal, quantity (Integer)
```

**OrderStatus state machine:**
```
PENDING → PREPARING → READY
PENDING | PREPARING → FAILED  (DLQ handler)
```
State transitions are enforced in `order_service.py` — not at the ORM level.
Any invalid transition raises `ValueError`.

**Why `MealIngredient` and `OrderItem` are mapped classes, not bare `Table()`:**
Both carry payload columns (`quantity_required`, `quantity`) that service code reads directly.
A plain association table with no mapped class would require raw SQL or awkward joins to access those columns.

**Why `OrderItem` as a separate table:**
A single order can contain multiple meals in varying quantities.
A direct foreign key from Order to Meal would enforce one meal per order.
The join table is the correct relational pattern.

**Models live in:** `src/models/` — `base.py`, `meal.py`, `ingredient.py`, `meal_ingredient.py`, `order.py`, `order_item.py`

**Async session factory:** `src/core/database.py` — `async_engine`, `async_session_factory`, `get_db` FastAPI dependency.

---

## Configuration Layer

All application configuration flows through `src/core/settings.py`. No component reads `os.environ` directly.

**`src/core/settings.py`** — Pydantic `BaseSettings` singleton. Reads from `.env` file and environment variables. Validated at startup — missing required vars or a wrong `DATABASE_URL` scheme fail immediately with a descriptive error, not silently at first use. Cached via `@lru_cache(maxsize=1)` so Settings is instantiated once per process lifetime.

**`src/core/deps.py`** — Stable re-export of all shared FastAPI `Depends(...)` callables. Routes import from here, not from `database.py` directly. Prevents circular imports as the route layer grows. Future shared dependencies (auth, pagination params) live here.

**Startup validation chain:**
```
process start
  → get_settings() instantiated (lru_cache miss)
    → .env file read + env vars merged
    → field validators run (database_url scheme, cache_ttl > 0)
    → model_validator runs (LLM provider API key present)
    → Settings instance cached
  → async_engine created using settings.database_url
  → FastAPI app mounts routes
```

---

## Layer Dependency Chain

Each layer depends only on the layers below it. Nothing reaches upward.

```
Models          — source of truth; define what exists in the database
  └→ Schemas    — data contracts; reference model types and enums
       └→ Services    — business logic; validate input via schemas, query models
            └→ Routes      — HTTP handlers; call services, validate requests via schemas
                  └→ Agent tools  — reads call services directly; writes POST to routes via httpx
```

**Why this order matters for builds:**
- You cannot write schemas before models (schemas reference ORM enums and types)
- You cannot write services before schemas (services use `*Create` / `*Read` shapes)
- You cannot write routes before services (routes are thin wrappers around service calls)
- Nova cannot build agent tools before Rex finishes services and routes

**The one exception — `dispatch_order`:**
The agent's order dispatch tool calls `POST /orders` via httpx rather than calling the service directly.
This keeps the agent decoupled from internal implementation and ensures the full validation + state machine + Celery dispatch chain runs on every order, regardless of who places it.

---

## Schema Layer

All API-facing data contracts live in `src/schemas/`. No business logic — shapes only.

| File | Schemas |
|---|---|
| `src/schemas/meal.py` | `MealCreate`, `MealRead`, `MealListResponse` |
| `src/schemas/ingredient.py` | `IngredientCreate`, `IngredientRead`, `IngredientStockUpdate` |
| `src/schemas/order.py` | `OrderItemCreate`, `OrderCreate`, `OrderItemRead`, `OrderRead`, `OrderStatusUpdate` |

**Key design choices:**
- All response schemas (`*Read`) set `model_config = ConfigDict(from_attributes=True)` — they can be built directly from SQLAlchemy ORM objects
- `OrderStatus` is imported from `src.models.order` (not redefined in the schema layer) — one enum, no drift
- All fields carry `Field(description="...")` — improves Nova's structured output quality and auto-generates useful OpenAPI docs
- `OrderItemRead` has optional `meal_name` and `price_each` — populated by the service when the `Meal` relationship is eagerly loaded via `selectinload`; routes that don't need meal details can skip the join

**Data flow:**
```
FastAPI route receives request
  → validated against *Create schema
  → service layer processes (DB, cache, Celery)
  → ORM object returned
  → serialised via *Read schema (from_attributes=True)
  → JSON response to caller
```

---

## Migration Layer

All schema changes go through Alembic. No manual DDL. No `Base.metadata.create_all()` in production.

**`alembic.ini`** — Alembic CLI configuration. `script_location = alembic`. No database URL in this file — credentials are read from `DATABASE_URL` env var at runtime.

**`alembic/env.py`** — Async bridge between Alembic's synchronous migration runner and the asyncpg engine:
```
alembic upgrade head
  → run_migrations_online()
    → asyncio.run(run_async_migrations())
      → AsyncEngine.connect()
        → connection.run_sync(_run_migrations_with_connection)
          → context.run_migrations()  ← synchronous Alembic runner
```

**`alembic/versions/`** — Versioned migration files. Each file has `upgrade()` and `downgrade()`. Files are named descriptively: `0001_initial_schema.py`.

**Migration discovery:** `env.py` imports `Base` from `src.models`, which triggers `src/models/__init__.py` and registers all five models on `Base.metadata`. Alembic reads `target_metadata = Base.metadata` to know what tables exist.

---

## Testing Strategy

| Layer | Tool | What is tested |
|---|---|---|
| Unit | `pytest` | Service functions in isolation (pure Python logic) |
| Integration | `pytest` + `httpx.AsyncClient` | API routes against a real test database |
| Agent tools | `pytest` + mocked LLM | Each LangGraph tool independently |
| Worker tasks | `pytest` + Celery eager mode | Celery tasks run synchronously in tests |

**Test database:** A separate PostgreSQL database (`sushi_test`) spun up via Docker Compose.
Alembic runs migrations before the test suite. Each test wraps in a transaction that rolls back — no persistent state between tests.

---

## Environment Variables

```
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/sushi

# Redis
REDIS_URL=redis://redis:6379/0

# LLM
LLM_PROVIDER=anthropic          # or openai
ANTHROPIC_API_KEY=<key>
OPENAI_API_KEY=<key>

# App
APP_ENV=development             # development | production
CACHE_TTL_SECONDS=300
```
