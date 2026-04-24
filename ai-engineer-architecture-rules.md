# AI Engineer Architecture Rules

Rules and thinking patterns established during the LangGraph agent build for the Sushi Shop.
Covers the full integration of an LLM agent into an existing production service layer —
how to approach it, what to design first, where agents fail in production, and the patterns
that separate a reliable agent from a demo that breaks under load.

Grounded in the decisions made in Commits 11–14 of this project.

---

## Integration Philosophy — How to Approach Wiring an Agent into an Existing System

1. **Start with the data flow, not the LLM.** Before writing a single node or prompt, map every step between the customer's input and the final outcome. For each step, answer one question: does this step require natural language understanding, or is it deterministic logic? LLM calls go where language understanding is genuinely needed. Code handles everything else. In this project: understanding the customer's request and generating responses are LLM steps. Routing based on availability, branching on empty results — that is all code.

2. **The existing service layer is a black box with a defined contract.** When joining a project that already has services, routes, and a DB — treat them as external APIs. Don't reach into the service internals; call the public functions. This guarantees that every validation, state machine rule, and business invariant the backend enforces also applies to the agent. Rex's `POST /orders` route validates, enqueues Celery, and enforces the state machine. If the agent bypasses the route and calls the service directly, it silently skips all of that — and has to be updated separately every time Rex adds validation.

3. **Map what already exists before designing what you need.** Before writing any agent code, read every service function signature and understand what it returns. In this project: `meal_service.search_meals()` returns a `MealListResponse` wrapper. `order_service.create_order()` raises `ValueError` with specific messages on invalid meals. `get_order_status()` is a separate lightweight function that checks Redis first. These details determine tool design — you cannot design tool output schemas without knowing what the service layer returns.

4. **Sketch the graph on paper before opening any files.** Five minutes of diagramming prevents two hours of refactoring a graph that has the wrong shape. Write: what goes into each node, what decision is made, what state field is written, where the failures can occur. Then write the code. The cognitive architecture sketch goes in the worklog before any file is opened.

---

## State Design — `AgentState`

5. **`AgentState` is a `TypedDict`, not a Pydantic model.** LangGraph requires TypedDict for its state management and merging machinery. When a node returns a partial dict, LangGraph merges it into the current state using the TypedDict schema. A Pydantic model would work for validation but does not participate in LangGraph's merge cycle.

6. **Every field must be present in the initial state dict.** TypedDict does not support truly optional keys at runtime. Create a factory function (`make_initial_state()`) that initialises all fields to their zero values — empty lists, `None`, no `error`. Nodes fill in fields as they run; the graph should never encounter a `KeyError` on a state field.

7. **The `error` field is a routing signal, not just logging.** When any node catches an exception, it sets `state["error"]` with a short description. Every conditional edge function checks `state.get("error")` first — if set, route to the apology node. This means a single exception anywhere in the graph always terminates gracefully, regardless of where in the flow it happened.

8. **State fields map to graph phases, not to database columns.** `meals_found`, `availability`, `substitutes`, `order_id` each correspond to one phase of the agent's job. A node that runs a phase populates exactly its field. This 1:1 mapping makes the graph readable — looking at the final state, you can reconstruct exactly which nodes ran and what they produced.

---

## Graph Structure — The Pattern to Follow

The standard pattern for a production LangGraph agent that calls tools in a fixed sequence:

```
START
  └→ [LLM node: understand intent]
        └→ [Tool node: search]
              └→ [Tool node: check result]
                    ├→ [result A]  → [LLM node: present options]
                    └→ [result B]  → [Tool node: fallback]
                                          ├→ [found]  → [LLM node: present options]
                                          └→ [none]   → [LLM node: apologise]
  [LLM node: present options]
        └→ [LLM node: confirm + dispatch]
              └→ END
  [LLM node: apologise] → END
```

9. **Two types of nodes: LLM nodes and tool nodes.** LLM nodes call the language model to understand or generate. Tool nodes call a service function (or API) to fetch or mutate data. Keep them separate — a node that both calls the LLM and calls a service is doing two jobs and has two failure modes. Each node has one responsibility.

10. **Tool nodes call exactly one tool.** The node for checking availability calls `check_ingredients` and nothing else. The node for finding substitutes calls `find_substitutes` and nothing else. Don't let a single node make multiple service calls based on a conditional — split it into two nodes with an edge between them.

11. **All nodes are `async def`.** FastAPI route handlers are async. `graph.ainvoke()` is the mandatory invocation pattern inside an async route. If nodes were sync and called `asyncio.run()` internally, you would hit `RuntimeError: This event loop is already running` — Python does not allow nested event loops. Async nodes invoked via `graph.ainvoke()` run natively in the existing event loop with no bridging.

12. **Compile the graph as a module-level singleton.** `graph = _build_graph().compile()` runs at import time. `graph.ainvoke()` is safe to call concurrently — LangGraph creates independent state copies per invocation. The compiled graph is not mutated at runtime. If the LLM setup fails (missing API key, wrong provider), you want that failure at startup, not on the first customer request.

13. **`recursion_limit` is a runtime config, not a compile-time setting.** Pass it at invocation:
    ```python
    await graph.ainvoke(state, config={"recursion_limit": 25})
    ```
    Without a limit, a graph with conditional edges and unexpected state can loop indefinitely, burning tokens and blocking the request indefinitely.

---

## Routing — Determinism as a Rule

14. **Routing is always deterministic code. Never an LLM call.** Conditional edge functions read state fields and return a node name string. No exceptions. The question "did the availability check pass?" is answered by `state["availability"].available` — a boolean — not by asking the model whether availability looks good. Using the LLM to route produces inconsistent phrasing, adds latency, burns tokens, and is unpredictable by design.

15. **Every routing function checks `state["error"]` first.** Before any other condition, check for the error signal. If set, route to `apologise_node`. This convention means one error check pattern handles failures from every upstream node uniformly.

16. **Routing functions should be pure and cheap.** A routing function that does I/O or computation is a sign that logic which belongs in a node has leaked into the edge. Routing reads state; nodes produce state.

17. **The failure mode nobody talks about: the LLM calling tools in the wrong order.** In a naive ReAct loop, all tools are available and the model decides what to call next. In production this produces conversations where the model calls `dispatch_order` before the customer confirmed, or calls `check_ingredients` before any meal ID is in state. The fix is not a better prompt — it is architecture. Structure the graph so that the decision to call a tool is not made by the LLM. Each node makes exactly one tool call, at the point in the graph where that call is appropriate. The routing function decides what runs next; the LLM does not.

---

## Tool Design — What to Register and Why

18. **Design the output schema before the implementation.** Ask: what does the agent need to reason about, and what is the minimal structured representation of that? A tool that returns too much dilutes the model's attention. A tool that returns too little forces the model to guess. For every output field: if the LLM cannot use it directly in a routing decision or a natural language response — leave it out.

19. **Tool output schemas are independent of service layer schemas.** `MealResult` in `tools.py` is not imported from `src/schemas/meal.MealRead`. They happen to have similar fields now — that convergence is expected to diverge. Rex's `MealRead` evolves with the API contract (pagination metadata, extra fields, renamed attributes). The agent tool output contract must be stable for the LLM's reasoning to remain consistent. Couple them and Rex's schema changes break the agent.

20. **Return structured types, never strings.** `AvailabilityResult(available=True, missing=[])` — not `"available"`. `list[MealResult]` — not `"Spicy Tuna Roll ($12.50)\nSalmon Roll ($10.00)"`. Free-form string output forces the LLM to parse it before reasoning about it. Structured output is directly usable. This is a reliability boundary: a parsed string is one hallucination away from a wrong routing decision; a boolean field is not.

21. **`missing: list[str]` carries ingredient names, not IDs.** The LLM communicates with the customer in natural language. Ingredient IDs are useless to a language model generating a response like "sorry, we're out of tuna." Names are directly usable. IDs require a secondary lookup that adds latency and an extra failure point. When designing tool output for an LLM, prefer human-readable values everywhere.

22. **Register all tools on a single LLM instance — not separately per node.** `llm.bind_tools([search_meals, check_ingredients, find_substitutes, dispatch_order])` is called once. Every node that calls the LLM gets the full tool set. This avoids creating multiple LLM instances with different tool configurations and simplifies circuit breaker wiring (one LLM instance to wrap, not four).

23. **The `dispatch_order` tool calls `POST /orders` via httpx — not the service function directly.** This keeps the agent decoupled from internal implementation. Rex's route handler validates, enqueues Celery, enforces the state machine, and will continue to do so as the backend evolves. If the agent called `create_order()` directly, every new validation Rex adds to the route would have to be mirrored in the agent tool. The HTTP boundary absorbs those changes automatically.

---

## Prompts — Writing Them as Code

24. **One prompt per node, scoped to that node's task.** `UNDERSTAND_REQUEST_PROMPT` focuses the model on intent extraction and calling `search_meals`. It explicitly says: call the tool, do not present options yet. `PRESENT_OPTIONS_PROMPT` focuses on formatting. `CONFIRM_AND_DISPATCH_PROMPT` focuses on confirmation detection. A single monolithic system prompt that tells the model "here are all the tools, figure out what to do" produces inconsistent behavior across turns.

25. **Prompt structure: role → task → constraints → output format → examples.** Every prompt in this order. Role establishes who the model is. Task states exactly what to do in this step. Constraints are negative and explicit: "Do NOT invent meal names. Only use meals returned by the search_meals tool." Output format specifies exactly what the response should look like. One concrete few-shot example is worth three paragraphs of instruction.

26. **Constraints exist to prevent hallucination at specific failure points.** Every "Do NOT" in a prompt corresponds to a real failure mode that the model will hit without the constraint. "Do NOT call dispatch_order more than once per conversation turn" — without this, a model that gets confused mid-conversation may attempt to place a duplicate order. "Do NOT invent meal names" — without this, the model will confidently recommend a Salmon Dragon Roll that does not exist on the menu. Document the failure mode the constraint prevents with a comment in the prompt file.

27. **Prompts are stored in `src/agents/prompts/` — never inlined in graph nodes.** Inlining prompts in node functions mixes specification with control flow, makes the prompts hard to read or compare, and makes A/B testing impossible. The prompt file is the specification the model executes — treat it like the source code it is.

---

## Error Handling — Failure Paths in Agent Graphs

28. **Every node has a `try/except` that sets `state["error"]`.** Not every node that might fail — every node. Assume any LLM call or service call can raise. Catching and routing to the apology path is always better than letting an unhandled exception propagate to the route handler as a 500.

29. **The apology node is the terminal error handler — it must never re-raise.** `apologise_node` is the last line of defense. If the LLM call inside it also fails, return a hardcoded `AIMessage` with a generic "I'm having trouble right now" message. A Python traceback reaching the customer is always worse than a generic canned response. The hardcoded fallback is not a compromise — it is a deliberate design choice: the customer always gets a response.

30. **The error signal (`state["error"]`) is checked by every routing function before any other condition.** Once set, the error propagates through the rest of the graph automatically — every routing function that fires next will route to `apologise_node`. The node that catches the exception does not need to know the graph topology; it just sets the field.

31. **`on_failure` hooks (Celery, retries) must not re-raise.** The same principle applies outside the agent graph: a failure handler that raises a new exception causes a secondary failure with confusing logs and potentially undefined behavior. Catch, log, produce the correct side effect (FAILED status, DLQ tombstone), and return.

---

## The Agent-API Boundary — Connecting FastAPI to LangGraph

32. **The route handler is a thin shell around `graph.ainvoke()`.** Four jobs only: build initial state, invoke the graph, extract the last `AIMessage` from the final state's messages, return `ChatResponse(reply=..., order_id=...)`. No business logic in the route. If you cannot describe the route body as "build state, invoke, extract, respond" — something has leaked into the wrong layer.

33. **`POST /agent/chat` has its own request/response schemas — not Rex's schemas.** `ChatRequest` and `ChatResponse` are agent-specific Pydantic models in `src/api/routes/agent.py`. The agent route has a distinct API contract: `{message, customer_name}` in, `{reply, order_id}` out. Reusing `OrderCreate` or `OrderRead` would couple the agent's public API to the internal order schema — a coupling that would break the agent every time Rex changes his schemas.

34. **The route handler must use `graph.ainvoke()` — not `graph.invoke()`.** The route is `async def`. Calling the sync `graph.invoke()` inside an async function blocks the event loop for the duration of the LLM call — all concurrent requests wait. `graph.ainvoke()` yields control to the event loop during LLM and tool calls, letting other requests proceed.

35. **Pass `recursion_limit` in the invocation config, not at compile time.** LangGraph's current pattern:
    ```python
    config = {"recursion_limit": 25}
    final_state = await graph.ainvoke(initial_state, config=config)
    ```
    This is a runtime config — compile-time settings are different. The route handler sets this per-invocation so individual requests cannot blow past the limit.

---

## Circuit Breaker — Reliable LLM Calls

36. **Every LLM call must be wrapped in a circuit breaker.** Without one: the LLM provider goes down, requests hang until timeout, the thread pool fills, subsequent requests queue behind hanging ones, the service becomes unavailable for everyone. With one: after 3 failures, the breaker opens, subsequent calls return immediately with `CircuitBreakerError`, the node catches it, sets `state["error"]`, the customer gets an instant "unavailable" message. The failure is isolated and bounded.

37. **Threshold=3, cooldown=60s is the conservative starting point.** Three failures before opening means a single rate-limit blip or transient error does not trip the breaker, but sustained failure (provider down) trips it within 3 calls. Sixty seconds matches a typical LLM provider incident recovery window — not so short that you flood a recovering provider with probe calls.

38. **The circuit breaker singleton is shared across all graph invocations.** All concurrent customer sessions share one `llm_circuit_breaker` instance. This is intentional: if the provider is down, all customers should get the immediate "unavailable" response — not just customers whose session happened to make a call after the 3rd failure. A per-session breaker would not accumulate failures from other sessions and would not protect against provider outages.

39. **Log state transitions at WARNING level — not INFO or DEBUG.** A state transition (CLOSED → OPEN, OPEN → HALF-OPEN) is a signal that the LLM provider is having problems. It should appear in any standard log monitoring setup without requiring a filter change. Failures are logged at ERROR level — also visible by default in most setups.

---

## Defining What the AI Can and Cannot Do

40. **"What can the AI do?" is answered by the tool list.** The tools registered on the LLM define the universe of actions it can take: search meals, check ingredients, find substitutes, dispatch an order. If it is not a tool, the model cannot do it — regardless of what the customer asks. This is the hard boundary between the model's language capability and the system's permitted actions.

41. **"What should the AI do in this step?" is answered by the node's prompt.** The graph structure determines which nodes run and when. The node's prompt constrains the model's behavior within that node. `UNDERSTAND_REQUEST_PROMPT` prevents the model from presenting meal options before search results exist. `CONFIRM_AND_DISPATCH_PROMPT` prevents the model from placing an order on an ambiguous message.

42. **Constraints define permitted behavior more reliably than instructions.** "Call search_meals before presenting options" is an instruction — the model may follow it sometimes. "Do NOT present meal options until search results are returned to you" is a constraint — it tells the model what the failure looks like. Negative constraints are more robust than positive instructions for production reliability.

43. **The model never decides what state transition to make.** State field writes are done in node code, not by asking the model to output a status update. The model generates natural language. Code reads the tool results and writes to state. The model's output influences routing only when explicitly coded into a routing function that reads a specific state field.

---

## The Full Agent Flow — Overview

```
CLIENT
  │
  │  POST /agent/chat  {"message": "I want spicy tuna", "customer_name": "Eran"}
  │
  ▼
FASTAPI (agent.py route)
  │
  │  1. Validates ChatRequest (Pydantic)
  │  2. Builds AgentState: {messages: [HumanMessage("I want spicy tuna")], ...zeroed fields}
  │  3. await graph.ainvoke(state, config={"recursion_limit": 25})
  │
  ▼
LANGGRAPH GRAPH (graph.py)
  │
  │  understand_request
  │    → LLM: extract intent "spicy tuna" → calls search_meals tool
  │
  │  search_meals_node
  │    → meal_service.search_meals(db, "spicy tuna")
  │    → state.meals_found = [MealResult(id=1, name="Spicy Tuna Roll", ...)]
  │
  │  check_availability_node
  │    → check_ingredients(meal_id=1)
  │    → queries MealIngredient + Ingredient stock levels
  │    → state.availability = AvailabilityResult(available=True, missing=[])
  │
  │  _route_after_availability: availability.available=True → present_options_node
  │
  │  present_options_node
  │    → LLM: format meals as customer-readable options
  │    → state.messages appended with assistant reply
  │
  │  confirm_and_dispatch_node
  │    → LLM: detect confirmation in next customer message
  │    → if confirmed: dispatch_order tool → httpx POST /orders
  │    → state.order_id = 42
  │
  ▼
FASTAPI (route extracts final state)
  │
  │  last_message = state["messages"][-1]  # the AIMessage with the confirmation
  │  return ChatResponse(reply=last_message.content, order_id=42)
  │
  ▼
CLIENT
  │
  {"reply": "Your order is placed: Spicy Tuna Roll × 1 — $12.50. Order #42.", "order_id": 42}
```

**Key insight:** The LLM only runs three times in the full happy-path flow — understanding the request, presenting options, and confirming the order. Every step in between (searching, checking availability, routing) is deterministic code. The LLM is used exactly where natural language understanding is necessary; code handles everything else.

---

## Conversation State — Multi-Turn Session Management

44. **`messages: list[BaseMessage]` is the conversation memory — but it is the caller's responsibility to persist it.** LangGraph nodes append to `messages` within a single graph invocation. Between HTTP requests, this state is gone unless the caller stores it. For multi-turn conversations, the route handler must retrieve the session's message history, prepend it to the new `HumanMessage`, and pass the full list into `AgentState`. Without this, every turn starts cold — the agent cannot reference what it found last turn.

45. **Session identity must be explicit in the request.** `ChatRequest` needs a `session_id: str` field. Without it, you cannot retrieve the right message history for a returning customer. A UUID generated client-side and passed with every request is the minimal viable approach. Storing session history keyed by `session_id` in Redis (with a TTL matching a reasonable conversation window — 30 minutes is reasonable for a food order) is the correct backend pattern. Postgres is overkill for ephemeral session data; Redis is exactly right.

46. **Message history has a token cost that grows without bound.** A naive implementation that stores every message forever will eventually overflow the model's context window. Set a hard cap on the number of messages passed into the graph — keep the last N turns (a reasonable default is 10 message pairs = 20 messages). When you truncate, always keep the system prompt and the most recent messages; never truncate from the end. For a food ordering agent conversations are short — but the cap prevents the degenerate case where a confused customer sends 40 messages.

47. **State fields beyond `messages` do not need to be persisted between turns for this agent.** `meals_found`, `availability`, `substitutes`, `order_id` are re-derived each turn from live service calls. Persisting them would create stale-data problems (stock levels change, meals go out of service). The only thing worth persisting cross-turn is `messages` — the conversation history — and `order_id` once an order is placed, so a subsequent "cancel my order" request can reference it.

---

## Token Budget — Cost and Context Window Management

48. **Tool schemas count against the context window.** Every tool registered on the LLM has its schema (name, description, parameter descriptions) serialised and prepended to every request. Four tools with verbose descriptions can cost 500–800 tokens per call. Keep tool descriptions tight — they are specifications, not documentation. The test: if removing a sentence from a tool description would make the model call the tool incorrectly, keep it. If not, cut it.

49. **System prompts are a fixed per-call cost — pay it deliberately.** The system prompt is sent on every LLM call. Bloated system prompts (500+ tokens) compound across every node. Keep node-scoped prompts to the minimum needed for that node's task. `UNDERSTAND_REQUEST_PROMPT` does not need to explain how dispatch works — that node is not dispatching. Scope aggressively.

50. **The prompt caching boundary matters for repeated prefixes.** Anthropic's API supports prompt caching for repeated content at the start of the context. If the system prompt is always the same, it is cached and not re-billed on subsequent calls. Structure prompts so the static part (role, constraints) comes first and the dynamic part (current state, tool results) comes last — this maximises cache hit rate. A system prompt that inlines tool results in the middle of the text defeats caching.

---

## LangGraph `ToolNode` vs. Manual Tool Dispatch

51. **Two patterns for tool calling in LangGraph — choose based on whether the LLM or the graph controls sequencing.** Pattern A (ReAct / `ToolNode`): the LLM generates an `AIMessage` with `tool_calls`, and `ToolNode` intercepts the message, executes the tool, appends a `ToolMessage` to state, and loops back to the LLM. The LLM decides what to call and when. Pattern B (fixed pipeline, used in this project): each graph node calls the service function directly in Python — no `ToolNode`, no LLM-generated `tool_calls`. The graph topology determines what runs and when; the LLM is only invoked for natural language tasks.

52. **Use Pattern A (`ToolNode`) when the agent needs to reason about which tool to call.** Open-ended research agents, multi-step reasoning tasks, agents where the sequence of tool calls depends on prior results in unpredictable ways — these suit the ReAct loop. Use Pattern B (fixed pipeline) when the sequence of operations is known and the ordering matters for correctness. A food ordering flow has a fixed sequence: search → check → optionally substitute → dispatch. Deviating from that sequence produces wrong behavior (dispatching before checking availability). Fixed pipeline is correct here; `ToolNode` would allow the model to skip steps.

53. **`model.bind_tools()` serves different purposes in each pattern.** In Pattern A, `bind_tools()` tells the LLM what tools exist so it can generate `tool_calls` in its output — the LLM is the dispatcher. In Pattern B, `bind_tools()` teaches the LLM the tool signatures so it knows what arguments to extract from the customer's message — the node code is the dispatcher. If you use Pattern B but forget to bind tools, the LLM can still generate text; it just cannot generate structured tool-call outputs when needed.

---

## Observability — Debugging Agents in Production

54. **Log the full state at every node boundary — not just on error.** At the start of each node, log the incoming state fields that node consumes. At the end, log the fields it wrote. This produces a state trace across the graph invocation. When a customer reports wrong behavior, you reconstruct exactly what each node saw and produced. Without this, you are guessing. The log format should be structured (JSON) so it is queryable by session ID.

55. **Log every tool call with its inputs and outputs at DEBUG level, and every tool failure at ERROR level.** The single most common agent bug is a tool being called with wrong arguments — a meal ID from the wrong search result, a customer name with extra whitespace, a quantity corrupted in state. Logging tool inputs catches this immediately. Tool outputs are logged to verify the service returned what the agent expected. This log is cheap at low traffic and invaluable at the moment you need it.

56. **Assign a trace ID per graph invocation and thread it through every log line.** `session_id` from the request is the right key. Every log line from every node in the same invocation carries `session_id=<uuid>`. When you filter logs by session ID you see the complete execution trace for one customer's request. Without this, logs from concurrent sessions interleave and are effectively unreadable.

57. **The state at `END` is your primary debugging artifact.** After `graph.ainvoke()` returns, the final state contains everything the agent decided: what meals it found, what the availability check returned, whether substitutes were searched, what order ID was assigned, and whether an error was set. Log the final state at INFO level on every invocation. When a customer says "the agent recommended the wrong dish," the final state tells you in two seconds whether the problem was in search, availability, or response generation.

---

## Idempotency — Safe Order Dispatch

58. **`dispatch_order` must be idempotent.** The tool should include a client-generated idempotency key in the request — a UUID generated once at the start of the confirm-and-dispatch node and stored in state. If the httpx call times out and the node retries, or if the customer sends the same confirmation again, the same key is sent. Rex's `POST /orders` route uses the key to deduplicate: if an order with that key already exists, return the existing order ID rather than creating a duplicate. Without this, a retry creates a second order — a ghost order that is in the kitchen but the customer never confirmed.

59. **On dispatch timeout: set `state["error"]`, do not retry automatically.** A timeout means the order may or may not have been created. An automatic retry risks creating a duplicate (if the server received the first request). The correct behavior on timeout is to surface the ambiguity to the customer: "I tried to place your order but couldn't confirm it was received — please check your order status or try again." `state["error"]` must carry the timeout-specific message, not a generic error, so the apology node can render the right response.

60. **Check `state["order_id"]` before calling `dispatch_order`.** If `order_id` is already set in state, the order was already dispatched. Do not call `dispatch_order` again. This guards against the LLM calling the tool twice in one turn — which prompt constraints should prevent, but code must also guard. The check is one line in the node. It is not optional.
