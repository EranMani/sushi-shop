# Backend Architecture Rules

Rules and tradeoffs established during code reviews of the Sushi Shop backend.
Updated after each review session. Covers schema design, service layer, async SQLAlchemy,
Redis caching, Postgres FTS, FastAPI routes, Celery architecture, and the full request flow.

---

## Schema Design

1. `*Create` = input (validation constraints, no `id`). `*Read` = output (`from_attributes=True`, ORM-safe). Never interchangeable.
2. Service layer always returns `*Read` — the ORM object stays internal; callers get clean, serialisable Pydantic models.
3. `*Create` schemas are staff-only. Customers never trigger create operations directly.
4. `OrderStatusUpdate` is a schema wrapping an enum — not an enum itself. `OrderStatus` is the enum (imported from the ORM model). `OrderStatusUpdate` is a Pydantic schema with one field: `status: OrderStatus`. The schema is the request body wrapper; the enum is the value constraint.
5. `model_validator(mode="after")` runs after all field validators complete and the model instance is constructed. It receives a fully built object and can cross-check fields. Use `mode="after"` for cross-field validation (e.g. `len(self.items) > 0`) — all fields are guaranteed present and valid at that point. `mode="before"` runs on raw unvalidated input.

---

## Many-to-Many Relationships & Join Tables

6. Use a join table when two entities have a many-to-many relationship. A direct FK from Order to Meal would enforce one meal per order — the join table (`OrderItem`) is the correct relational pattern.
7. Use an explicit mapped class (not bare `Table()`) when the join table carries payload columns. If the join table only stores two FKs, `Table()` is fine. The moment you add extra columns (`quantity`, `quantity_required`), you need a mapped class so service code can read those columns directly.

| Join table | Relationship | Extra payload |
|---|---|---|
| `OrderItem` | Order ↔ Meal (many-to-many) | `quantity` — how many of this meal per order |
| `MealIngredient` | Meal ↔ Ingredient (many-to-many) | `quantity_required` — how much ingredient per meal |

8. Schema mirrors model — consistently. Every join table model has a matching schema class. The schema is the API contract for what the join table exposes to callers.
9. **Planning rule:** identify many-to-many relationships before writing any model code. Each one needs a join table. Decide upfront whether it carries payload — if yes, it's a mapped class from day one. Retrofitting a bare `Table()` into a mapped class after services are written is a painful refactor.

---

## Service Layer

10. Returns `None` for not-found when multiple callers exist — each caller (route, agent, test) handles it differently. Route raises `HTTPException(404)`, agent routes to an apology node, test asserts `None`.
11. Domain exceptions (e.g. `IngredientNotFoundError`) make sense only when there is a single caller — more expressive and cleaner than `None` in that case.
12. Caller-neutral — no FastAPI imports, no HTTP concepts. `AsyncSession` injected as a parameter. Each caller speaks its own language on top.
13. **The service layer is the only layer that sits at the intersection of Postgres and Redis.** Routes know HTTP. Models know the schema. The agent knows LangGraph. Only the service layer touches both Postgres (reads/writes) and Redis (cache invalidation, cache population). Cache operations belong in the service — not in routes, not in models.
14. **Error messages are part of the API contract.** Nova's agent reads error messages and uses them to decide what to tell the customer. A generic `"invalid input"` leaves the agent with nothing useful to say. Write error messages as developer and agent communication — specific, named, actionable.

---

## Service Return Values — None vs Exception

15. Return `None` when there are multiple callers and "not found" is a normal case.
16. Raise an exception when there is a single caller, or the failure is a programming error. `update_order_status` raises `ValueError` on an invalid state transition — the Celery worker is the only caller and should never attempt an illegal transition.
17. Decision tree:
    - Multiple callers + "not found" is a normal flow → return `None`
    - Single caller, or failure is a programming error → raise an exception

---

## Async SQLAlchemy — Relationship Loading ⚠️ CRITICAL

18. **Lazy loading is forbidden in async SQLAlchemy.** In sync SQLAlchemy, accessing `order.items` when unloaded triggers an implicit query automatically. In async context, this raises `MissingGreenlet` — there is no implicit I/O allowed. Every relationship you intend to access must be explicitly loaded before you touch it.
19. **`selectinload` is the instruction to SQLAlchemy: "follow this relationship and populate it before I need it."** It issues a separate SELECT for the related rows and attaches them to the parent object. No lazy query, no implicit I/O.
20. **Chained `selectinload` for hierarchy traversal.** Each relationship hop must be loaded explicitly:
    ```python
    selectinload(Order.items).selectinload(OrderItem.meal)
    ```
    - `selectinload(Order.items)` — loads `OrderItem` rows for the order
    - `.selectinload(OrderItem.meal)` — for each `OrderItem`, loads its `Meal`
    Miss one level → `MissingGreenlet` the moment you access that unloaded attribute.
21. **Mental model: treat every relationship as if it doesn't exist until you explicitly load it.** Count the hops your code makes (`Order → OrderItem → Meal` = two hops), and match each hop with a `selectinload` level.
22. **`db.refresh()` does NOT restore selectinload chains.** After a commit, calling `await db.refresh(order)` reloads scalar columns but leaves relationships unloaded. If you need relationships after a commit, re-execute a fresh `select` with `selectinload` — never rely on `refresh` for relationship access.
23. **`db.flush()` vs `db.commit()` — when to use each:**
    - `flush()` — sends pending SQL to Postgres within the current transaction, populates database-generated values (e.g. `order.id`), but does NOT commit. Visible within the same session only.
    - `commit()` — finalises the transaction. Changes become permanent and visible to all connections.
    - Pattern in `create_order`: `flush()` after Order insert (to get `order.id`) → insert OrderItems using that ID → `commit()` everything together.

---

## SQLAlchemy Result Unwrapping

24. **`.scalars().all()` is two chained calls:**
    - `.scalars()` — unwraps each result row into an ORM object (equivalent to `scalar_one_or_none()` but for a collection)
    - `.all()` — materialises the result into a Python list
    Use for any query that returns multiple rows.
25. **`scalar_one_or_none()` vs `scalar_one()`:**
    - `scalar_one_or_none()` — unwraps into an ORM object, returns `None` if no row matched. Use when not-found is a valid, expected outcome.
    - `scalar_one()` — raises `NoResultFound` if nothing matched. Use when the row must exist and its absence is a programming error.
26. List comprehension is the clean pattern for bulk schema conversion:
    `[_build_order_read(order) for order in orders]` — applies the same helper to every item, no duplication, no loop with appends.

---

## create_order — Safety Sequence

27. **The order of operations in `create_order` is a deliberate safety sequence:**
    ```
    validate → flush → insert items → commit → enqueue task → reload
    ```
    - Validate all meal IDs before touching the DB — fail fast, no partial state
    - `flush()` after Order insert to get `order.id`
    - Insert OrderItems using that ID — all in one transaction
    - `commit()` — write everything to Postgres permanently
    - Enqueue Celery task *after* commit — worker must find the order in Postgres
    - Reload with `selectinload` — `db.refresh()` won't restore relationships
28. **`process_order.delay()` must be called after `db.commit()`.** If enqueued before commit, the worker may pick up the task before the transaction is visible to other connections — it queries Postgres, finds no row, and fails.
29. **The state machine is enforced in exactly one place.** `_VALID_TRANSITIONS` in `order_service.py` is the single source of truth. If a new state is added, there is exactly one place to update. A state machine scattered across multiple files is how bugs get introduced.

---

## Redis — When To Use It

Four conditions that justify caching a value in Redis:

30. High read frequency — data requested repeatedly by many users.
31. Data changes rarely relative to reads — low write-to-read ratio.
32. Staleness is tolerable — a few seconds of stale data won't break anything critical.
33. Cheap to rebuild — a cache miss falls through to Postgres and repopulates without cost.

**`list_orders` is intentionally not cached — `list_meals` is.** Menu data changes rarely; order status changes on every Celery transition. A cached order list would show stale statuses to polling clients. Cache only when data is stable enough that staleness is tolerable.

---

## Redis — Operational Rules

34. Always write to Postgres first. Redis is never the primary write target.
35. Every key must have a TTL — use `setex`, not `set`. A key without a TTL is a memory leak.
36. Every cache operation must be wrapped in `try/except` — Redis failure logs a warning, never crashes the app. Postgres is the source of truth; Redis is advisory.
37. Invalidate on write, rebuild lazily on next read (cache-aside pattern) — don't rebuild eagerly.
38. Cache the final serialised output — not the query, not the ORM object. Ready to serve on a cache hit.
39. Colon-separated key namespacing: `menu:all`, `order:status:{id}`. Prevents key collisions across concerns.
40. Fixed keys as module-level constants. Dynamic keys as functions (e.g. `order_status_key(order_id)`).
41. **`SETEX` is atomic** — sets the key and TTL together in one indivisible command. No gap between SET and EXPIRE. Use it instead of separate SET + EXPIRE calls.
42. **Cache invalidate-then-set, not just set.** In `update_order_status`: delete the old key first, then set the new one. `setex` would overwrite anyway, but explicit delete-then-set makes the intent unambiguous.

---

## Cache Invalidation Ownership

43. The **service layer** owns `menu:all` invalidation — called on every write to Meal or Ingredient.
44. The **Celery worker** owns `order:status:{id}` — updated at every state transition.
45. Invalidation = delete the key. Next read rebuilds from Postgres naturally. No eager repopulation.

---

## Redis Cache Candidates — Reasoning

46. `menu:all` — customers browse the menu before every order. Highest read frequency. Strong candidate.
47. `order:status:{id}` — customers poll this repeatedly while waiting for READY. Strong candidate.
48. `meal:{id}` — strongest third candidate. Nova's agent looks up a specific meal on every order (verify availability, check ingredients, confirm price). Redis read (~1ms) vs Postgres (~5–20ms under load) = meaningful latency reduction on the most frequent agent operation = better customer UX.
49. `ingredient:stock:{id}` — weaker candidate. Stock changes with every kitchen task; invalidation frequency is too high for a useful cache hit ratio.

---

## Atomicity — Redis vs PostgreSQL

50. **Redis atomic command** — a single Redis command is one indivisible unit. No other client can interleave. `SETEX` sets the key and TTL together — impossible to end up with a key that has no TTL.
51. **PostgreSQL atomic transaction** — a group of SQL statements that succeed or fail together. No partial state is ever visible to other connections. The basis of ACID guarantees.
52. **Shared core idea** — atomic means no observable half-finished state. Either fully done or not done at all — never in-between.
53. **Cross-system writes are NOT atomic** — a Postgres commit followed by a Redis invalidation are two separate operations. A stale cache window exists between them. Accepted tradeoff: slightly stale data for up to `cache_ttl_seconds`, never a crash. The non-fatal Redis pattern makes this safe.

---

## Postgres Full-Text Search

54. `tsvector` indexes text with language rules — stemming and stop words applied. `"spicy"` and `"Spicy"` both resolve to `spici`.
55. Combine name + tags with the `||` operator — one search vector covers both fields; one query matches either.
56. `plainto_tsquery` handles user input tokenisation and stemming automatically — safe to pass raw user input.
57. `@@` is the match operator — `tsvector @@ tsquery` = "does this text contain this search term?".

---

## Route Layer Responsibility Boundary

58. The route layer is the **HTTP translation layer** — nothing more. Four jobs only:
    - Translate HTTP input → typed Python (Pydantic)
    - Delegate to the service
    - Translate Python result → HTTP output (FastAPI)
    - Translate exceptions → HTTP error codes (try/except)
59. Business logic in a route is always wrong. Any conditional, calculation, or second service call belongs in the service layer — where it can be tested without HTTP context and called directly by Nova's agent tools.
60. Enforceability test: if you cannot describe a route body as "validate, delegate, respond" — something has leaked into the wrong layer.

---

## FastAPI Route Mechanics

61. `APIRouter(prefix=...)` carries the shared path prefix and tags. Routes declare only what comes after the prefix. An empty string `""` means "just the prefix".
62. Static path segments (`/search`) must be declared before dynamic segments (`/{meal_id}`) — FastAPI matches routes in declaration order. A dynamic segment will shadow a static one if declared first.
63. Route decorator parameters: `response_model` (output shape), `status_code` (default success code), `summary` (appears in OpenAPI/Swagger docs).
64. Route function signature: schema for the input body, `AsyncSession` via `Depends(get_db)`.
65. `IntegrityError` (SQLAlchemy) is caught at the route layer and converted to `HTTPException(409)`. Always call `db.rollback()` before raising — the session is in a broken state after an integrity violation.

---

## Celery Architecture

66. **Celery app has two Redis roles:**
    - **Broker** — message queue where delayed tasks are stored. FastAPI writes to it; workers read from it.
    - **Backend** — result store where worker outcomes are written after task completion.
    Both use the same Redis URL in this project. They are separate concerns — broker is the pipe, backend is the receipt.

67. **`task_acks_late=True`** — by default Celery acknowledges a task on *receipt* (broker removes it before work is done). With `acks_late`, acknowledgement happens only after task *completion*. A worker crash mid-execution means the broker requeues the task for another worker. No silent loss.

68. **`task_reject_on_worker_lost=True`** — if the worker process is killed by the OS (not just an exception), the task is explicitly rejected back to the queue rather than silently disappearing. Complements `acks_late`.

69. **Exchange and routing key (AMQP concepts)** — exchange is a router; tasks are sent to the exchange, not directly to a queue. The routing key is the label on the message. A `direct` exchange delivers to the queue whose routing key matches exactly. Celery follows this convention regardless of broker.

70. **Two queues: primary + DLQ** — `kitchen.orders` holds all incoming kitchen tasks. `kitchen.dlq` holds tasks that exhausted their retry budget. Separation keeps the primary queue clean for live traffic; DLQ is the holding area for failed tasks to inspect and debug.

71. **`result_expires=3600`** — Celery result backend entries expire after 1 hour. Postgres is the source of truth for order status; Celery results are transient. Expiry keeps Redis memory clean.

72. **`include=["src.tasks.kitchen"]`** — Celery worker imports this module at startup so it knows what `process_order` is when it pulls a task message from Redis. Without it, the worker receives the task name but has no function to run.

73. **JSON serialisation for all Celery messages** — `task_serializer`, `result_serializer`, `accept_content` all set to JSON. Everything written to Redis is JSON-encoded. No pickle — safer and human-readable for debugging.

74. **Two Redis keys, two different purposes (easy to confuse):**
    - `order:status:{id}` — cache key, written by the Celery worker via `set_cached_order_status()` at every state transition, read by `GET /orders/{id}`
    - Celery result backend key — internal Celery bookkeeping, the route layer never reads from it

---

## Celery Task Flow — FastAPI → Redis → Worker ⚠️ CRITICAL

75. **The task name string is the shared contract between two processes.** FastAPI writes it to Redis; the worker reads it and looks it up in its own registry. Neither process knows about the other — Redis is the only bridge.

76. **Two processes, one registry name — how they stay in sync:**
    - FastAPI process: imports `celery_app` + `kitchen.py` → registers task under `"kitchen.process_order"` → `delay()` writes that name to Redis
    - Worker process: imports `celery_app` + `kitchen.py` (via `include`) → registers task under same name → reads name from Redis → calls function
    - The name string must be identical in both processes. A mismatch means the worker receives a message it cannot route.

77. **Queue routing is determined by `task_default_queue`** — unless a task decorator specifies `queue=` explicitly, all tasks go to the default queue. The worker must listen on that same queue name.

78. **Simple mental model — each piece only talks to its neighbour:**
    - Client → FastAPI
    - FastAPI → Redis (broker)
    - Worker → Redis (broker) + Postgres + Redis (cache)
    - Client → FastAPI → Redis (cache)

    No piece jumps over another. That's what makes the system manageable.

---

## Full Request Flow — Client to Kitchen and Back

```
CLIENT
  │
  │  POST /orders  {"customer_name": "Eran", "items": [...]}
  │
  ▼
FASTAPI (api container)
  │
  │  1. Validates request (Pydantic)
  │  2. create_order() — writes Order + OrderItems to Postgres
  │  3. process_order.delay(order_id=42)
  │     → serialises {"task": "kitchen.process_order", "args": [42]}
  │     → pushes message to Redis list: kitchen.orders
  │
  │  4. Returns 201 OrderRead to client immediately
  │     (doesn't wait for the kitchen — order is PENDING)
  │
  ▼
REDIS (broker)
  │
  │  kitchen.orders queue:
  │  [ {"task": "kitchen.process_order", "args": [42]} ]  ← sitting here
  │
  ▼
CELERY WORKER (worker container)
  │
  │  1. Reads message from kitchen.orders
  │  2. Looks up "kitchen.process_order" in registry → finds function
  │  3. Calls process_order(42)
  │     → updates Order status: PENDING → PREPARING  (Postgres + Redis cache)
  │     → simulates prep time (sleep)
  │     → updates Order status: PREPARING → READY    (Postgres + Redis cache)
  │  4. Acknowledges task to broker (Redis removes message from queue)
  │  5. Writes result to Redis backend (expires in 1 hour — not the source of truth)
  │
  ▼
CLIENT (polling GET /orders/42)
  │
  │  Route checks Redis cache: order:status:42 → "READY"
  │  Returns OrderRead {status: "READY"} instantly — no Postgres hit
```

**Key insight:** FastAPI returns to the client at step 4 — before the kitchen does any work. The client gets an order ID and starts polling. The worker runs completely independently and asynchronously. Redis is the only thing connecting them.
