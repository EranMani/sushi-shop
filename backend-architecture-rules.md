# Backend Architecture Rules

Rules and tradeoffs established during code reviews of the Sushi Shop backend.
Covers schema design, service layer, Redis caching, Postgres FTS, and the FastAPI route layer.

---

## Schema Design

1. `*Create` = input (validation constraints, no `id`). `*Read` = output (`from_attributes=True`, ORM-safe). Never interchangeable.
2. Service layer always returns `*Read` — the ORM object stays internal; callers get clean, serialisable Pydantic models.
3. `*Create` schemas are staff-only. Customers never trigger create operations directly.

---

## Service Layer

4. Returns `None` for not-found when multiple callers exist — each caller (route, agent, test) handles it differently. Route raises `HTTPException(404)`, agent routes to an apology, test asserts `None`.
5. Domain exceptions (e.g. `IngredientNotFoundError`) make sense only when there is a single caller — more expressive and cleaner than `None` in that case.
6. Caller-neutral — no FastAPI imports, no HTTP concepts. `AsyncSession` injected as a parameter. Each caller speaks its own language on top.

---

## Redis — When To Use It

Four conditions that justify caching a value in Redis:

7. High read frequency — data requested repeatedly by many users.
8. Data changes rarely relative to reads — low write-to-read ratio.
9. Staleness is tolerable — a few seconds of stale data won't break anything critical.
10. Cheap to rebuild — a cache miss falls through to Postgres and repopulates without cost.

---

## Redis — Operational Rules

11. Always write to Postgres first. Redis is never the primary write target.
12. Every key must have a TTL — use `setex`, not `set`. A key without a TTL is a memory leak.
13. Every cache operation must be wrapped in `try/except` — Redis failure logs a warning, never crashes the app. Postgres is the source of truth; Redis is advisory.
14. Invalidate on write, rebuild lazily on next read (cache-aside pattern) — don't rebuild eagerly.
15. Cache the final serialised output — not the query, not the ORM object. Ready to serve on a cache hit.
16. Colon-separated key namespacing: `menu:all`, `order:status:{id}`. Prevents key collisions across concerns.
17. Fixed keys as module-level constants. Dynamic keys as functions (e.g. `order_status_key(order_id)`).

---

## Cache Invalidation Ownership

18. The **service layer** owns `menu:all` invalidation — called on every write to Meal or Ingredient.
19. The **Celery worker** owns `order:status:{id}` — updated at every state transition (PENDING → PREPARING → READY → FAILED).
20. Invalidation = delete the key. Next read rebuilds from Postgres naturally. No eager repopulation.

---

## Redis Cache Candidates — Reasoning

21. `menu:all` — customers browse the menu before every order. Highest read frequency in the system. Strong candidate.
22. `order:status:{id}` — customers poll this repeatedly while waiting for READY. Strong candidate.
23. `meal:{id}` — strongest third candidate. Nova's agent looks up a specific meal on every order to verify availability, check ingredients, and confirm price. Redis read (~1ms) vs Postgres (~5–20ms under load) = meaningful latency reduction on the most frequent agent operation = better customer UX.
24. `ingredient:stock:{id}` — weaker candidate. Stock changes with every kitchen task; invalidation frequency is too high for a useful cache hit ratio.

---

## Atomicity — Redis vs PostgreSQL

25. **Redis atomic command** — a single Redis command is one indivisible unit. No other client can interleave. `SETEX` sets the key and TTL together — impossible to end up with a key that has no TTL.
26. **PostgreSQL atomic transaction** — a group of SQL statements that succeed or fail together. No partial state is ever visible to other connections. The basis of ACID guarantees.
27. **Shared core idea** — atomic means no observable half-finished state. Other clients see the operation as fully done or not done at all — never in-between.
28. **Cross-system writes are NOT atomic** — a Postgres commit followed by a Redis invalidation are two separate operations. A stale cache window exists between them. Accepted tradeoff: slightly stale data for up to `cache_ttl_seconds`, never a crash. The non-fatal Redis pattern makes this safe.

---

## Postgres Full-Text Search

29. `tsvector` indexes text with language rules — stemming and stop words applied. `"spicy"` and `"Spicy"` both resolve to `spici`.
30. Combine name + tags with the `||` operator — one search vector covers both fields; one query matches either.
31. `plainto_tsquery` handles user input tokenisation and stemming automatically — safe to pass raw user input.
32. `@@` is the match operator — `tsvector @@ tsquery` = "does this text contain this search term?".

---

## Route Layer Responsibility Boundary

33. The route layer is the **HTTP translation layer** — nothing more. Four jobs only:
    - Translate HTTP input → typed Python (Pydantic)
    - Delegate to the service
    - Translate Python result → HTTP output (FastAPI)
    - Translate exceptions → HTTP error codes (try/except)
34. Business logic in a route is always wrong. Any conditional, calculation, or second service call belongs in the service layer — where it can be tested without HTTP context and called directly by Nova's agent tools.
35. Enforceability test: if you cannot describe a route body as "validate, delegate, respond" — something has leaked into the wrong layer.

---

## FastAPI Route Mechanics

36. `APIRouter(prefix=...)` carries the shared path prefix and tags. Routes declare only what comes after the prefix. An empty string `""` means "just the prefix".
37. Static path segments (`/search`) must be declared before dynamic segments (`/{meal_id}`) — FastAPI matches routes in declaration order. A dynamic segment will shadow a static one if declared first.
38. Route decorator parameters: `response_model` (output shape), `status_code` (default success code), `summary` (appears in OpenAPI/Swagger docs).
39. Route function signature: schema for the input body, `AsyncSession` via `Depends(get_db)`.
40. `IntegrityError` (SQLAlchemy) is caught at the route layer and converted to `HTTPException(409)`. Always call `db.rollback()` before raising — the session is in a broken state after an integrity violation.
