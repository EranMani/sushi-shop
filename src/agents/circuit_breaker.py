# src/agents/circuit_breaker.py
#
# Circuit breaker scaffold for LLM calls.
#
# COMMIT 11: Scaffold only. The LLMCircuitBreaker class is importable and
# instantiatable, but graph nodes in this commit call the LLM directly.
#
# COMMIT 14: Graph nodes replace direct LLM calls with:
#     llm_circuit_breaker.call(llm.invoke, messages)
#
# Design:
# - Uses pybreaker.CircuitBreaker as the underlying mechanism.
# - Threshold: 3 consecutive failures trip the breaker (CLOSED → OPEN).
# - Cooldown: 60 seconds in OPEN state before transitioning to HALF-OPEN.
# - In HALF-OPEN: one probe call is allowed. If it succeeds, breaker closes.
#   If it fails, breaker stays OPEN for another cooldown period.
# - When OPEN: raises CircuitBreakerError immediately — the customer gets
#   "assistant unavailable" without waiting for a timeout.
#
# Why pybreaker and not tenacity?
# tenacity provides retry logic (exponential backoff, jitter). Retrying LLM calls
# is reasonable for transient errors (rate limits, 503s). But the circuit breaker
# pattern is about stopping ALL calls when the provider is systemically down —
# not retrying until a timeout. These are complementary patterns. For Commit 14,
# tenacity-based retries could wrap the breaker call for transient errors, while
# the breaker handles sustained failures. For now, pybreaker handles the core
# "stop hammering a down provider" requirement.

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pybreaker

logger = logging.getLogger(__name__)

# ─── Breaker configuration ─────────────────────────────────────────────────────

# Number of consecutive failures that trip the breaker OPEN.
# 3 is conservative — a single rate-limit blip won't trip it,
# but sustained failures (provider down) will within 3 calls.
_FAILURE_THRESHOLD: int = 3

# Seconds to wait in OPEN state before probing with a HALF-OPEN call.
# 60 seconds matches a typical LLM provider incident recovery window.
# Lower values risk excessive probing; higher values extend customer outage.
_RECOVERY_TIMEOUT: int = 60


class _LLMCircuitBreakerListener(pybreaker.CircuitBreakerListener):
    """Logs state transitions so they are observable in application logs."""

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: pybreaker.CircuitBreakerState,
        new_state: pybreaker.CircuitBreakerState,
    ) -> None:
        logger.warning(
            "LLM circuit breaker state transition: %s → %s "
            "(failure_count=%d)",
            old_state.name,
            new_state.name,
            cb.fail_counter,
        )

    def failure(
        self,
        cb: pybreaker.CircuitBreaker,
        exc: Exception,
    ) -> None:
        logger.error(
            "LLM circuit breaker recorded failure (%d/%d): %s",
            cb.fail_counter,
            cb.fail_max,
            exc,
        )

    def success(self, cb: pybreaker.CircuitBreaker) -> None:
        logger.debug("LLM circuit breaker recorded success (state=%s)", cb.current_state)


class LLMCircuitBreaker:
    """Circuit breaker wrapper for LLM invocations.

    Wraps calls to the LLM provider (Anthropic or OpenAI) to prevent
    cascading failures when the provider is down or rate-limiting.

    Usage (Commit 14):
        result = llm_circuit_breaker.call(llm.invoke, messages)

    When the breaker is OPEN, `call()` raises `CircuitBreakerOpen` immediately
    without attempting the LLM call. The calling node should catch this and
    set state["error"] so the graph routes to `apologise`.

    Attributes:
        _breaker: The underlying pybreaker.CircuitBreaker instance.
    """

    def __init__(
        self,
        failure_threshold: int = _FAILURE_THRESHOLD,
        recovery_timeout: int = _RECOVERY_TIMEOUT,
    ) -> None:
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=failure_threshold,
            reset_timeout=recovery_timeout,
            listeners=[_LLMCircuitBreakerListener()],
            name="llm_circuit_breaker",
        )

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call `fn(*args, **kwargs)` through the circuit breaker.

        If the breaker is CLOSED or HALF-OPEN, the function is called normally.
        If the breaker is OPEN, raises `pybreaker.CircuitBreakerError` immediately.

        Args:
            fn:      The function to call (e.g., `llm.invoke`).
            *args:   Positional arguments forwarded to `fn`.
            **kwargs: Keyword arguments forwarded to `fn`.

        Returns:
            The return value of `fn(*args, **kwargs)`.

        Raises:
            pybreaker.CircuitBreakerError: If the breaker is OPEN.
            Exception: Any exception raised by `fn` (also counts as a failure).
        """
        return self._breaker.call(fn, *args, **kwargs)

    @property
    def state(self) -> str:
        """Current breaker state as a string: 'closed', 'open', or 'half-open'."""
        return self._breaker.current_state

    @property
    def fail_counter(self) -> int:
        """Number of consecutive failures recorded since last reset."""
        return self._breaker.fail_counter

    def reset(self) -> None:
        """Manually reset the breaker to CLOSED state.

        Primarily useful in tests to clear breaker state between test runs.
        In production, the breaker resets automatically after `recovery_timeout`.
        """
        self._breaker.close()
        logger.info("LLM circuit breaker manually reset to CLOSED")


# ─── Singleton instance ────────────────────────────────────────────────────────
#
# One breaker instance for the process. All graph nodes share this instance
# so the failure count is cumulative across all LLM calls in all sessions.
# This is intentional — if the provider is down, all customers should see
# the immediate "unavailable" response, not just customers whose session
# happened to make a call after the 3rd failure.

llm_circuit_breaker = LLMCircuitBreaker()


# ─── Exception re-export ──────────────────────────────────────────────────────
#
# Graph nodes import this so they don't need to know pybreaker's exception class.

CircuitBreakerOpen = pybreaker.CircuitBreakerError
