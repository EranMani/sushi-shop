# src/core/cache.py
#
# Redis client and cache helpers.
#
# Design rules enforced here:
#   - Every key has an explicit TTL — no TTL means a memory leak.
#   - Invalidation happens on write, not on a background timer.
#   - Postgres is always the source of truth; Redis is a read-through cache.
#   - Key naming convention: "menu:all", "order:status:{id}" — colon-separated namespace.
#
# Usage:
#   from src.core.cache import get_redis, get_cached_menu, set_cached_menu, invalidate_menu_cache

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from src.core.settings import get_settings

logger = logging.getLogger(__name__)

# Module-level Redis client — created once at import time, shared across requests.
# The pool is managed internally by redis.asyncio.
_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return the shared async Redis client, creating it on first call.

    The client is a module-level singleton. Redis connection pooling is handled
    internally — this does not create a new connection per call.
    """
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


# ─── Key constants ────────────────────────────────────────────────────────────

MENU_ALL_KEY = "menu:all"


def order_status_key(order_id: int) -> str:
    """Return the Redis key for a specific order's status cache entry."""
    return f"order:status:{order_id}"


# ─── Menu cache helpers ───────────────────────────────────────────────────────

async def get_cached_menu() -> str | None:
    """Return the cached menu JSON string, or None if the cache is cold.

    The caller is responsible for deserialising. Returning raw JSON avoids
    unnecessary serialise/deserialise cycles when the route layer only needs
    to pass the string to a response body.
    """
    client = get_redis()
    try:
        value: str | None = await client.get(MENU_ALL_KEY)
        return value
    except Exception as exc:
        # A Redis failure must never break menu reads — fall through to Postgres.
        logger.warning("Redis GET failed for key '%s': %s", MENU_ALL_KEY, exc)
        return None


async def set_cached_menu(data: list[dict[str, object]]) -> None:
    """Serialise and store the menu in Redis with the configured TTL.

    Args:
        data: List of meal dicts (already serialised from ORM objects via
              MealRead.model_dump()) to store as JSON.
    """
    settings = get_settings()
    client = get_redis()
    try:
        await client.setex(
            MENU_ALL_KEY,
            settings.cache_ttl_seconds,
            json.dumps(data),
        )
    except Exception as exc:
        # Cache write failure is non-fatal — the route will just return fresh
        # data from Postgres and the next call will try again.
        logger.warning("Redis SETEX failed for key '%s': %s", MENU_ALL_KEY, exc)


async def invalidate_menu_cache() -> None:
    """Delete the `menu:all` cache key.

    Called by every write operation on Meal or Ingredient so the next
    GET /meals request rebuilds from Postgres rather than stale data.
    Redis failure here is logged but not re-raised — the write to Postgres
    already succeeded; a stale cache is correctable, a failed write is not.
    """
    client = get_redis()
    try:
        await client.delete(MENU_ALL_KEY)
        logger.debug("Invalidated cache key '%s'", MENU_ALL_KEY)
    except Exception as exc:
        logger.warning("Redis DELETE failed for key '%s': %s", MENU_ALL_KEY, exc)


# ─── Order status cache helpers ───────────────────────────────────────────────

async def get_cached_order_status(order_id: int) -> str | None:
    """Return the cached status string for an order, or None if not cached.

    Args:
        order_id: Primary key of the order to look up.
    """
    client = get_redis()
    key = order_status_key(order_id)
    try:
        value: str | None = await client.get(key)
        return value
    except Exception as exc:
        logger.warning("Redis GET failed for key '%s': %s", key, exc)
        return None


async def set_cached_order_status(order_id: int, status: str) -> None:
    """Cache the status string for an order with the configured TTL.

    Args:
        order_id: Primary key of the order.
        status:   The status string (e.g. "PENDING", "PREPARING", "READY", "FAILED").
    """
    settings = get_settings()
    client = get_redis()
    key = order_status_key(order_id)
    try:
        await client.setex(key, settings.cache_ttl_seconds, status)
    except Exception as exc:
        logger.warning("Redis SETEX failed for key '%s': %s", key, exc)


async def invalidate_order_status_cache(order_id: int) -> None:
    """Delete the cached status entry for a specific order.

    Called by the Celery kitchen worker whenever it updates an order's status
    in Postgres, so the next status-poll sees the fresh value.
    """
    client = get_redis()
    key = order_status_key(order_id)
    try:
        await client.delete(key)
        logger.debug("Invalidated cache key '%s'", key)
    except Exception as exc:
        logger.warning("Redis DELETE failed for key '%s': %s", key, exc)
