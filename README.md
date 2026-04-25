# Sushi Shop

[![CI](https://github.com/EranMani/sushi-shop/actions/workflows/ci.yml/badge.svg)](https://github.com/EranMani/sushi-shop/actions/workflows/ci.yml)
![Status](https://img.shields.io/badge/status-work%20in%20progress-yellow)

> **Work in progress.** The backend is functional but the project is still being actively built. Expect incomplete test coverage and missing features.

An AI-powered sushi restaurant simulation. Customers describe what they want in natural language — a LangGraph agent finds matching meals, checks ingredient availability, offers substitutes if needed, and dispatches the confirmed order to the kitchen. Celery workers then drive the order through a real state machine (`PENDING → PREPARING → READY`).

---

## How it works

```
Customer (natural language)
  └─→ Nginx  (rate limiter + load balancer)
        └─→ FastAPI  (REST API + LangGraph agent)
              ├─→ LangGraph Agent
              │     ├─→ PostgreSQL  (meal search via full-text search)
              │     └─→ POST /orders  (order dispatch via httpx)
              ├─→ PostgreSQL  (persistent data store)
              ├─→ Redis  (Celery broker + menu/order cache)
              └─→ Celery workers  (kitchen simulation)
                    └─→ DLQ  (failed order handling)
```

### Agent flow

1. Customer sends a message to `POST /agent/chat` — e.g. *"I'd like something spicy with tuna"*
2. The agent searches the menu using Postgres full-text search across meal names and tags
3. It checks ingredient availability for the matched meal
4. If unavailable, it finds and presents substitutes
5. On customer confirmation, it dispatches the order via `POST /orders`
6. A Celery kitchen worker picks up the task and transitions the order:
   `PENDING → PREPARING → READY`
7. Failed tasks are retried once, then routed to a dead-letter queue

### Order state machine

```
PENDING ──→ PREPARING ──→ READY
   │              │
   └──────────────┴──→ FAILED  (DLQ)
```

State transitions are enforced in code — any invalid transition raises an error. There is no public HTTP endpoint to update order status; only the kitchen worker can drive state changes.

---

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI (Python 3.12), async |
| ORM | SQLAlchemy (async) + asyncpg |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Database | PostgreSQL 16 |
| Cache / Broker | Redis 7 |
| Task queue | Celery (kitchen workers + DLQ) |
| AI agent | LangGraph |
| LLM | Anthropic or OpenAI (configurable) |
| Load balancer | Nginx (rate limiting + round-robin) |
| Containers | Docker + Docker Compose |
| CI | GitHub Actions (lint + test) |

---

## Quick start

```bash
# 1. Clone and configure
git clone https://github.com/EranMani/sushi-shop.git
cd sushi-shop
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY (or OPENAI_API_KEY + LLM_PROVIDER=openai)

# 2. Start the full stack
docker-compose up

# Migrations run automatically on container start.
# The API is available at http://localhost:80
```

To run multiple API replicas behind Nginx:

```bash
docker-compose up --scale api=3
```

To wipe all data and start fresh:

```bash
docker-compose down -v
```

---

## API

### Agent

| Method | Path | Description |
|---|---|---|
| `POST` | `/agent/chat` | Send a natural-language message; receive a reply and optional `order_id` |

```json
// Request
{ "message": "I'd like something spicy with salmon", "customer_name": "Hana" }

// Response
{ "reply": "I found the Spicy Salmon Roll — shall I place the order?", "order_id": null }
```

Rate-limited to **2 requests/minute per IP** (Nginx) to protect LLM costs.

### Meals

| Method | Path | Description |
|---|---|---|
| `GET` | `/meals` | List all meals (Redis-cached) |
| `GET` | `/meals/search?q=spicy` | Full-text search across names and tags |
| `GET` | `/meals/{id}` | Get a meal by ID |
| `POST` | `/meals` | Create a meal |

### Ingredients

| Method | Path | Description |
|---|---|---|
| `GET` | `/ingredients` | List all ingredients |
| `GET` | `/ingredients/{id}` | Get an ingredient by ID |
| `POST` | `/ingredients` | Create an ingredient |
| `PATCH` | `/ingredients/{id}/stock` | Update stock level (absolute value) |

### Orders

| Method | Path | Description |
|---|---|---|
| `POST` | `/orders` | Place an order (triggers kitchen worker) |
| `GET` | `/orders` | List all orders |
| `GET` | `/orders/{id}` | Get order with status (Redis cache-first) |

Auto-generated docs are available at `http://localhost:80/docs`.

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | `postgresql+asyncpg://user:pass@db:5432/sushi` |
| `REDIS_URL` | — | `redis://redis:6379/0` |
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` | — | Required when `LLM_PROVIDER=anthropic` |
| `OPENAI_API_KEY` | — | Required when `LLM_PROVIDER=openai` |
| `APP_ENV` | `development` | `development` / `production` |
| `CACHE_TTL_SECONDS` | `300` | Menu cache TTL in seconds |
| `KITCHEN_PREP_TIME_SECONDS` | `5` | Simulated kitchen delay (set to `1` in CI) |

See `.env.example` for the full list with descriptions.

---

## Project structure

```
src/
├── main.py                  # FastAPI app entry point
├── core/
│   ├── settings.py          # Pydantic Settings (validated at startup)
│   ├── database.py          # Async engine + session factory
│   ├── cache.py             # Redis client + cache helpers
│   └── celery_app.py        # Celery config, queues, DLQ
├── models/                  # SQLAlchemy ORM models
├── schemas/                 # Pydantic request/response schemas
├── services/                # Pure Python business logic
├── api/routes/              # FastAPI route handlers
├── tasks/
│   └── kitchen.py           # Celery kitchen worker
└── agents/
    ├── graph.py             # LangGraph state machine (7 nodes, 4 conditional edges)
    ├── state.py             # AgentState schema
    ├── tools.py             # Agent tool definitions
    ├── circuit_breaker.py   # LLM failure guard (pybreaker)
    └── prompts/             # System prompts
```

---

## Design highlights

- **No raw SQL** — all queries go through SQLAlchemy ORM or `session.execute(select(...))`
- **Postgres FTS** — meal search combines `name` and `tags` into a single tsvector; no Elasticsearch needed at this scale
- **Cache is non-fatal** — Redis failure falls through to Postgres; the API keeps running
- **Agent tools return typed schemas** — no free-form string output for the LLM to parse
- **Circuit breaker on all LLM calls** — LLM failure returns an immediate clear error, not a hanging request
- **Celery task is idempotent** — status is read before each transition; safe to retry at any point without corrupting order state
- **No status endpoint** — `update_order_status` is called only by the kitchen worker; the state machine cannot be bypassed via the API

---

## License

MIT
