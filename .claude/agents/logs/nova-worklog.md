# Nova — Worklog

## Session Index

| # | Commit | Status | Key Decision |
|---|--------|--------|--------------|
| 01 | `langgraph-agent-foundation` | ✅ Done | Graph nodes are async + routing is deterministic state-field reads — zero LLM calls for routing, zero asyncio.run() wrappers needed |

---

## Session 01 — Commit 11: `langgraph-agent-foundation`

**Date:** 2026-04-24
**Status:** Done

### Task Brief

Build the LangGraph state machine foundation: `AgentState`, all graph nodes, conditional branching, tool output schemas (as stubs), system prompt, circuit breaker scaffold, and the `POST /agent/chat` route stub. No live DB calls yet — tools are placeholders so the graph compiles and branches correctly.

The AI problem being solved: a customer sends natural language. The agent must understand intent, find matching meals, check availability, offer substitutes if needed, and dispatch a confirmed order. All of this must be predictable, debuggable, and fail gracefully when the LLM or tools misbehave.

### Cognitive Architecture Sketch (written before opening any files)

**Data flow through each node:**

```
START
  |
  v
[understand_request]
  IN:  state.messages (raw customer message)
  LLM: extract intent + meal preferences from natural language
  OUT: updated state.messages (with assistant's parsed understanding)
  FAIL: catch LLM exception → set state.error → route to apologise
  |
  v
[search_meals_node]
  IN:  state.messages (contains extracted search query)
  TOOL: search_meals(query) → list[MealResult]
  OUT: state.meals_found
  BRANCH: if meals_found is empty → apologise (no results)
         if meals_found non-empty → check_availability_node
  FAIL: catch tool exception → set state.error → route to apologise
  |
  v
[check_availability_node]
  IN:  state.meals_found[0].id (check the first / most relevant meal)
  TOOL: check_ingredients(meal_id) → AvailabilityResult
  OUT: state.availability
  BRANCH: availability.available=True  → present_options_node
          availability.available=False → find_substitutes_node
  FAIL: catch tool exception → set state.error → route to apologise
  |
  v (available branch)
[present_options_node]
  IN:  state.meals_found, state.substitutes (whichever is populated)
  LLM: format meal options as readable customer message
  OUT: updated state.messages
  FAIL: catch LLM exception → set state.error → route to apologise
  |
  v
[confirm_and_dispatch_node]
  IN:  state.messages (customer confirmation in latest message)
  LLM: check if customer confirmed, call dispatch_order tool
  TOOL: dispatch_order(meal_ids, quantities, customer_name) → OrderResult
  OUT: state.order_id, updated state.messages
  FAIL: catch LLM or tool exception → set state.error → route to apologise
  |
  v
END

  v (unavailable branch from check_availability)
[find_substitutes_node]
  IN:  state.meals_found[0].id
  TOOL: find_substitutes(meal_id) → list[MealResult]
  OUT: state.substitutes
  BRANCH: len(substitutes) > 0 → present_options_node
          len(substitutes) == 0 → apologise_node
  FAIL: catch tool exception → set state.error → route to apologise
  |
  v (substitutes found — merges back to present_options_node)

[apologise_node]
  IN:  state (error message or empty results context)
  LLM: generate empathetic "nothing available" message
  OUT: updated state.messages
  FAIL: catch LLM exception → return minimal fallback message (no re-raise)
  |
  v
END
```

**Key design decisions made during the sketch:**

1. **Tool calls live inside graph nodes, not as LangChain ToolNode** — The spec calls for explicit nodes that call tools. Using LangChain's `ToolNode` would route via tool-call message parsing, which adds a layer of LLM interpretation between each tool invocation. Our graph structure is deterministic: `check_availability_node` always calls `check_ingredients`, period. The routing after the tool call is also deterministic (based on `availability.available`). This is cleaner and more debuggable than a generic ToolNode router.

2. **Conditional routing reads state fields directly** — After `check_availability_node`, the edge function reads `state["availability"].available`. After `find_substitutes_node`, it reads `len(state["substitutes"]) > 0`. No LLM involved in routing decisions. This satisfies the "use as little AI as possible" principle.

3. **Error state routes to `apologise`** — Any node that catches an exception sets `state["error"]` and returns. The conditional edges after each node check `state["error"]` first — if set, route to `apologise`. This means `apologise` serves double duty: "nothing available" and "something broke". The prompt handles both cases gracefully.

4. **`understand_request` uses `model.bind_tools`** — The first node and `confirm_and_dispatch` need tool access. `understand_request` does not need to call tools in Commit 11 (stubs only) but the binding is wired so Commit 12 can add real tools without touching the graph structure.

5. **LLM provider selected at graph compile time** — `get_settings().llm_provider` determines which LangChain model is instantiated. The graph does not re-read settings at invocation time.

### Decisions Made

**1. `AgentState.availability` typed as `AvailabilityResult | None`.**
The commit spec specifies `availability: AvailabilityResult | None` — I'm matching that. The `None` case is the initial state before `check_availability_node` runs. Conditional edges must check `if state["availability"] is not None` before accessing `.available`. This is explicit rather than relying on a truthy check on the object itself.

**2. `MealResult` defined in `tools.py`, not imported from Rex's schemas.**
Rex's `MealRead` schema has the same fields. Using it directly would create a hard dependency between the agent layer and the service schema layer. `MealResult` is intentionally a separate Pydantic model — it is the tool's output contract, not the service layer's output contract. If Rex changes `MealRead` (e.g., adds a field), my tool stub can adapt the shape independently. For now they happen to be identical but the boundary is correct.

**3. Circuit breaker scaffold uses `pybreaker.CircuitBreaker` with threshold=3, cooldown=60.**
This matches the spec. The class wraps LLM calls with a `call()` method. In Commit 14, graph nodes will call `llm_circuit_breaker.call(llm.invoke, messages)` instead of `llm.invoke(messages)` directly. The scaffold just instantiates and exposes the breaker — graph nodes in this commit call LLM directly (Commit 14 wires the breaker in).

**4. `POST /agent/chat` route is a stub that returns a placeholder response.**
The real implementation is Commit 13. The stub must: (a) compile without errors, (b) include the router in `main.py`. The stub uses `ChatRequest` / `ChatResponse` Pydantic schemas defined in the route file itself (not in Rex's schemas/ — these are agent-specific shapes).

**5. System prompt structure: role → task → constraints → output format → examples.**
Following the prompt-is-code standard. Every constraint is negative and explicit. One few-shot example is included for the search-and-present flow. Comments explain why each constraint exists.

**6. `graph.compile()` called with `recursion_limit=25`.**
A cycle in the graph (e.g., a bug where `present_options` routes back to `understand_request`) would otherwise loop indefinitely. 25 is generous enough for the longest valid path (8 nodes) while catching runaway loops quickly.

**7. `understand_request` node binds all four tools to the LLM.**
Even though this node only needs to understand intent (not call tools), binding all tools ensures the model can reference tool schemas when formulating its understanding. More importantly, it means the same `model_with_tools` object is reusable across all LLM-calling nodes without re-binding per node.

**8. Node functions follow the signature `(state: AgentState) -> dict[str, object]`.**
LangGraph node functions return a dict of state field updates (not a full new state). The `object` type on the dict value is `Any`-equivalent — unavoidable because the values are heterogeneous (lists, objects, strings). Documented with `# type: ignore` comments where needed.

**9. `search_meals_node` also handles the "no results" case deterministically.**
If `meals_found` is empty, the conditional edge after `search_meals_node` routes to `apologise`. No LLM call needed to decide this — empty list is a clear signal.

**10. All node functions are `async def`.**
Initial design had sync node functions with `asyncio.run()` wrappers to call async tool stubs. This is wrong: `asyncio.run()` inside a node fails when the graph is invoked from an already-running event loop (FastAPI's async context). The correct pattern is async node functions + `graph.ainvoke()` from the route handler. All tool `ainvoke()` calls work naturally inside async nodes. This decision locks in that the route handler (Commit 13) must use `await graph.ainvoke(state, config={"recursion_limit": 25})`, not `graph.invoke()`.

### Failure Modes Considered

| Node | Exception case | Guard |
|---|---|---|
| `understand_request` | LLM call fails | try/except → set `state["error"]` |
| `search_meals_node` | Tool raises | try/except → set `state["error"]` |
| `check_availability_node` | Tool raises | try/except → set `state["error"]` |
| `find_substitutes_node` | Tool raises | try/except → set `state["error"]` |
| `present_options_node` | LLM call fails | try/except → set `state["error"]` |
| `confirm_and_dispatch_node` | LLM or tool fails | try/except → set `state["error"]` |
| `apologise_node` | LLM call fails | try/except → return fallback string (no re-raise) |
| Graph routing | Unexpected loop | `recursion_limit=25` on compile |
| LLM provider down | Repeated failures | circuit breaker opens after 3 failures (Commit 14) |

The `apologise_node` is special: it is the final fallback. If the LLM call inside `apologise` also fails, the node must not re-raise — it returns a hardcoded fallback message. This prevents the customer from seeing a Python traceback.

### Self-Review Checklist

- [x] `state.py` — `AgentState` matches spec exactly, `availability` typed as `AvailabilityResult | None`
- [x] `tools.py` — `MealResult`, `AvailabilityResult`, `OrderResult` are Pydantic models (not dataclasses or dicts)
- [x] `tools.py` — all four tool stubs have correct return type annotations
- [x] `tools.py` — stubs return typed dummy values (not `None`) so graph can be tested
- [x] `prompts/assistant.py` — structure: role → task → constraints → output format → examples
- [x] `prompts/assistant.py` — at least one negative constraint per section
- [x] `circuit_breaker.py` — imports cleanly, `LLMCircuitBreaker` class is instantiatable
- [x] `graph.py` — `StateGraph(AgentState)` with all 7 nodes added
- [x] `graph.py` — all edges and conditional edges wired
- [x] `graph.py` — `recursion_limit=25` on compile
- [x] `graph.py` — `graph.compile()` runs without error (verified via smoke test)
- [x] `agent.py` — `POST /agent/chat` route compiles, included in `main.py`
- [x] No `Any` in type hints without comment explanation
- [x] No direct DB access from agent code in this commit (stubs return dummy values)
- [x] No raw SQL anywhere in agent files

### Scope Overflow Check

The tool stubs in this commit intentionally return dummy values. The real DB-calling logic belongs to Commit 12 (`agent-tools`) and Commit 13 (`agent-order-dispatch-tool`). Nothing from Commits 12/13 has been pre-built.

The circuit breaker scaffold belongs to this commit by spec. The wiring into graph nodes belongs to Commit 14. The scaffold is created but not wired — exactly right.

### Documentation Flags for Claude

```
📋 Documentation flags for Claude:

ARCHITECTURE.md:
- New component: src/agents/ — LangGraph AI assistant; state machine with 7 nodes, 2 conditional edges; handles natural language → meal search → availability check → order dispatch
- New component: src/agents/state.py — AgentState TypedDict; 6 fields tracking conversation and tool results
- New component: src/agents/tools.py — tool output schemas (MealResult, AvailabilityResult, OrderResult) and stub tool functions; real DB logic in Commit 12
- New component: src/agents/prompts/assistant.py — system prompt defining agent role, constraints, output format, and one few-shot example
- New component: src/agents/circuit_breaker.py — LLMCircuitBreaker scaffold; pybreaker-backed; threshold=3, cooldown=60s; wired into nodes in Commit 14
- New component: src/api/routes/agent.py — POST /agent/chat route stub; real implementation in Commit 13
- Updated: src/main.py — agent router included

DECISIONS.md:
- Tool calls inside graph nodes (not via LangChain ToolNode) — deterministic routing; each node calls exactly the tool it is designed for; no LLM interpretation needed to decide which tool to call next
- Conditional routing reads state fields directly — availability.available and len(substitutes) are code-level checks; zero LLM calls for routing decisions
- MealResult is a separate schema from MealRead — agent tool output contract is independent of Rex's service schema; shields agent from upstream schema changes
- apologise_node has a hardcoded fallback — if the LLM inside apologise also fails, the customer sees a clear message, not a traceback
- graph compiled with recursion_limit=25 — bounds runaway loops; 25 is 3x the longest valid path (8 nodes)
- All graph nodes are async def — prevents asyncio.run() inside FastAPI event loop; Commit 13 route handler must use await graph.ainvoke(state, config={"recursion_limit": 25})

GLOSSARY.md:
- AgentState: TypedDict that flows through all LangGraph nodes; the single mutable context object for one conversation turn
- AvailabilityResult: structured tool output from check_ingredients; available: bool + missing: list[str]; enables agent to reason about which specific ingredients are out
- MealResult: agent-layer representation of a meal; separate from MealRead schema to maintain tool output independence from service layer
- Circuit breaker: pybreaker wrapper around LLM calls; opens after 3 failures, resets after 60s cooldown; prevents hung requests when LLM provider is down
```

---

## Handoff → Claude

What the agent does: A LangGraph state machine that handles the full sushi ordering flow. The customer sends a natural language message. The `understand_request` node uses an LLM to parse intent and preferences. The `search_meals_node` calls the `search_meals` tool to find matching meals and stores results in `state.meals_found`. The `check_availability_node` calls `check_ingredients` on the first result and stores the `AvailabilityResult` in `state.availability`. If available, the graph routes to `present_options` (LLM formats the options for the customer) then `confirm_and_dispatch` (LLM confirms the order and calls `dispatch_order`). If unavailable, the graph routes to `find_substitutes`, then either back to `present_options` (if substitutes were found) or to `apologise` (if none). All error states route to `apologise`. The graph compiles with `recursion_limit=25`.

Agent route: POST /agent/chat — request: `{"message": str, "customer_name": str}` — response: `{"reply": str, "order_id": int | null}`

Tools registered:
- `search_meals(query: str)` — searches meals by natural language query; returns `list[MealResult]` (stub in Commit 11, real DB in Commit 12)
- `check_ingredients(meal_id: int)` — checks ingredient stock for a meal; returns `AvailabilityResult` (stub in Commit 11, real DB in Commit 12)
- `find_substitutes(meal_id: int)` — finds available substitute meals; returns `list[MealResult]` (stub in Commit 11, real DB in Commit 12)
- `dispatch_order(meal_ids: list[int], quantities: list[int], customer_name: str)` — places order via POST /orders; returns `OrderResult` (stub in Commit 11, httpx implementation in Commit 13)

Error states:
- Any node LLM failure: sets `state.error`, routes to `apologise_node`, returns hardcoded fallback if `apologise` LLM also fails
- Tool exception: sets `state.error`, routes to `apologise_node`
- LLM provider repeated failures: circuit breaker opens after 3 failures (wired in Commit 14; scaffold only in Commit 11)
- Empty meal search: routes to `apologise_node` (deterministic, no LLM call)
- No substitutes found: routes to `apologise_node` (deterministic, no LLM call)

Files to read: `src/agents/graph.py`, `src/agents/state.py`, `src/agents/tools.py`, `src/agents/prompts/assistant.py`, `src/agents/circuit_breaker.py`, `src/api/routes/agent.py`

I'm done. You can start.

— Nova
