# src/agents/graph.py
#
# LangGraph state machine for the sushi shop AI assistant.
#
# Graph structure:
#   START
#     └→ understand_request (LLM: parse intent, call search_meals)
#           └→ search_meals_node (tool: search_meals)
#                 └→ check_availability_node (tool: check_ingredients)
#                       ├→ [available]   → present_options_node (LLM: format options)
#                       └→ [unavailable] → find_substitutes_node (tool: find_substitutes)
#                                               ├→ [found]   → present_options_node
#                                               └→ [none]    → apologise_node
#                 └→ [no meals found] → apologise_node
#   present_options_node → confirm_and_dispatch_node (LLM: confirm + dispatch)
#   apologise_node → END
#   confirm_and_dispatch_node → END
#
# Routing principles:
# - ALL routing decisions are deterministic (read state fields, no LLM calls).
# - LLM calls are reserved for: understanding requests, formatting responses,
#   detecting confirmation, generating apologies.
# - Any node that sets state["error"] routes to apologise_node via the conditional
#   edge's error check.
# - The graph is invoked via graph.ainvoke() (async) — all node functions are async
#   so they can call async tool stubs (Commit 11) and real async service functions
#   (Commit 12) without needing asyncio.run() wrappers.
# - recursion_limit=25 passed in config at invoke time.
#
# COMMIT 11: Graph compiles with tool stubs. All nodes are wired.
# COMMIT 12: Tool implementations replace stubs (no graph changes needed).
# COMMIT 13: dispatch_order stub replaced with httpx implementation.
# COMMIT 14: LLM calls wrapped with llm_circuit_breaker.call() in each node.

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.agents.prompts.assistant import (
    APOLOGISE_PROMPT,
    CONFIRM_AND_DISPATCH_PROMPT,
    PRESENT_OPTIONS_PROMPT,
    UNDERSTAND_REQUEST_PROMPT,
)
from src.agents.state import AgentState
from src.agents.tools import (
    AvailabilityResult,
    MealResult,
    check_ingredients,
    dispatch_order,
    find_substitutes,
    search_meals,
)
from src.core.settings import get_settings

logger = logging.getLogger(__name__)

# ─── LLM initialisation ────────────────────────────────────────────────────────


def _build_llm() -> object:
    """Construct the LangChain LLM based on the configured provider.

    Called once at module load time. The LLM instance is shared across all
    graph invocations in this process — no re-initialisation per request.

    Returns:
        A ChatAnthropic or ChatOpenAI instance, with all four tools bound.
    """
    settings = get_settings()

    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic  # type: ignore[import-untyped]

        llm = ChatAnthropic(
            model="claude-3-5-sonnet-20241022",
            api_key=settings.anthropic_api_key,
            temperature=0,  # deterministic responses for tool calls
        )
    else:  # openai
        from langchain_openai import ChatOpenAI  # type: ignore[import-untyped]

        llm = ChatOpenAI(
            model="gpt-4o",
            api_key=settings.openai_api_key,
            temperature=0,
        )

    # Bind all four tools so the LLM can call any of them.
    # Even nodes that only need one tool get the full set — this avoids
    # creating multiple LLM instances and simplifies Commit 14's circuit breaker wiring.
    return llm.bind_tools([search_meals, check_ingredients, find_substitutes, dispatch_order])


# Module-level LLM instance. Constructed once at import time.
# If settings are missing, this fails at startup — not at first customer request.
_llm = _build_llm()


# ─── Node implementations ──────────────────────────────────────────────────────
#
# All node functions are ASYNC. This allows them to:
# 1. Await async tool stubs directly (Commit 11)
# 2. Await real async service calls via async_session_factory (Commit 12)
# 3. Be invoked by graph.ainvoke() without thread pool overhead
#
# The LLM calls use llm.invoke() (sync) for now because the LangChain models
# support both sync and async. Commit 14 wraps these with the circuit breaker.
# If needed in Commit 14, switch to llm.ainvoke() for fully async LLM calls.


async def understand_request(state: AgentState) -> dict[str, object]:
    """Parse the customer's natural language request and initiate tool calls.

    This node uses the LLM to understand intent and extract a search query.
    The LLM response (which may contain a tool call for search_meals) is
    appended to messages. search_meals_node then extracts and executes it.

    State reads: messages (customer's request)
    State writes: messages (appended with LLM response)
    Error path: sets state["error"] -> routes to apologise
    """
    try:
        # Prepend the understand-request-specific system prompt so the LLM
        # focuses on intent extraction, not on the full ordering flow.
        messages = [
            SystemMessage(content=UNDERSTAND_REQUEST_PROMPT),
            *state["messages"],
        ]
        response = _llm.invoke(messages)
        return {"messages": [*state["messages"], response]}
    except Exception as exc:
        logger.error("understand_request: LLM call failed: %s", exc, exc_info=True)
        return {"error": f"LLM call failed in understand_request: {exc}"}


async def search_meals_node(state: AgentState) -> dict[str, object]:
    """Call the search_meals tool to find meals matching the customer's intent.

    Extracts the search query from the last LLM message's tool calls (if present)
    or falls back to the raw customer message text.

    State reads: messages (last message may contain tool call from understand_request)
    State writes: meals_found
    Error path: sets state["error"] -> routes to apologise
    """
    try:
        last_message = state["messages"][-1] if state["messages"] else None
        query = _extract_search_query(last_message, state["messages"])

        # Await the async tool directly — no asyncio.run() wrapper needed
        # because this node is async and called via graph.ainvoke().
        results = await search_meals.ainvoke({"query": query})

        meals: list[MealResult] = results if isinstance(results, list) else []
        return {"meals_found": meals}
    except Exception as exc:
        logger.error("search_meals_node: tool call failed: %s", exc, exc_info=True)
        return {"error": f"Tool call failed in search_meals_node: {exc}"}


async def check_availability_node(state: AgentState) -> dict[str, object]:
    """Call check_ingredients on the first meal found to verify it is in stock.

    Uses the first meal in meals_found as the candidate. In a multi-meal scenario
    (future enhancement), this could check availability per meal.

    State reads: meals_found[0].id
    State writes: availability
    Error path: sets state["error"] -> routes to apologise
    """
    try:
        if not state["meals_found"]:
            # Defensive guard — conditional edge after search_meals_node
            # should have routed empty results to apologise already.
            return {"error": "No meals available to check availability for."}

        meal_id = state["meals_found"][0].id
        result = await check_ingredients.ainvoke({"meal_id": meal_id})
        availability: AvailabilityResult = result
        return {"availability": availability}
    except Exception as exc:
        logger.error("check_availability_node: tool call failed: %s", exc, exc_info=True)
        return {"error": f"Tool call failed in check_availability_node: {exc}"}


async def find_substitutes_node(state: AgentState) -> dict[str, object]:
    """Call find_substitutes for the unavailable meal.

    State reads: meals_found[0].id
    State writes: substitutes
    Error path: sets state["error"] -> routes to apologise
    """
    try:
        if not state["meals_found"]:
            return {"error": "No meal ID available for substitute search."}

        meal_id = state["meals_found"][0].id
        results = await find_substitutes.ainvoke({"meal_id": meal_id})
        subs: list[MealResult] = results if isinstance(results, list) else []
        return {"substitutes": subs}
    except Exception as exc:
        logger.error("find_substitutes_node: tool call failed: %s", exc, exc_info=True)
        return {"error": f"Tool call failed in find_substitutes_node: {exc}"}


async def present_options_node(state: AgentState) -> dict[str, object]:
    """Format the available meal options into a customer-readable LLM response.

    Uses substitutes if we arrived via the unavailability branch (substitutes
    are populated), otherwise uses meals_found (direct availability branch).

    State reads: meals_found, substitutes, messages
    State writes: messages (appended with LLM response)
    Error path: sets state["error"] -> routes to apologise
    """
    try:
        # Determine which meals to present.
        # Substitutes branch: substitutes are populated because the first choice
        # was unavailable and we found alternatives.
        # Direct branch: substitutes is empty, meals_found is the right list.
        meals_to_present = state["substitutes"] if state["substitutes"] else state["meals_found"]

        # Build a context string the LLM can use to format the response.
        # This is deterministic structured data — no LLM interpretation needed here.
        meal_context = "\n".join(
            f"- id={m.id} name={m.name!r} price=${m.price} "
            f"description={m.description!r} tags={m.tags}"
            for m in meals_to_present
        )

        availability = state.get("availability")
        unavailable_note = ""
        if availability and not availability.available:
            unavailable_note = (
                "\nNote: The customer's first choice was unavailable. "
                "These are substitute options."
            )

        messages = [
            SystemMessage(
                content=PRESENT_OPTIONS_PROMPT
                + unavailable_note
                + f"\n\nAvailable meals to present:\n{meal_context}"
            ),
            *state["messages"],
        ]
        response = _llm.invoke(messages)
        return {"messages": [*state["messages"], response]}
    except Exception as exc:
        logger.error("present_options_node: LLM call failed: %s", exc, exc_info=True)
        return {"error": f"LLM call failed in present_options_node: {exc}"}


async def confirm_and_dispatch_node(state: AgentState) -> dict[str, object]:
    """Detect customer confirmation and dispatch the order if confirmed.

    The LLM inspects the latest customer message to determine if it is a
    confirmation. If confirmed, it calls dispatch_order and the result is
    stored in state.order_id.

    State reads: messages, meals_found, substitutes
    State writes: order_id, messages (appended with confirmation or clarification)
    Error path: sets state["error"] (terminal node — falls through to END on success)
    """
    try:
        messages = [
            SystemMessage(content=CONFIRM_AND_DISPATCH_PROMPT),
            *state["messages"],
        ]
        response = _llm.invoke(messages)
        updated_messages = [*state["messages"], response]

        # Extract order_id from dispatch_order tool call result, if present.
        # In Commit 13, the LLM's tool call to dispatch_order will be executed
        # and the result (with order_id) will appear in the message response.
        # For Commit 11, this is a stub — no actual dispatch happens.
        order_id: int | None = None
        if hasattr(response, "additional_kwargs"):
            tool_calls = response.additional_kwargs.get("tool_calls", [])
            if tool_calls:
                # Stub: Commit 13 will process the tool call result here
                # and extract order_id from the dispatch_order response.
                pass

        return {"messages": updated_messages, "order_id": order_id}
    except Exception as exc:
        logger.error(
            "confirm_and_dispatch_node: LLM or tool call failed: %s",
            exc,
            exc_info=True,
        )
        return {"error": f"LLM call failed in confirm_and_dispatch_node: {exc}"}


async def apologise_node(state: AgentState) -> dict[str, object]:
    """Generate an apology or 'nothing available' message for the customer.

    This node is the terminal fallback for all failure paths:
    - Empty search results (no meals found)
    - No substitutes found
    - Any tool or LLM exception in upstream nodes

    CRITICAL: if the LLM call inside THIS node also fails, the node must
    not re-raise. It returns a hardcoded fallback message instead.
    A Python traceback reaching the customer is worse than a generic message.

    State reads: error (optional), messages
    State writes: messages (appended with apology)
    """
    try:
        error_context = ""
        if state.get("error"):
            # Include error in system prompt context so the LLM can acknowledge
            # technical issues appropriately. The LLM is instructed NOT to show
            # raw error text to the customer.
            error_context = f"\n\nInternal context (do not show to customer): {state['error']}"

        messages = [
            SystemMessage(content=APOLOGISE_PROMPT + error_context),
            *state["messages"],
        ]
        response = _llm.invoke(messages)
        return {"messages": [*state["messages"], response]}
    except Exception as exc:
        # Last resort: LLM is down or broken even for the apology call.
        # Return a hardcoded message — do NOT re-raise.
        # The customer must always get a response.
        logger.error(
            "apologise_node: LLM call also failed — returning hardcoded fallback: %s",
            exc,
            exc_info=True,
        )
        fallback = AIMessage(
            content="I'm sorry, I'm having trouble right now. "
                    "Please try again in a moment or speak with our staff."
        )
        return {"messages": [*state["messages"], fallback]}


# ─── Routing helpers ───────────────────────────────────────────────────────────
#
# Conditional edge functions. They read state and return a node name string.
# NO LLM calls here. Routing is purely deterministic code.
#
# Convention: all routing functions check state["error"] first. If any upstream
# node set an error, every routing function routes to apologise_node. This means
# a single error anywhere in the graph always terminates at the apology, regardless
# of which routing function happens to be evaluated next.


def _route_after_understand(state: AgentState) -> str:
    """Route after understand_request.

    - Error -> apologise_node
    - Otherwise -> search_meals_node
    """
    if state.get("error"):
        return "apologise_node"
    return "search_meals_node"


def _route_after_search(state: AgentState) -> str:
    """Route after search_meals_node.

    - Error -> apologise_node
    - No meals found -> apologise_node
    - Meals found -> check_availability_node
    """
    if state.get("error"):
        return "apologise_node"
    if not state.get("meals_found"):
        return "apologise_node"
    return "check_availability_node"


def _route_after_availability(state: AgentState) -> str:
    """Route after check_availability_node.

    - Error -> apologise_node
    - availability is None -> apologise_node (defensive guard)
    - available=True -> present_options_node
    - available=False -> find_substitutes_node
    """
    if state.get("error"):
        return "apologise_node"
    availability: AvailabilityResult | None = state.get("availability")
    if availability is None:
        # Defensive guard — should not happen if the node ran successfully.
        return "apologise_node"
    if availability.available:
        return "present_options_node"
    return "find_substitutes_node"


def _route_after_substitutes(state: AgentState) -> str:
    """Route after find_substitutes_node.

    - Error -> apologise_node
    - Substitutes found -> present_options_node
    - No substitutes -> apologise_node
    """
    if state.get("error"):
        return "apologise_node"
    if state.get("substitutes"):
        return "present_options_node"
    return "apologise_node"


# ─── Graph construction ────────────────────────────────────────────────────────


def _build_graph() -> StateGraph:
    """Construct the LangGraph state machine.

    Returns a StateGraph builder (not yet compiled).
    Called once at module load time via the module-level compile call below.
    """
    builder = StateGraph(AgentState)

    # ── Add nodes ──────────────────────────────────────────────────────────────
    builder.add_node("understand_request", understand_request)
    builder.add_node("search_meals_node", search_meals_node)
    builder.add_node("check_availability_node", check_availability_node)
    builder.add_node("find_substitutes_node", find_substitutes_node)
    builder.add_node("present_options_node", present_options_node)
    builder.add_node("confirm_and_dispatch_node", confirm_and_dispatch_node)
    builder.add_node("apologise_node", apologise_node)

    # ── Entry point ────────────────────────────────────────────────────────────
    builder.add_edge(START, "understand_request")

    # ── Conditional edges (deterministic routing, no LLM) ─────────────────────

    builder.add_conditional_edges(
        "understand_request",
        _route_after_understand,
        {
            "search_meals_node": "search_meals_node",
            "apologise_node": "apologise_node",
        },
    )

    builder.add_conditional_edges(
        "search_meals_node",
        _route_after_search,
        {
            "check_availability_node": "check_availability_node",
            "apologise_node": "apologise_node",
        },
    )

    builder.add_conditional_edges(
        "check_availability_node",
        _route_after_availability,
        {
            "present_options_node": "present_options_node",
            "find_substitutes_node": "find_substitutes_node",
            "apologise_node": "apologise_node",
        },
    )

    builder.add_conditional_edges(
        "find_substitutes_node",
        _route_after_substitutes,
        {
            "present_options_node": "present_options_node",
            "apologise_node": "apologise_node",
        },
    )

    # ── Fixed edges ────────────────────────────────────────────────────────────

    # present_options always leads to confirm_and_dispatch.
    # The customer must explicitly confirm before the order is placed.
    builder.add_edge("present_options_node", "confirm_and_dispatch_node")

    # Terminal nodes.
    builder.add_edge("confirm_and_dispatch_node", END)
    builder.add_edge("apologise_node", END)

    return builder


# ─── Compiled graph (module-level singleton) ────────────────────────────────────
#
# Compiled once at module load time. graph.ainvoke() is safe to call concurrently.
#
# recursion_limit is passed at invocation time via:
#   config = {"recursion_limit": 25}
#   await graph.ainvoke(state, config=config)
#
# This is the LangGraph >= 0.1 pattern — compile() does not accept recursion_limit
# as a compile-time argument; it is a runtime invocation config.

graph = _build_graph().compile()


# ─── Helper functions ──────────────────────────────────────────────────────────


def _extract_search_query(
    last_message: object,
    all_messages: list[object],
) -> str:
    """Extract the search query from LLM tool calls or fall back to raw text.

    When the LLM produces a tool call for search_meals in understand_request,
    the query is embedded in the tool call arguments. When no tool call is
    present, we fall back to using the last human message text directly.

    Args:
        last_message: The last message in the conversation (usually an LLM response).
        all_messages: Full message history.

    Returns:
        A search query string suitable for passing to search_meals.
    """
    import json

    from langchain_core.messages import HumanMessage

    # Check if the last LLM message contains a search_meals tool call
    if hasattr(last_message, "additional_kwargs"):
        tool_calls = getattr(last_message, "additional_kwargs", {}).get("tool_calls", [])
        for tc in tool_calls:
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                if fn.get("name") == "search_meals":
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                        query = args.get("query", "")
                        if query:
                            return query
                    except (json.JSONDecodeError, AttributeError):
                        pass

    # Also check tool_calls attribute directly (LangChain v0.2+ format)
    if hasattr(last_message, "tool_calls"):
        for tc in (getattr(last_message, "tool_calls", None) or []):
            if isinstance(tc, dict) and tc.get("name") == "search_meals":
                args = tc.get("args", {})
                query = args.get("query", "")
                if query:
                    return query

    # Fallback: use the last human message content as the query
    for msg in reversed(all_messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Multi-modal message — extract text parts only
                return " ".join(
                    part["text"]
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )

    return ""
