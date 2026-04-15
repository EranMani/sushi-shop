# commit-protocol.md — Sushi Shop

> The canonical build sequence. Every commit is defined here before any code is written.
> Each commit is atomic — one concern, one owner, one clear test gate.
> No commit is made without Eran's approval.
> No two commits are combined.

---

## Commit Index

| # | Name | Assignee | Status |
|---|---|---|---|
| 01 | project-foundation | Adam | pending |
| 02 | database-models | Rex | pending |
| 03 | alembic-initial-migration | Rex | pending |
| 04 | pydantic-schemas | Rex | pending |
| 05 | core-dependencies | Rex | pending |
| 06 | meal-ingredient-service-routes | Rex | pending |
| 07 | order-service-routes | Rex | pending |
| 08 | redis-cache-layer | Rex | pending |
| 09 | celery-kitchen-worker | Rex | pending |
| 10 | celery-dlq | Rex | pending |
| 11 | langgraph-agent-foundation | Nova | pending |
| 12 | agent-tools | Nova | pending |
| 13 | agent-order-dispatch-tool | Nova | pending |
| 14 | circuit-breaker | Nova | pending |
| 15 | nginx-load-balancer-rate-limiter | Adam | pending |
| 16 | test-infrastructure | Rex | pending |
| 17 | unit-tests-services | Rex | pending |
| 18 | integration-tests-routes | Rex | pending |
| 19 | agent-tool-tests | Nova | pending |
| 20 | celery-task-tests | Rex | pending |

---

## Commits in Detail

---

### Commit 01 — `project-foundation`

**Name (GitHub):** `chore: project foundation — docker, env, folder structure`

**Body:**
Sets up the full project skeleton before any application code is written.
Everything a developer needs to run the project locally from a clean clone.

Includes:
- `docker-compose.yml` — PostgreSQL, Redis, FastAPI (1 replica to start), Celery worker, Nginx
- `Dockerfile` — FastAPI app image
- `.env.example` — all required env vars documented
- `src/` folder structure: `api/`, `agents/`, `models/`, `schemas/`, `services/`, `tasks/`, `core/`
- `main.py` — bare FastAPI app with health check route
- `requirements.txt` / `pyproject.toml`
- `.gitignore`

**Assignee:** Adam

**Testing — done when:**
- [ ] `docker-compose up` starts all services with no errors
- [ ] `GET /health` returns `200 OK`
- [ ] PostgreSQL and Redis containers are reachable from the FastAPI container
- [ ] `.env.example` contains every variable referenced in code

---

### Commit 02 — `database-models`

**Name (GitHub):** `feat: SQLAlchemy database models (Meal, Ingredient, Order, OrderItem)`

**Body:**
Defines the full relational schema as SQLAlchemy ORM models.

Models:
- `Meal` — id, name, description, price, tags, is_available
- `Ingredient` — id, name, unit, stock_quantity
- `MealIngredient` — join table: meal_id, ingredient_id, quantity_required
- `Order` — id, customer_name, status (PENDING/PREPARING/READY), created_at, updated_at
- `OrderItem` — join table: order_id, meal_id, quantity

All models live in `src/models/`.
Base declarative and async session factory live in `src/core/database.py`.

**Assignee:** Rex

**Testing — done when:**
- [ ] All models import without errors
- [ ] Relationships are navigable (e.g. `meal.ingredients`, `order.items`)
- [ ] No circular imports

---

### Commit 03 — `alembic-initial-migration`

**Name (GitHub):** `chore: alembic setup and initial schema migration`

**Body:**
Initialises Alembic and generates the first migration from the SQLAlchemy models.

Includes:
- `alembic.ini`
- `alembic/env.py` configured for async SQLAlchemy
- `alembic/versions/0001_initial_schema.py` — creates all tables

**Assignee:** Rex

**Testing — done when:**
- [ ] `alembic upgrade head` runs without errors against a fresh database
- [ ] All five tables exist in PostgreSQL after migration
- [ ] `alembic downgrade -1` cleanly removes the tables
- [ ] `alembic current` shows the correct revision

---

### Commit 04 — `pydantic-schemas`

**Name (GitHub):** `feat: Pydantic request and response schemas`

**Body:**
All API-facing data contracts. No logic — just shapes.

Schemas in `src/schemas/`:
- `meal.py` — `MealCreate`, `MealRead`, `MealListResponse`
- `ingredient.py` — `IngredientCreate`, `IngredientRead`
- `order.py` — `OrderCreate` (list of `{meal_id, quantity}`), `OrderRead`, `OrderStatusUpdate`

**Assignee:** Rex

**Testing — done when:**
- [ ] All schemas import without errors
- [ ] `MealCreate` rejects missing required fields
- [ ] `OrderCreate` rejects an empty items list
- [ ] `OrderRead` serialises the status enum correctly

---

### Commit 05 — `core-dependencies`

**Name (GitHub):** `feat: FastAPI core dependencies (get_db, settings)`

**Body:**
Shared FastAPI dependencies used across all routes.

Includes:
- `src/core/settings.py` — Pydantic `Settings` class reading from `.env`
- `src/core/database.py` — async engine, session factory, `get_db` dependency
- `src/core/deps.py` — `Depends(get_db)` and any future shared dependencies

**Assignee:** Rex

**Testing — done when:**
- [ ] `get_db` yields an async session and closes it after the request
- [ ] `Settings` raises a clear error if a required env var is missing
- [ ] The session is rolled back on exception

---

### Commit 06 — `meal-ingredient-service-routes`

**Name (GitHub):** `feat: meal and ingredient CRUD — services and routes`

**Body:**
First real application logic. Menu management.

Services (`src/services/`):
- `meal_service.py` — create, get, list, search (Postgres FTS on name + tags)
- `ingredient_service.py` — create, get, list, update stock quantity

Routes (`src/api/routes/`):
- `POST /meals`, `GET /meals`, `GET /meals/{id}`, `GET /meals/search?q=`
- `POST /ingredients`, `GET /ingredients`, `PATCH /ingredients/{id}/stock`

**Assignee:** Rex

**Testing — done when:**
- [ ] `POST /meals` creates a meal and returns 201
- [ ] `GET /meals/search?q=spicy` returns meals matching the query
- [ ] `PATCH /ingredients/{id}/stock` updates stock and reflects in DB
- [ ] 404 is returned for unknown IDs
- [ ] FTS search is case-insensitive

---

### Commit 07 — `order-service-routes`

**Name (GitHub):** `feat: order service and routes (create, status, list)`

**Body:**
Order lifecycle management. This route is also the target of the agent's dispatch tool.

Service (`src/services/order_service.py`):
- `create_order` — validates meals exist and are available, creates Order + OrderItems, enqueues Celery task
- `get_order` — fetch order with items
- `update_order_status` — PENDING → PREPARING → READY (called by Celery worker)

Routes:
- `POST /orders` — create a new order, returns order ID
- `GET /orders/{id}` — get order with current status
- `GET /orders` — list all orders

**Assignee:** Rex

**Testing — done when:**
- [ ] `POST /orders` with valid meal IDs returns 201 and an order ID
- [ ] `POST /orders` with an unavailable meal returns 422
- [ ] `GET /orders/{id}` returns the correct status after creation (PENDING)
- [ ] `POST /orders` with an empty items list returns 422

---

### Commit 08 — `redis-cache-layer`

**Name (GitHub):** `feat: Redis cache for menu and order status`

**Body:**
Caches the full meal list and individual order statuses in Redis.
Reduces Postgres load for read-heavy operations.

Cache strategy:
- `menu:all` — full serialised meal list, TTL = `CACHE_TTL_SECONDS` (default 300s)
- `order:status:{id}` — current status string, TTL = 60s
- Cache is invalidated on any write to `Meal` or `Ingredient`

Cache client in `src/core/cache.py`.
Injected into services via `Depends`.

**Assignee:** Rex

**Testing — done when:**
- [ ] Second call to `GET /meals` is served from cache (verify with Redis `KEYS` or logging)
- [ ] Cache is invalidated after `POST /meals`
- [ ] Cache miss falls through to Postgres correctly
- [ ] Order status cache reflects Celery updates within TTL

---

### Commit 09 — `celery-kitchen-worker`

**Name (GitHub):** `feat: Celery kitchen worker — PENDING → PREPARING → READY`

**Body:**
The kitchen simulation. A Celery task receives an order ID, simulates preparation time,
and transitions the order through the state machine.

Task (`src/tasks/kitchen.py`):
- `process_order(order_id)` — sleeps to simulate prep time, updates order status at each step
- Status updates write to both Postgres and Redis cache
- On completion, logs "Order {id} is READY — notify customer"

Celery app configured in `src/core/celery_app.py`.

**Assignee:** Rex

**Testing — done when:**
- [ ] Dispatching `process_order.delay(order_id)` transitions order from PENDING → PREPARING → READY
- [ ] Postgres reflects the final READY status
- [ ] Redis cache is updated at each transition
- [ ] Worker logs each state transition with the order ID

---

### Commit 10 — `celery-dlq`

**Name (GitHub):** `feat: dead letter queue for failed kitchen tasks`

**Body:**
Any order task that fails (worker crash, unhandled exception) is routed to the DLQ
instead of silently disappearing.

Config:
- Celery `task_routes` and `task_queues` in `src/core/celery_app.py`
- `kitchen.dlq` queue for dead letters
- Failed tasks are retried once before being sent to DLQ
- DLQ handler logs the failure and updates order status to `FAILED`

**Assignee:** Rex

**Testing — done when:**
- [ ] A task that raises an exception ends up in the DLQ after max retries
- [ ] Order status is set to `FAILED` in Postgres
- [ ] DLQ message contains the original order ID and error reason
- [ ] Healthy tasks are not affected by DLQ configuration

---

### Commit 11 — `langgraph-agent-foundation`

**Name (GitHub):** `feat: LangGraph agent — state, graph structure, and branching logic`

**Body:**
The AI assistant graph. Handles the conversation flow and decision branches.

Graph nodes:
- `understand_request` — parse what the customer wants
- `search_meals` — call the search tool
- `check_availability` — verify ingredients in stock
- `find_substitutes` — if unavailable, find alternatives
- `present_options` — return choices to the customer
- `confirm_and_dispatch` — customer confirms, agent places the order

Conditional edges:
- After `check_availability`: available → `present_options` / unavailable → `find_substitutes`
- After `find_substitutes`: substitutes found → `present_options` / none → end with apology

State schema and graph wiring in `src/agents/`.

**Assignee:** Nova

**Testing — done when:**
- [ ] Graph compiles without errors (`graph.compile()`)
- [ ] A test run with mocked tools returns a structured `AgentState` at each node
- [ ] The availability branch routes correctly for both cases
- [ ] The substitutes branch routes correctly for both cases

---

### Commit 12 — `agent-tools`

**Name (GitHub):** `feat: LangGraph agent tools — search, availability check, substitutes`

**Body:**
The tools the agent uses to interact with the restaurant system.

Tools (`src/agents/tools.py`):
- `search_meals(query: str)` — Postgres FTS, returns list of matching meals
- `check_ingredients(meal_id: int)` — checks stock for all ingredients of a meal, returns bool + missing list
- `find_substitutes(meal_id: int)` — queries for available meals with overlapping tags

All tools call service functions directly (no HTTP — they share the same process).

**Assignee:** Nova

**Testing — done when:**
- [ ] `search_meals("spicy")` returns meals tagged as spicy
- [ ] `check_ingredients(meal_id)` correctly identifies missing ingredients
- [ ] `find_substitutes(meal_id)` returns at least one alternative when one exists
- [ ] All tools return structured output the agent can parse

---

### Commit 13 — `agent-order-dispatch-tool`

**Name (GitHub):** `feat: agent dispatch tool — httpx POST to /orders`

**Body:**
The tool the agent uses to place a confirmed order.
Calls `POST /orders` via httpx rather than calling the service directly.
This keeps the agent decoupled from internal implementation and respects the API contract.

Tool:
- `dispatch_order(meal_ids: list[int], quantities: list[int], customer_name: str)` — builds the request payload and POSTs to `/orders`

Agent route exposed in `src/api/routes/agent.py`:
- `POST /agent/chat` — accepts a message, runs the LangGraph agent, streams or returns the response

**Assignee:** Nova

**Testing — done when:**
- [ ] `dispatch_order` tool calls `POST /orders` and returns the order ID on success
- [ ] `POST /agent/chat` with "I want a spicy tuna roll" returns meal options
- [ ] `POST /agent/chat` with a confirmed order creates an order in Postgres
- [ ] httpx errors are caught and returned as user-friendly messages

---

### Commit 14 — `circuit-breaker`

**Name (GitHub):** `feat: circuit breaker for LLM calls in the agent`

**Body:**
Wraps the LLM invocation in the agent with a circuit breaker.
If the LLM fails or times out repeatedly, the breaker opens and the customer
receives an immediate "assistant unavailable" message instead of a hanging request.

Implementation: `pybreaker` or `tenacity` at the LLM call boundary in `src/agents/`.
Breaker state: closed (normal) → open (failing) → half-open (recovery probe).

**Assignee:** Nova

**Testing — done when:**
- [ ] Simulated LLM failures trip the breaker after the configured threshold
- [ ] Open breaker returns a user-friendly error without calling the LLM
- [ ] Breaker recovers after a cooldown period
- [ ] Healthy LLM calls are unaffected by breaker configuration

---

### Commit 15 — `nginx-load-balancer-rate-limiter`

**Name (GitHub):** `feat: Nginx load balancer and rate limiting config`

**Body:**
Nginx as the entry point for all traffic.

Config (`nginx/nginx.conf`):
- Round-robin upstream across FastAPI replicas
- Rate limit: 10 req/s per IP on all routes
- Rate limit: 2 req/min per IP on `/agent/chat`
- Proxy headers set correctly for FastAPI

`docker-compose.yml` updated to include Nginx service and expose port 80.

**Assignee:** Adam

**Testing — done when:**
- [ ] `docker-compose up --scale api=3` distributes requests across 3 FastAPI instances (verify via logs)
- [ ] Exceeding the rate limit on `/agent/chat` returns 429
- [ ] Requests below the rate limit are not affected
- [ ] `GET /health` is accessible via Nginx on port 80

---

### Commit 16 — `test-infrastructure`

**Name (GitHub):** `chore: pytest test infrastructure — fixtures, test database, async client`

**Body:**
Sets up the test foundation before any test cases are written.

Includes:
- `conftest.py` — async test client, test database session, transaction rollback per test
- `pytest.ini` / `pyproject.toml` test config
- `docker-compose.test.yml` — `sushi_test` database for test runs
- Alembic migration applied automatically before test suite

Every test wraps in a transaction that rolls back — no shared state between tests.

**Assignee:** Rex

**Testing — done when:**
- [ ] `pytest` runs with zero test failures (no tests yet, just infrastructure)
- [ ] A dummy test that creates and reads a `Meal` via the test DB session passes
- [ ] Rollback is confirmed — data from one test is not visible in the next

---

### Commit 17 — `unit-tests-services`

**Name (GitHub):** `test: unit tests for meal, ingredient, and order services`

**Body:**
Tests the pure Python service layer in isolation.

Coverage:
- `meal_service`: create, get, list, search (FTS), not-found raises correctly
- `ingredient_service`: create, update stock, get
- `order_service`: create with valid meals, reject unavailable meals, status transitions

**Assignee:** Rex

**Testing — done when:**
- [ ] All service tests pass
- [ ] Unhappy paths (missing meal, zero stock) are covered
- [ ] Test coverage for services is ≥ 80%
- [ ] No test hits external services (LLM, Redis) — those are mocked if referenced

---

### Commit 18 — `integration-tests-routes`

**Name (GitHub):** `test: integration tests for all API routes`

**Body:**
Tests the full request-response cycle against a real test database.

Coverage:
- `POST /meals`, `GET /meals`, `GET /meals/search`
- `POST /orders` happy path and unhappy paths
- `GET /orders/{id}` returns correct status
- `PATCH /ingredients/{id}/stock`
- 404 handling on all routes

**Assignee:** Rex

**Testing — done when:**
- [ ] All route tests pass against the test database
- [ ] 4xx responses return structured error messages (not raw exceptions)
- [ ] Each test is isolated — no order dependency between tests

---

### Commit 19 — `agent-tool-tests`

**Name (GitHub):** `test: LangGraph agent tool tests with mocked LLM`

**Body:**
Tests each agent tool independently. LLM is mocked — tools are tested for correctness,
not for LLM behaviour.

Coverage:
- `search_meals` returns expected results for known queries
- `check_ingredients` correctly identifies missing stock
- `find_substitutes` returns alternatives when available, empty list when not
- `dispatch_order` calls the correct endpoint with the correct payload

**Assignee:** Nova

**Testing — done when:**
- [ ] All tool tests pass
- [ ] Tools are tested against the test database, not production
- [ ] LLM is mocked — no API calls made during tests
- [ ] Edge cases: no meals found, all ingredients available, no substitutes

---

### Commit 20 — `celery-task-tests`

**Name (GitHub):** `test: Celery kitchen worker task tests (eager mode)`

**Body:**
Tests Celery tasks synchronously using `CELERY_TASK_ALWAYS_EAGER = True`.
No broker required — tasks run in the same process as the test.

Coverage:
- `process_order` transitions order through PENDING → PREPARING → READY
- Failed task updates order to FAILED and routes to DLQ
- Status is persisted in Postgres at each step

**Assignee:** Rex

**Testing — done when:**
- [ ] Task completes synchronously and order status is READY in Postgres
- [ ] A task that raises an exception sets status to FAILED
- [ ] No real Redis or Celery broker is required to run these tests

---

## Protocol Rules

1. Commits are made in the order listed above. No skipping.
2. Each commit requires Eran's approval before it is made.
3. The assignee does the work. If they need input from another agent, they log a handoff note.
4. Testing gate must be fully satisfied before Eran approves the commit.
5. If a commit reveals that a prior commit needs changing, surface it to Eran before touching the earlier commit.
6. `ARCHITECTURE.md` is updated if a decision changes during implementation.
