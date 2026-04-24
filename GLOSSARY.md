# GLOSSARY.md — Sushi Shop

> Canonical definitions for terms used across this project.
> Updated at commit time when a new concept or term is introduced.
> If a term appears in code, docs, or conversation — it is defined here.

---

## A

**AgentState**
The `TypedDict` that flows through every node in the LangGraph sushi assistant graph. Contains six fields: `messages` (full conversation history), `meals_found` (search results), `availability` (ingredient check result), `substitutes` (alternative meals), `order_id` (set on successful order dispatch), and `error` (set when any node catches an exception). Conditional edge functions read these fields to make routing decisions deterministically. Defined in `src/agents/state.py`. Introduced in Commit 11.

**AvailabilityResult**
A Pydantic model returned by the `check_ingredients` agent tool. Contains `available: bool` and `missing: list[str]` (ingredient names that are out of stock). Returns structured data rather than a boolean so the LLM can reason about which specific ingredients are missing — useful for explaining unavailability to the customer and for making informed substitute suggestions. Defined in `src/agents/tools.py`. Introduced in Commit 11.

---

## C

**Circuit Breaker**
A fault-tolerance pattern that wraps calls to an external dependency (here, the LLM provider). The breaker has three states: CLOSED (normal), OPEN (failing — all calls rejected immediately), and HALF-OPEN (recovery probe). When consecutive failures exceed the threshold (3), the breaker opens. After a cooldown (60s), one probe call is allowed; if it succeeds, the breaker closes. If it fails, the cooldown restarts. In the sushi agent, `LLMCircuitBreaker` in `src/agents/circuit_breaker.py` wraps LLM calls so that a down provider returns an immediate "assistant unavailable" message rather than hanging the customer's request. Wired into graph nodes in Commit 14. Scaffolded in Commit 11.

---

## D

**DLQ (Dead Letter Queue)**
A holding queue for Celery tasks that have failed after all retry attempts. Instead of silently dropping a failed kitchen task, the worker routes it to the DLQ. The DLQ handler sets the order status to `FAILED` in Postgres and logs the failure reason. This makes failures inspectable and recoverable rather than invisible. Introduced in Commit 10.

---

## M

**MealResult**
A Pydantic model returned by the `search_meals` and `find_substitutes` agent tools. Contains `id`, `name`, `description`, `price`, `tags`, and `is_available`. Defined independently of `MealRead` (Rex's REST schema) — the tool output contract is stable regardless of service schema changes. The `id` field is critical: it is passed to `check_ingredients` and `find_substitutes` in subsequent tool calls. Defined in `src/agents/tools.py`. Introduced in Commit 11.

---
