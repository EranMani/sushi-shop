# src/api/routes/agent.py
#
# POST /agent/chat — the sushi shop AI assistant endpoint.
#
# COMMIT 11: Route stub. Compiles and is wired into main.py.
# The route accepts the correct request shape and returns the correct response
# shape, but calls a placeholder graph invocation (no live LLM or DB calls).
#
# COMMIT 13: Full implementation — real graph.invoke() with the customer's
# message, httpx dispatch tool, and proper state extraction for the response.
#
# Request: {"message": str, "customer_name": str}
# Response: {"reply": str, "order_id": int | null}
#
# The `customer_name` field is passed through to dispatch_order so the kitchen
# worker can identify the customer when the order is ready. It is not used for
# auth — there are no user accounts in the current phase.

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ─── Request/response schemas ──────────────────────────────────────────────────
# These are agent-specific shapes — not reusing Rex's schemas.
# The agent route has a distinct API contract from the order service routes.


class ChatRequest(BaseModel):
    """Request body for POST /agent/chat.

    The customer's natural language message and their name.
    `customer_name` is required so that if the conversation results in an order,
    the order can be associated with the customer without a separate call.
    """

    message: str = Field(
        description="Customer's natural language message to the AI assistant. "
                    "Examples: 'I want something spicy', 'Do you have salmon?', "
                    "'I'll take the tuna roll'.",
        min_length=1,
        max_length=2000,
    )
    customer_name: str = Field(
        description="Customer's name. Used to associate any order placed during "
                    "this conversation with the customer.",
        min_length=1,
        max_length=200,
    )


class ChatResponse(BaseModel):
    """Response shape for POST /agent/chat.

    `reply` is the assistant's natural language response to the customer.
    `order_id` is non-null only when an order was successfully placed during
    this conversation turn — otherwise null.
    """

    reply: str = Field(
        description="The assistant's natural language response to the customer's message."
    )
    order_id: int | None = Field(
        default=None,
        description="The created order ID if an order was placed during this "
                    "conversation turn. Null otherwise.",
    )


# ─── Route handler ─────────────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Handle a customer message and return the assistant's response.

    COMMIT 11 STUB: Returns a placeholder response without invoking the
    LangGraph graph. The route compiles and can be called, but does not
    run the agent.

    COMMIT 13 IMPLEMENTATION will:
    1. Build an initial AgentState with the customer's message as a HumanMessage.
    2. Call graph.invoke(state, config={"recursion_limit": 25}).
    3. Extract the last AIMessage from the final state's messages list.
    4. Return the message content as `reply` and state.order_id as `order_id`.

    Error handling (Commit 13):
    - If graph.invoke() raises: return a user-friendly error message (not a traceback).
    - If the last message has no content: return a generic fallback.
    - 500 is a last resort — the graph's apologise_node should catch everything first.
    """
    logger.info(
        "POST /agent/chat — customer=%r message_length=%d",
        request.customer_name,
        len(request.message),
    )

    # STUB response — Commit 13 replaces this with real graph.invoke()
    return ChatResponse(
        reply=(
            "Hello! I'm Hana, your sushi assistant. "
            "I'm not fully set up yet, but I'll be ready to help you soon!"
        ),
        order_id=None,
    )
