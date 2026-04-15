# agents_workflow.md — Sushi Shop

> Visual reference for how agents work individually and together.
> Based on `AGENTS.md`, `commit-protocol.md`, and each agent's `.md` file.
> This document describes process, not product. For what each agent builds, see `CLAUDE.md`.

---

## 1. The Team at a Glance

```
                          ┌─────────────┐
                          │    Eran     │  ← Team lead. Final approval on every commit.
                          └──────┬──────┘
                                 │ approves / escalations
                          ┌──────▼──────┐
                          │   Claude    │  ← Orchestrator. Owns no code. Routes everything.
                          └──────┬──────┘
              ┌──────────────────┼──────────────────┐
              │                  │                  │
       ┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐
       │     Rex     │    │    Nova     │    │    Adam     │
       │  Backend    │    │  AI Agent   │    │   DevOps    │
       └─────────────┘    └─────────────┘    └─────────────┘
                                 │
                          ┌──────▼──────┐
                          │    Mira     │  ← Product. No code. Suggestions only.
                          └─────────────┘

       ┌─────────────┐
       │    Aria     │  ← UI Designer. Monitoring only. Frontend phase not started.
       └─────────────┘
```

---

## 2. How a Commit Step Flows (the full loop)

Every commit follows this exact sequence. No step is skipped.

```
┌──────────────────────────────────────────────────────────────┐
│                     COMMIT STEP LOOP                         │
│                                                              │
│  1. Claude reads commit-protocol.md                          │
│     └→ identifies current step number and its owner         │
│                                                              │
│  2. Claude reads the owner's worklog                         │
│     └→ checks for any open handoff notes or blockers        │
│                                                              │
│  3. Claude checks prerequisite handoffs                      │
│     └→ if a teammate's handoff is needed and missing        │
│          → surface to Eran before proceeding                │
│                                                              │
│  4. Claude invokes the owning agent                          │
│     └→ passes handoff context from teammate worklogs        │
│                                                              │
│  5. Agent does the work                                      │
│     └→ writes to worklog continuously (not at the end)      │
│                                                              │
│  6. Agent writes outgoing handoff notes                      │
│     └→ for every teammate whose next step depends on        │
│          decisions made in this step                         │
│                                                              │
│  7. Claude runs pre-commit checklist                         │
│     □ ARCHITECTURE.md — new component or data flow?         │
│     □ DECISIONS.md    — non-obvious design choice?          │
│     □ GLOSSARY.md     — new term introduced?                │
│     └→ updates whichever file is flagged before committing  │
│                                                              │
│  8. Eran reviews and approves                                │
│                                                              │
│  9. Agent commits (in their voice, with their signature)     │
│                                                              │
│  10. Claude explains the next step and asks Eran to proceed  │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Individual Agent Workflows

### 3.1 Rex — Backend Engineer

Rex's workflow is strictly models-first. He never writes a service before the schema is settled.

```
START: Claude invokes Rex with the step brief
│
├─ READ
│   ├── own worklog (last session)
│   ├── teammate worklogs (Nova's if she has tools depending on Rex's services)
│   └── handoff notes from Adam (any infra constraints)
│
├─ OPEN worklog session (🔄 WIP)
│   └── write task brief immediately
│
├─ DEFINE TYPES FIRST
│   ├── SQLAlchemy models (if schema step)
│   └── Pydantic schemas (if schema/route step)
│       └── no service code written until types are settled
│
├─ WRITE SERVICES
│   └── pure Python logic, typed inputs/outputs, clear error messages
│
├─ WRITE ROUTES
│   └── thin handlers — delegate to services, never business logic in routes
│
├─ SELF-REVIEW
│   ├── [ ] models match agreed schema
│   ├── [ ] all error cases handled with clear messages
│   ├── [ ] async used correctly (no blocking calls in async def)
│   ├── [ ] cache invalidated on all writes
│   └── [ ] order state machine transitions are enforced
│
├─ WRITE HANDOFF NOTES (if applicable)
│   ├── → Nova: if service signatures or routes changed that her tools depend on
│   └── → Adam: if new env vars, packages, or startup changes were made
│
├─ WRITE DOCUMENTATION FLAGS FOR CLAUDE
│   └── 📋 ARCHITECTURE.md / DECISIONS.md
│
└─ CLOSE worklog session (✅ Done + key decision)
```

**Rex's commit voice:**
```
✓  "added DLQ routing — failed kitchen tasks retry once then dead-letter;
    order status set to FAILED so the customer isn't left in PENDING forever"
✗  "feat: add dead letter queue"
```

---

### 3.2 Nova — AI Engineer

Nova's workflow starts with a diagram, not code. She never opens a file before sketching the graph.

```
START: Claude invokes Nova with the step brief
│
├─ READ
│   ├── own worklog (last session)
│   └── Rex's worklog (tools call his services — read his decisions first)
│
├─ OPEN worklog session (🔄 WIP)
│   └── write task brief + sketch the agent graph as a block diagram
│       (what goes in at each node, what decisions are made, what state is updated)
│
├─ DEFINE STATE SCHEMA
│   └── AgentState TypedDict — all fields typed, all optionals explicit
│
├─ DEFINE TOOL OUTPUT SCHEMAS
│   └── typed dataclass or Pydantic model for every tool's return value
│       (never a raw string the LLM has to parse)
│
├─ WRITE TOOLS
│   ├── search_meals      → calls meal_service.search() directly
│   ├── check_ingredients → calls ingredient_service.check_stock() directly
│   ├── find_substitutes  → calls meal_service.find_substitutes() directly
│   └── dispatch_order    → httpx POST /orders (HTTP boundary — not a direct service call)
│
├─ WRITE PROMPTS (in src/agents/prompts/ — not inlined)
│   └── structure: role → task → constraints → output format → examples
│       with negative constraints ("Do NOT invent meal names")
│       and comments explaining why each constraint exists
│
├─ WIRE THE GRAPH
│   ├── nodes: understand_request → search_meals → check_availability
│   │                              → present_options / find_substitutes
│   │                              → confirm_and_dispatch
│   └── conditional edges: availability branch, substitutes branch
│
├─ ADD CIRCUIT BREAKER
│   └── wraps LLM invocation — open breaker returns immediate user-friendly error
│
├─ SELF-REVIEW
│   ├── [ ] graph compiles (graph.compile())
│   ├── [ ] all tool outputs are typed schemas, not free-form strings
│   ├── [ ] all tool failures caught and set state["error"]
│   ├── [ ] recursion_limit set on graph compile
│   ├── [ ] circuit breaker tested with simulated LLM failure
│   └── [ ] prompts in prompts/ not inlined in graph nodes
│
├─ WRITE HANDOFF NOTE → Claude
│   └── agent route shape, tool list, error states
│
├─ WRITE DOCUMENTATION FLAGS FOR CLAUDE
│
└─ CLOSE worklog session (✅ Done + key AI engineering decision)
```

**Nova's commit voice:**
```
✓  "structured check_ingredients output — was bool, now AvailabilityResult(available, missing);
    agent can reason about which ingredients are out, not just whether it can proceed"
✗  "feat: improve agent tools"
```

---

### 3.3 Adam — DevOps Engineer

Adam's workflow is infrastructure-as-code. Every setup step is scripted or documented — nothing tribal.

```
START: Claude invokes Adam with the step brief
│
├─ READ
│   ├── own worklog (last session)
│   ├── Rex's worklog (new deps, env vars, startup changes)
│   └── Nova's worklog (new LLM env vars or network requirements)
│
├─ OPEN worklog session (🔄 WIP)
│   └── write task brief + list infrastructure dependencies
│
├─ UPDATE INFRASTRUCTURE FILES
│   ├── Dockerfile          — if new package or startup command
│   ├── docker-compose.yml  — if new service, new env var, health check change
│   ├── .env.example        — every new env var documented with placeholder + comment
│   ├── nginx/nginx.conf    — if rate limit or upstream change
│   └── Makefile            — if new convenience command needed
│
├─ UPDATE CI IF NEEDED
│   └── .github/workflows/ — lint + test jobs
│
├─ VERIFY
│   ├── [ ] docker-compose up starts all services with no errors
│   ├── [ ] GET /health returns 200 via Nginx on port 80
│   ├── [ ] .env.example has every variable referenced in code
│   ├── [ ] no secrets in any committed file
│   └── [ ] health checks pass for db, redis, api
│
├─ WRITE DOCUMENTATION FLAGS FOR CLAUDE
│
└─ CLOSE worklog session (✅ Done + key infra decision)
```

**Adam's commit voice:**
```
✓  "added health check to FastAPI container — without it Nginx routes to the upstream
    even when uvicorn is deadlocked; now fails out within 30 seconds"
✗  "chore: update docker config"
```

---

### 3.4 Mira — Product Manager

Mira's workflow is observation and suggestion. She does not block any step — she informs.

```
TRIGGER: Claude reports a step is complete
│
├─ READ Claude's step summary
│
├─ OPEN worklog session (🔄 Active)
│
├─ REVIEW what was built from the user's perspective
│   └── ask: would a customer find this clear? does it solve the right problem?
│       is the scope right? is something missing that would confuse a user?
│
├─ WRITE SUGGESTIONS (if any)
│   └── format: 💡 Suggestion → [Agent name]
│       what I noticed / why it matters / my suggestion / what I'm not sure about
│
├─ FLAG TO CLAUDE
│   └── Claude decides whether to route immediately or bundle for next check-in
│
└─ CLOSE worklog session (✅ Done + key product insight)
```

Mira's suggestions are never blockers. The receiving agent decides whether to act on them.

---

### 3.5 Aria — UI Designer *(monitoring phase)*

```
TRIGGER: Claude reports a step that touches API shapes
│
├─ REVIEW the API response shapes being built by Rex
│   └── ask: will this be hard to render? is data missing that a UI would need?
│       is the order status model rich enough for a real-time status indicator?
│
├─ FLAG API SHAPE CONCERNS TO CLAUDE (if any)
│   └── "GET /orders/{id} should include estimated_ready_at if we want a countdown"
│       routes through Claude → Rex decides before the route is finalised
│
└─ No worklog entry needed unless a concern is raised
```

Aria's full workflow activates when Eran confirms the frontend phase has started.

---

## 4. Cross-Agent Interactions

### 4.1 Handoff Flow (Rex → Nova)

The most common handoff in this project. Happens after commits 06 and 07.

```
Rex finishes meal/order services and routes
│
├─ Rex writes in his worklog:
│   ## Handoff → Nova
│   Service function signatures: [name(params) → return type]
│   Route: POST /orders — OrderCreate → OrderRead
│   Error cases: MealNotFound, InsufficientStock
│   Files to read: src/services/order_service.py, src/api/routes/orders.py
│   I'm done. You can start.
│
Claude reads Rex's worklog
│
└─ Claude invokes Nova with the handoff context
    │
    Nova reads Rex's worklog session before opening any files
    │
    Nova builds tools against Rex's actual interfaces (not assumptions)
```

### 4.2 Handoff Flow (Rex → Adam)

Happens when Rex adds a new package or env var.

```
Rex adds a new dependency or env var
│
├─ Rex writes in his worklog:
│   ## Handoff → Adam
│   What changed: added pybreaker to pyproject.toml; new env var BREAKER_THRESHOLD
│   What you need to update: .env.example (add BREAKER_THRESHOLD=3 with comment)
│   Files to read: pyproject.toml, src/core/settings.py
│
Claude routes to Adam
│
└─ Adam updates .env.example and rebuilds the container image
```

### 4.3 Cross-Domain Finding

When an agent discovers a bug outside their domain.

```
Nova finds a bug in Rex's order_service while writing the dispatch tool
│
├─ Nova logs in her worklog:
│   🐛 CROSS-DOMAIN FINDING → Rex
│   File: src/services/order_service.py
│   Problem: create_order doesn't validate that quantity > 0; an order of 0 items
│             passes validation and creates an empty OrderItem row
│   Impact: dispatch_order tool could place a zero-quantity order
│   Suggested fix: add quantity > 0 check in OrderCreate schema validator
│
Nova flags to Claude
│
Claude routes to Rex
│
└─ Rex fixes it in his domain
    Nova does not touch the file
```

### 4.4 Disagreement Escalation

```
Agent A disagrees with a decision Agent B made
│
├─ Agent A logs in their worklog:
│   ⚠️ DISAGREEMENT → [Agent B / decision]
│   What was decided: [the decision]
│   Why I disagree: [specific technical or product reason]
│   What I propose: [concrete alternative]
│   What I need to proceed: [what must be resolved]
│
Agent A flags to Claude
│
Claude assesses
│
├─ [Blocking the current step] → Claude surfaces to Eran immediately
└─ [Not blocking]              → Claude routes to Agent B for response
                                    └─ Agent B responds in their worklog
                                         └─ Claude confirms resolution or re-escalates to Eran
```

---

## 5. The Commit Roadmap — Who Does What and When

```
Phase 1: Foundation
─────────────────────────────────────────────
 01  project-foundation          Adam
     └→ Docker, Nginx, .env, folder skeleton, health check

Phase 2: Database
─────────────────────────────────────────────
 02  database-models             Rex
     └→ SQLAlchemy ORM: Meal, Ingredient, MealIngredient, Order, OrderItem
 03  alembic-initial-migration   Rex
     └→ alembic.ini, env.py, 0001_initial_schema.py
 04  pydantic-schemas            Rex
     └→ MealCreate/Read, IngredientCreate/Read, OrderCreate/Read
 05  core-dependencies           Rex
     └→ Settings, get_db, async engine

Phase 3: API
─────────────────────────────────────────────
 06  meal-ingredient-service-routes   Rex
     └→ meal_service (FTS search), ingredient_service, routes
     └→ ⚑ HANDOFF → Nova after this commit
 07  order-service-routes             Rex
     └→ order_service (create, status transitions), /orders routes
     └→ ⚑ HANDOFF → Nova after this commit (dispatch_order target)

Phase 4: Infrastructure
─────────────────────────────────────────────
 08  redis-cache-layer           Rex
     └→ menu:all cache, order:status:{id} cache, invalidation on writes
 09  celery-kitchen-worker       Rex
     └→ process_order task: PENDING → PREPARING → READY
 10  celery-dlq                  Rex
     └→ dead letter queue, FAILED status on max retries

Phase 5: AI Agent
─────────────────────────────────────────────
 11  langgraph-agent-foundation  Nova
     └→ AgentState, graph nodes, conditional edges (availability + substitutes branches)
 12  agent-tools                 Nova
     └→ search_meals, check_ingredients, find_substitutes (direct service calls)
 13  agent-order-dispatch-tool   Nova
     └→ dispatch_order (httpx → POST /orders), POST /agent/chat route
 14  circuit-breaker             Nova
     └→ LLM failure guard, open breaker returns immediate user-friendly error

Phase 6: Nginx
─────────────────────────────────────────────
 15  nginx-load-balancer-rate-limiter   Adam
     └→ round-robin upstream, 10 req/s all routes, 2 req/min /agent/chat

Phase 7: Testing
─────────────────────────────────────────────
 16  test-infrastructure         Rex
     └→ conftest.py, test DB, transaction rollback per test
 17  unit-tests-services         Rex
     └→ meal_service, ingredient_service, order_service
 18  integration-tests-routes    Rex
     └→ all API routes against real test DB
 19  agent-tool-tests            Nova
     └→ each tool with mocked LLM
 20  celery-task-tests           Rex
     └→ process_order in eager mode, DLQ failure path
```

---

## 6. Data Flow — Domain Boundaries Visualised

```
Customer (natural language input)
    │
    ▼
POST /agent/chat
    │  ◄── Nova owns this route and everything above this line
    │
    ▼
LangGraph Agent (Nova)
    ├── understand_request
    │       └── LLM call [circuit breaker wraps this]
    ├── search_meals
    │       └── meal_service.search(query)  ◄── Rex's service
    ├── check_availability
    │       └── ingredient_service.check_stock(meal_id)  ◄── Rex's service
    ├── find_substitutes
    │       └── meal_service.find_substitutes(meal_id)  ◄── Rex's service
    └── dispatch_order
            └── httpx POST /orders  ◄── HTTP boundary: Nova calls, Rex implements
                    │
                    ▼
              order_service.create_order()  ◄── Rex's service
                    │
                    ▼
              Celery task enqueued  ◄── Rex's task
                    │
                    ▼
              Kitchen worker (Rex)
                    ├── PENDING
                    ├── PREPARING
                    └── READY  → customer notified
                         or
                         FAILED → DLQ → status update
```

**The boundary between Nova and Rex is the HTTP call to POST /orders.**
Everything above it: Nova. Everything below it: Rex.
Nova never touches a database session. Rex never writes a LangGraph node.

---

## 7. Worklog Reading Map

Before starting any cross-domain task, read these worklogs:

```
If you are Nova building tools
    └── Read Rex's worklog  (his service signatures are what your tools call)

If you are Rex changing a service interface
    └── Read Nova's worklog  (her tools may depend on the current signature)

If you are Adam updating the container
    └── Read Rex's worklog   (new packages, env vars, startup changes)
    └── Read Nova's worklog  (new LLM env vars, network requirements)

If you are Claude preparing a step handoff
    └── Read the owning agent's worklog
    └── Read the worklogs of agents whose output this step depends on
```

---

## 8. Communication Formats (quick reference)

```
💡 Suggestion → [Agent]      — proactive improvement idea, crossing domain lines
🔧 Request → [Agent]         — need specific information before I can proceed
✨ To [Agent]: [specific]     — acknowledgement of good work (only when genuine)
🐛 CROSS-DOMAIN FINDING      — bug found outside my domain, logged and flagged
⚠️ DISAGREEMENT              — technical or product disagreement, escalated to Claude
📋 Documentation flags       — ARCHITECTURE.md / DECISIONS.md / GLOSSARY.md updates
```

All of these are logged in the initiating agent's worklog before Claude routes them.
