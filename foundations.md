# foundations.md — Sushi Shop

> One page per agent domain. Not a tutorial — a map of the concepts that matter most,
> explained in the context of this specific project. Read this alongside the code, not instead of it.

---

## Rex — Backend Engineering

### 1. Async SQLAlchemy: why async, and what it changes

FastAPI is async — it handles many requests concurrently without blocking. If the database
driver is synchronous, every DB call blocks the event loop, killing that concurrency benefit.
`asyncpg` is a fully async PostgreSQL driver. SQLAlchemy wraps it so you can write normal ORM
queries while the engine handles the async plumbing underneath.

The key shift: every function that touches the database must be `async def`, and every
query must be `await`ed. Forgetting `await` doesn't raise an error — it just returns a
coroutine object instead of data. This is one of the most common silent bugs in async Python.

**In this project:** `get_db` yields an `AsyncSession` per request. Route handlers receive it
via FastAPI's dependency injection. No session is shared across requests.

---

### 2. Alembic: migrations as source of truth

Alembic is the gap between "what your ORM models say the schema should be" and "what the
database actually contains." Every schema change is written as a migration — a Python file
with an `upgrade()` and `downgrade()` function. Alembic tracks which migrations have been
applied in an `alembic_version` table.

**Why not `Base.metadata.create_all()`?** That call creates tables if they don't exist, but
never alters them. In production, your tables already exist. `create_all()` silently does
nothing, so column additions and index changes never land. Alembic is explicit — every change
is deliberate and reversible.

**In this project:** Every model change Rex makes has a corresponding migration in
`alembic/versions/`. The Makefile's `make migrate` runs `alembic upgrade head` inside the
container.

---

### 3. Celery: the kitchen is a task queue

Celery decouples "accepting a request" from "processing it." When an order is placed, the
API immediately returns `PENDING` — the actual kitchen work (state transitions, delays,
notifications) happens in a Celery worker running in a separate process.

Three components work together:
- **Broker** (Redis): where tasks are queued. The API pushes a task message; the worker pulls it.
- **Worker**: the process that executes the task function.
- **DLQ (Dead Letter Queue)**: where failed tasks land after retries are exhausted. Prevents
  silent failures — a failed order ends up in `FAILED` state, not lost.

**In this project:** `kitchen.py` defines the task that walks the order through
`PENDING → PREPARING → READY`. The state machine is enforced in code — an invalid transition
raises an error, it doesn't silently pass.

---

### 4. Redis: two jobs, one server

Redis serves two completely different roles here — don't conflate them.

**As a Celery broker:** Redis holds the task queue. Messages (task payloads) live here
temporarily until a worker picks them up. This data is ephemeral — if Redis restarts, pending
tasks could be lost (acceptable with proper retry config; not acceptable for orders, which is
why the order state is always written to Postgres first).

**As a cache:** The menu is read frequently and changes rarely. Caching it in Redis means
most menu requests never hit Postgres. Cache entries have a TTL (`CACHE_TTL_SECONDS`);
when they expire, the next request repopulates from Postgres. Redis is never the source
of truth — Postgres always is.

---

### 5. FastAPI dependency injection

`Depends()` is how FastAPI wires shared resources into route handlers. Instead of creating
a DB session inside every route, you declare `db: AsyncSession = Depends(get_db)` in the
function signature and FastAPI handles the lifecycle — creating the session before the request
and closing it after, even if the handler raises an exception.

This pattern keeps route handlers thin. The handler validates input, calls a service function,
returns a response. The service function contains the business logic. Neither creates its own
DB connection.

---

### 6. The service layer boundary

Services (`meal_service.py`, `order_service.py`, etc.) are pure Python functions that take a
session and return typed results. They contain all business logic — availability checks,
substitute logic, state transitions.

Routes are thin: validate → call service → respond.
Services are rich: query → reason → mutate → return.

This separation means the same logic can be called from a route handler, a Celery task, or a
test — without duplicating code or coupling to HTTP.

---

## Nova — AI Engineering

### 1. LangGraph: an agent is a state machine

LangGraph models the AI assistant as a directed graph of nodes. Each node is a function that
reads the current state, does something (calls a tool, calls the LLM, decides a branch), and
returns an updated state. Edges connect nodes — some edges are conditional (branch based on
what the LLM decided), some are unconditional.

**Why not a simple chain?** A chain runs A → B → C once. An agent needs to loop — the LLM
calls a tool, reads the result, decides whether to call another tool or respond. LangGraph
makes that loop explicit and inspectable, rather than hidden in recursion.

**In this project:** The graph starts with the user message, routes through tool calls
(menu search, availability check, order dispatch), and terminates when the assistant has a
final response.

---

### 2. Tool-calling: the agent as a function caller

The LLM doesn't execute code — it decides *which* function to call and *what arguments* to
pass. LangGraph intercepts that decision, executes the actual Python function, and feeds the
result back to the LLM as context for the next step.

**Tools must return typed schemas, not strings.** If a tool returns `"Salmon available: yes,
tuna: no"`, the LLM has to parse English to reason about it — and it will sometimes get it
wrong. If the tool returns `AvailabilityResult(salmon=True, tuna=False)`, the LLM gets
structured data it can reason about reliably.

**In this project:** `tools.py` defines each tool as a Python function with a Pydantic return
type. Nova owns these tools — Rex owns the service functions they call.

---

### 3. Why Nova calls HTTP, not the database directly

Nova's `dispatch_order` tool calls `POST /orders` via httpx — it doesn't import Rex's service
functions or touch a DB session. This is a deliberate boundary.

**Why it matters:**
- The API route is the enforcement point for validation, auth, and business rules. Bypassing
  it bypasses those checks.
- It keeps Nova's domain (LLM decisions) separate from Rex's domain (data persistence).
  If Rex changes his service layer, Nova's tool doesn't need to change — only the API contract
  matters.
- It mirrors how a real microservice would work: one service calls another's HTTP API, not its
  internal functions.

---

### 4. The circuit breaker: failing fast on LLM outages

A circuit breaker wraps calls to external services (here: the LLM provider). It tracks recent
failures. When failures exceed a threshold, the circuit "opens" — subsequent calls fail
immediately without attempting the real call. After a cooldown, it lets one call through to
test recovery.

**Without it:** if Anthropic or OpenAI is down, every customer request hangs until timeout.
Dozens of requests pile up, holding connections open, degrading the whole API.

**With it:** the circuit opens after N failures. Customers immediately get a clear error
("assistant is temporarily unavailable") instead of a hanging request. The system degrades
gracefully.

---

### 5. System prompts: behaviour over capability

The LLM's capability (what it can do) is set by the model. The system prompt controls its
behaviour (what it does in this context). A well-written system prompt defines the assistant's
persona, its constraints ("only discuss menu items that exist"), its tool-use preferences, and
how it handles edge cases ("if no substitutes are available, say so directly").

The system prompt is code. It changes the agent's output as predictably as changing a
function's logic. Nova owns and versions these prompts like any other file.

---

## Adam — DevOps

### 1. Docker: image vs container, and why layers matter

An image is a blueprint — a stack of read-only filesystem layers built from a `Dockerfile`.
A container is a running instance of an image. Many containers can run from the same image.

Layers are cached. When you rebuild an image, Docker only re-runs instructions where
something changed — and every instruction after that change. This is why dependency
installation (`pip install`) comes before copying your source code: dependencies change rarely,
source code changes constantly. Put slow steps early, fast-changing steps late.

**In this project:** The Dockerfile installs Python deps first, then copies `src/`. A code
change only invalidates the last layer. A dependency change invalidates everything after
`pip install`.

---

### 2. Docker Compose: orchestrating the stack

Compose describes the entire local stack as a single file: which services run, how they
connect, what volumes they use, what order to start them in. `docker-compose up` replaces
manually starting Postgres, Redis, the API, the Celery worker, and Nginx in five separate
terminal windows.

`depends_on` controls start order but not readiness — a service can "start" before its
database is actually accepting connections. Health checks solve this: Compose waits until a
service reports healthy before starting its dependents.

**In this project:** The API and worker both depend on `db` and `redis` with health checks.
Nginx depends on the API being healthy before it starts routing traffic.

---

### 3. Nginx: the layer in front

Nginx sits between the internet and the FastAPI instances. It does two jobs here:

**Rate limiting:** prevents a single client from hammering the API. Defined as requests-per-second
per IP. Clients that exceed the limit get a 429 before the request ever reaches FastAPI.

**Load balancing:** multiple FastAPI replicas run behind Nginx. Nginx distributes requests
round-robin across them. This is how horizontal scaling works — add more replicas, Nginx
spreads the load. FastAPI itself doesn't need to know it's one of many.

---

### 4. GitHub Actions: CI as a contract

CI (Continuous Integration) runs automatically on every push. Its job is to be the first
reviewer — catching lint errors and test failures before a human has to.

A workflow file defines jobs (lint, test) that run in parallel or sequence. Each job runs in
a fresh container. The test job spins up a real Postgres instance (not a mock) because the
tests need to verify actual query behaviour.

**The key principle:** if CI passes, the code is in a known good state. If CI fails, nothing
merges. The pipeline is the gatekeeper, not individual discipline.

---

## Mira — Product Management

### 1. User value without a UI

Most product thinking assumes a visible interface. This project has none — it's an API and
an AI assistant. Mira's job is to ask "what does the customer actually experience?" even
when there's no screen to point at.

For a backend-only phase, user value lives in: response quality (does the assistant give
useful answers?), reliability (does the order actually get placed?), and clarity (does the
customer know what's happening at each step?). These are measurable without a frontend.

---

### 2. "Is this worth building?" — the PM's core question

Every technical proposal has a cost: implementation time, maintenance burden, added
complexity. Mira's role is to challenge that cost against the user benefit.

A feature that solves a real user problem at low cost: build it.
A feature that solves an edge case at high cost: defer it.
A feature that adds technical elegance with no user benefit: skip it.

This is why Kafka, Elasticsearch, and read replicas were deferred — not because they're bad
ideas, but because the current phase doesn't have users who would feel their absence.

---

### 3. Product thinking as a constraint on scope

Mira doesn't write code, but she shapes what gets written. Her questions ("who benefits from
this?", "what breaks if we skip this?") act as a filter on the backlog. Without this filter,
engineering naturally tends toward completeness — building everything that could be useful.
With it, the team builds what is useful now.

Her output flows through Claude (orchestrator) rather than directly into code, because product
decisions need to be visible to the whole team before they affect a single line.

---

## Cross-Agent: How the Domains Connect

Understanding each domain in isolation misses the most important part: how they fit together.

```
Customer message
  → Nova (LangGraph) receives it
      → Nova calls search_meals tool
          → Rex's meal_service queries Postgres (via SQLAlchemy)
          → Redis cache checked first; Postgres is fallback
      → Nova calls check_availability tool
          → Rex's ingredient_service checks stock
      → Nova calls dispatch_order tool
          → HTTP POST to Rex's /orders route (Nova never touches DB directly)
              → Rex's order_service writes order to Postgres
              → Celery task dispatched to Redis broker
                  → Celery worker (Rex's kitchen.py) processes order
                      → PENDING → PREPARING → READY state transitions
  → Nova returns final response to customer
```

**Adam's role:** All of the above runs inside Docker Compose. Nginx is the front door.
GitHub Actions verifies every change before it lands.

**Mira's role:** Every feature in this flow was validated against "does this serve the
customer?" before Rex or Nova built it.
