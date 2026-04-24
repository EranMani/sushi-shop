# src/agents/state.py
#
# AgentState — the single TypedDict that flows through every LangGraph node.
#
# Design rationale:
# - TypedDict (not Pydantic model) because LangGraph requires TypedDict for its
#   state management and merging machinery. LangGraph merges the partial dict
#   returned by each node into the current state using the TypedDict schema.
# - Every field is nullable/defaultable so the graph can initialise a fresh state
#   with only `messages` populated — nodes fill in the other fields as they run.
# - `availability` is `AvailabilityResult | None` (not just `AvailabilityResult`)
#   to explicitly represent the pre-check_availability state. Nodes that read
#   `availability.available` must guard against None.
# - `error` acts as a signal to conditional edges: any node that catches an
#   exception sets this field, and the next conditional edge routes to `apologise`.

from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import BaseMessage

from src.agents.tools import AvailabilityResult, MealResult


class AgentState(TypedDict):
    """State that flows through the LangGraph sushi assistant.

    LangGraph nodes receive this state and return a partial dict with only
    the fields they modified. LangGraph merges the partial update into the
    current state.

    All fields must be present in the initial state dict — TypedDict does not
    support truly optional keys at runtime. Use `make_initial_state()` to
    construct a properly initialised state.

    Fields:
        messages:      Full conversation history as LangChain messages.
                       The first message is typically the customer's request.
                       Nodes that call the LLM append the response here.
        meals_found:   Results from the search_meals tool call.
                       Empty list until search_meals_node runs.
        availability:  Result from check_ingredients tool call.
                       None until check_availability_node runs.
        substitutes:   Results from find_substitutes tool call.
                       Empty list until find_substitutes_node runs.
        order_id:      Set after dispatch_order succeeds.
                       None until confirm_and_dispatch_node runs successfully.
        error:         Set when any node catches an exception.
                       Conditional edges check this first — if set, route to apologise.
    """

    messages: list[BaseMessage]
    meals_found: list[MealResult]
    availability: AvailabilityResult | None
    substitutes: list[MealResult]
    order_id: int | None
    error: str | None


# ─── Default state factory ─────────────────────────────────────────────────────


def make_initial_state(messages: list[BaseMessage]) -> AgentState:
    """Create an AgentState with only the initial messages populated.

    All tool result fields default to empty/None — graph nodes fill them in
    as execution progresses.

    Args:
        messages: Initial conversation messages, typically just the customer's
                  first message as a HumanMessage.

    Returns:
        A fresh AgentState ready to be passed to graph.invoke().
    """
    return AgentState(
        messages=messages,
        meals_found=[],
        availability=None,
        substitutes=[],
        order_id=None,
        error=None,
    )
