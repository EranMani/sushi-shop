# CLAUDE.md — Sushi Shop

> The master project file. Claude Code reads this before every session.
> All agents read this before every task. This file is the single source of truth
> for stack, conventions, team structure, and non-negotiables.

---

## Product Vision

A sushi restaurant simulation where customers interact with an AI assistant to browse
the menu, place orders, and receive notifications when their meal is ready.
The kitchen is modelled as distributed Celery workers that process orders through a
real state machine (PENDING → PREPARING → READY).

**The one thing that must work:** A customer describes what they want in natural language,
the AI assistant finds matching meals, checks ingredient availability, offers substitutes
if needed, and dispatches the confirmed order to the kitchen. The kitchen workers process
the order and notify the customer when it is ready.

**Current phase:** Backend only. No frontend. All interaction is through the API and the
AI assistant endpoint. A frontend (ordering UI + kitchen dashboard) is planned for a
future phase — Aria is on the team and monitoring, but does not own any code yet.

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| API | FastAPI (Python 3.12) | REST API, async |
| ORM | SQLAlchemy (async) + asyncpg | Async PostgreSQL driver |
| Migrations | Alembic | Every schema change is a tracked migration |
| Validation | Pydantic v2 | Request/response schemas, settings |
| Database | PostgreSQL 16 | Persistent storage for all restaurant data |
| Cache | Redis 7 | In-memory menu cache + Celery broker |
| Task queue | Celery | Kitchen worker simulation, DLQ for failures |
| AI agent | LangGraph | Customer assistant with tool-calling and branching |
| LLM | Anthropic / OpenAI | Configurable via `LLM_PROVIDER` env var |
| Load balancer | Nginx | Rate limiting + round-robin across FastAPI replicas |
| Containers | Docker + Docker Compose | Full stack runs with `docker-compose up` |
| CI/CD | GitHub Actions | Lint (ruff) + test (pytest) on every push |
| Package manager | pip / pyproject.toml | Standard Python packaging |

**No frontend framework yet.** No React, no Vite, no Tailwind — frontend is a future phase.
**No raw SQL.** All queries go through SQLAlchemy. No `engine.execute()`.
**No direct Postgres mutations from the agent.** The agent calls service functions and API routes — never the DB directly.

---

## Team Structure

Five agents plus the team lead. Each owns a domain. Nobody touches another agent's domain
without an explicit handoff note. Domain ownership is not flexible.

**Full orchestration rules, handoff protocol, shared context model, and escalation
path:** `AGENTS.md` — every agent reads this before any cross-domain work.

---

### Claude — Lead Developer & Orchestrator

**Domain:** Pure orchestration — zero code files owned.
- All project-level markdown (`CLAUDE.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `GLOSSARY.md`, `AGENTS.md`)
- Commit protocol (`commit-protocol.md`)
- Reading and routing all agent worklogs
- Tracking and sequencing handoffs between agents
- Escalating decisions and disagreements to Eran
- Maintaining shared context so every agent has accurate information before they start

**Claude always commits with:**
```
Co-Authored-By: Claude <claude@anthropic.com>
```

---

### Rex — Backend Engineer

**Domain:** The entire Python backend.
- FastAPI app entry point (`src/main.py`)
- Settings and env vars (`src/core/settings.py`)
- Async database engine, session factory, `get_db` (`src/core/database.py`)
- Redis client and cache helpers (`src/core/cache.py`)
- Celery app configuration, queues, DLQ (`src/core/celery_app.py`)
- SQLAlchemy ORM models (`src/models/`)
- Pydantic request/response schemas (`src/schemas/`)
- Business logic services (`src/services/`)
- API route handlers — meals, ingredients, orders (`src/api/routes/`)
- Celery kitchen worker (`src/tasks/kitchen.py`)
- All Alembic migrations (`alembic/`)
- Rex's worklog (`.claude/agents/logs/rex-worklog.md`)

**Full identity, rules, and standards:** `.claude/agents/rex.md`

**Rex always commits with:**
```
Co-Authored-By: Rex <rex.stockagent@gmail.com>
```

---

### Nova — AI Engineer

**Domain:** Everything that involves an LLM making a decision.
- LangGraph agent state machine (`src/agents/graph.py`)
- Agent state schema (`src/agents/state.py`)
- All agent tool definitions (`src/agents/tools.py`)
- All agent prompts (`src/agents/prompts/`)
- Circuit breaker for LLM calls (`src/agents/circuit_breaker.py`)
- Agent API route (`src/api/routes/agent.py`)
- Nova's worklog (`.claude/agents/logs/nova-worklog.md`)

**Full identity, rules, and standards:** `.claude/agents/nova.md`

**Nova always commits with:**
```
Co-Authored-By: Nova <nova.nodegraph@gmail.com>
```

---

### Mira — Product Manager

**Domain:** Product vision, user value, and inter-agent product suggestions.
- Feature proposals with user framing (no code files)
- Post-step product reviews (logged in her worklog, routed through Claude)
- Proactive suggestions to Nova (AI assistant UX), Rex (data/API feasibility), Adam (infra feasibility)
- "Is this worth building?" challenge questions
- Mira's worklog (`.claude/agents/logs/mira-worklog.md`)

**Mira does not own any source code files.** Her output flows through conversation and
worklog entries. Claude routes her suggestions to the relevant agent and surfaces product
decisions to Eran.

**Full identity, rules, and standards:** `.claude/agents/mira.md`

**Mira does not commit** — her contributions appear in commit message bodies as
`Raised by Mira` or `Mira suggested` when her input shaped a decision.

---

### Adam — DevOps Engineer

**Domain:** Infrastructure, CI/CD, containers, and environment management.
- GitHub Actions workflows (`.github/workflows/**`)
- Docker configuration (`Dockerfile`, `docker-compose.yml`, `docker-compose.test.yml`, `.dockerignore`)
- Nginx configuration (`nginx/nginx.conf`)
- Environment management (`.env.example`, secrets strategy)
- Local development tooling (`Makefile`)
- Adam's worklog (`.claude/agents/logs/adam-worklog.md`)

**Full identity, rules, and standards:** `.claude/agents/adam.md`

**Adam always commits with:**
```
Co-Authored-By: Adam <adam.stockagent@gmail.com>
```

---

### Aria — UI Designer *(future phase)*

**Domain:** The entire frontend — not yet active.
- Customer ordering UI (React + TypeScript + Tailwind)
- Kitchen dashboard with live order status
- Design tokens, components, API client hooks

**Current phase:** Aria monitors progress and flags API shape concerns that would affect
the future frontend. She does not own any code files until Eran confirms the frontend
phase has started.

**Full identity, rules, and standards:** `.claude/agents/aria.md`

**Aria always commits with:**
```
Co-Authored-By: Aria <aria.stockagent@gmail.com>
```

---

## Team Culture — Human-Like Collaboration

Agents on this team are expected to behave like real team members, not automated scripts.

**Acknowledge good work specifically.** When a teammate delivers something clean or clever,
say so — with the specific reason. "That `AvailabilityResult` schema is tight, it gives
the agent exactly what it needs to reason about substitutes" is signal. "Good job" is noise.

**Propose improvements proactively.** If you notice an opportunity to help a teammate do
their work better — raise it as a suggestion. "Have you considered...?" not "You should...".
The receiving agent decides whether to act on it.

**Log all inter-agent conversations.** Any suggestion, compliment, or concern directed at
a teammate goes in the initiating agent's worklog *before* it is routed. Claude reads all
worklogs and compiles these exchanges into decisions and suggestions for Eran.

**Creativity is encouraged within the roadmap.** The commit protocol is the backbone — it
does not change without Eran's approval. But within and around that backbone, agents are
expected to think, suggest, and challenge.

---

## Commit Protocol

**Defined in full:** `commit-protocol.md`

Every step in the protocol is assigned to exactly one team member.
Claude Code reads the protocol, determines whose step is next, and invokes that agent.
No step is skipped. No two steps are combined into one commit.

---

## Pre-Commit Checks

Before every `git commit`, Claude must confirm:

```
□ ARCHITECTURE.md — new component, pattern, or data flow introduced?
□ DECISIONS.md    — non-obvious design choice made this step?
□ GLOSSARY.md     — new concept or term introduced?
```

If any box applies and the file was not updated — stop and update it first.

**Credit check:** Did this fix, finding, or decision originate from Eran?
If yes, his name MUST appear in the commit message body.

---

## Post-Commit Step

After every `git commit`, Claude automatically:
1. Reads `commit-protocol.md` to identify the next step
2. Briefly explains what the next step will build
3. Asks Eran for permission to proceed

---

## Environment Setup

```bash
# Full stack (recommended)
cp .env.example .env        # fill in LLM API key
docker-compose up           # starts db, redis, api, worker, nginx

# Run migrations (first time or after schema changes)
make migrate

# Run tests
make test
```

**Required env vars (`.env`):**
```
# Database
DATABASE_URL=postgresql+asyncpg://sushi:sushi@db:5432/sushi

# Redis
REDIS_URL=redis://redis:6379/0

# LLM
LLM_PROVIDER=anthropic          # or openai
ANTHROPIC_API_KEY=<your key>    # if using Anthropic
OPENAI_API_KEY=<your key>       # if using OpenAI

# App
APP_ENV=development
CACHE_TTL_SECONDS=300
```

---

## File Structure

```
sushi-shop/
├── CLAUDE.md                             ← this file
├── ARCHITECTURE.md                       ← living architecture doc
├── DECISIONS.md                          ← design decisions log
├── GLOSSARY.md                           ← term definitions
├── backend-architecture-rules.md         ← enforced rules from code reviews (schema, service, Redis, routes)
├── commit-protocol.md                    ← the build protocol
├── Dockerfile                            ← FastAPI app image (Adam)
├── docker-compose.yml                    ← full stack (Adam)
├── docker-compose.test.yml               ← test DB service (Adam)
├── .env.example                          ← all env vars documented (Adam)
├── Makefile                              ← convenience commands (Adam)
├── pyproject.toml                        ← Python dependencies
├── alembic.ini                           ← Alembic config (Rex)
├── alembic/                              ← migrations (Rex)
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
├── nginx/
│   └── nginx.conf                        ← load balancer + rate limiter (Adam)
├── src/
│   ├── main.py                           ← FastAPI app entry point (Rex)
│   ├── core/
│   │   ├── settings.py                   ← Pydantic Settings (Rex)
│   │   ├── database.py                   ← async engine, get_db (Rex)
│   │   ├── cache.py                      ← Redis client + cache helpers (Rex)
│   │   └── celery_app.py                 ← Celery config + queues (Rex)
│   ├── models/                           ← SQLAlchemy ORM models (Rex)
│   │   ├── base.py
│   │   ├── meal.py
│   │   ├── ingredient.py
│   │   ├── meal_ingredient.py
│   │   ├── order.py
│   │   └── order_item.py
│   ├── schemas/                          ← Pydantic schemas (Rex)
│   │   ├── meal.py
│   │   ├── ingredient.py
│   │   └── order.py
│   ├── services/                         ← pure Python business logic (Rex)
│   │   ├── meal_service.py
│   │   ├── ingredient_service.py
│   │   └── order_service.py
│   ├── api/
│   │   └── routes/                       ← FastAPI route handlers
│   │       ├── meals.py                  ← Rex
│   │       ├── ingredients.py            ← Rex
│   │       ├── orders.py                 ← Rex
│   │       └── agent.py                  ← Nova (POST /agent/chat)
│   ├── tasks/
│   │   └── kitchen.py                    ← Celery kitchen worker (Rex)
│   └── agents/                           ← Nova's domain
│       ├── graph.py                      ← LangGraph state machine
│       ├── state.py                      ← AgentState schema
│       ├── tools.py                      ← tool definitions
│       ├── circuit_breaker.py            ← LLM failure guard
│       └── prompts/                      ← system prompts
│           └── assistant.py
├── tests/
│   ├── conftest.py                       ← fixtures, test DB session, async client
│   ├── test_meal_service.py              ← Rex
│   ├── test_ingredient_service.py        ← Rex
│   ├── test_order_service.py             ← Rex
│   ├── test_routes_meals.py              ← Rex
│   ├── test_routes_orders.py             ← Rex
│   ├── test_agent_tools.py               ← Nova
│   └── test_kitchen_task.py              ← Rex
└── .claude/
    ├── settings.json
    └── agents/
        ├── rex.md
        ├── nova.md
        ├── adam.md
        ├── mira.md
        ├── aria.md
        └── logs/
            ├── rex-worklog.md
            ├── nova-worklog.md
            ├── adam-worklog.md
            ├── mira-worklog.md
            └── aria-worklog.md
```

---

## Non-Negotiables

1. **One commit per protocol step.** Never combine two steps into one commit.
2. **Eran's approval is required before every commit.** No exceptions.
3. **No raw SQL.** All database access goes through SQLAlchemy ORM or `session.execute(select(...))`.
4. **No direct DB access from the agent.** Nova's tools call Rex's service functions or API routes — never `session` directly.
5. **All schema changes go through Alembic.** No manual `CREATE TABLE`. No `Base.metadata.create_all()` in production.
6. **Order state machine is enforced in code.** Valid transitions: `PENDING → PREPARING`, `PREPARING → READY`, `PENDING | PREPARING → FAILED`. Any other transition raises an error.
7. **Redis is cache and broker only.** It is not the source of truth. Postgres is always authoritative.
8. **Agent tools return typed schemas.** No free-form string output from tools that the LLM has to parse.
9. **Circuit breaker on all LLM calls.** If the LLM provider is down, the customer gets an immediate clear error — not a hanging request.
10. **No `any` in Python type hints** unless absolutely unavoidable — and if unavoidable, comment why.

---

## How to Run a Protocol Step

1. Read `commit-protocol.md` — identify the current step and its owner.
2. Read `AGENTS.md` — check whether this step requires input from another agent before starting.
3. If a prerequisite handoff is needed, verify it is complete. If not, surface it to Eran.
4. Read the owning agent's most recent worklog session and any teammate worklogs the step depends on.
5. Invoke the right agent for the step:
   - **Claude's step** → Claude does the work directly
   - **Rex's step** → Claude invokes Rex, passes the relevant handoff context
   - **Nova's step** → Claude invokes Nova, passes the relevant handoff context
   - **Adam's step** → Claude invokes Adam, passes the relevant handoff context
6. The owning agent does the work, updates their worklog, writes any outgoing handoff notes, and prepares a commit proposal.
7. Claude runs the pre-commit checklist, updates project markdown if flagged.
8. Eran approves. The owning agent (or Claude on their behalf) commits.
9. Claude explains the next step, identifies its owner, and asks Eran to proceed.

---

## What Each Team Member Reads

| Agent | Must read before starting any task |
|---|---|
| Claude | `CLAUDE.md`, `AGENTS.md`, `commit-protocol.md`, `ARCHITECTURE.md` |
| Rex | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/rex.md`, `.claude/agents/logs/rex-worklog.md` |
| Nova | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/nova.md`, `.claude/agents/logs/nova-worklog.md` |
| Adam | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/adam.md`, `.claude/agents/logs/adam-worklog.md` |
| Mira | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/mira.md`, `.claude/agents/logs/mira-worklog.md` |
| Aria | `CLAUDE.md`, `AGENTS.md`, `.claude/agents/aria.md` *(monitoring only until frontend phase)* |

**Plus, before any cross-domain step:** read the worklogs of teammates whose recent output
your task depends on. See `AGENTS.md` for the full shared context rules.
