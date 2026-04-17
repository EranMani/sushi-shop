# src/core/settings.py
#
# Pydantic BaseSettings — single source of truth for all application configuration.
#
# All env vars are read once at startup (via `get_settings()`) and cached for
# the lifetime of the process. If a required variable is missing, startup fails
# immediately with a clear error message — not a confusing AttributeError at first use.
#
# Usage:
#   from src.core.settings import get_settings
#   settings = get_settings()
#   url = settings.database_url

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables / .env file.

    All fields are required unless a default is provided. Missing required
    variables raise a `ValueError` at startup with a message that identifies
    exactly which variable is absent.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Extra env vars in the file are silently ignored — avoids errors when
        # the .env file contains variables for other services (e.g., Docker vars).
        extra="ignore",
        # Case-insensitive matching: DATABASE_URL and database_url both work.
        case_sensitive=False,
    )

    # ─── Database ─────────────────────────────────────────────────────────────

    database_url: str
    """Async PostgreSQL connection URL.
    Must use the asyncpg driver: postgresql+asyncpg://user:pass@host:port/db.
    """

    test_database_url: str | None = None
    """Optional async URL for the test database.
    When set, the test suite uses this instead of `database_url`.
    """

    # ─── Redis ────────────────────────────────────────────────────────────────

    redis_url: str
    """Redis connection URL used as both the Celery broker and the cache.
    Format: redis://host:port/db_index (e.g., redis://redis:6379/0).
    """

    # ─── LLM Provider ─────────────────────────────────────────────────────────

    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    """Which LLM provider the AI assistant uses.
    Accepted values: 'anthropic' or 'openai'. Controls which LangChain
    integration is loaded in the agent at startup.
    """

    anthropic_api_key: str | None = None
    """Anthropic API key. Required when llm_provider='anthropic'."""

    openai_api_key: str | None = None
    """OpenAI API key. Required when llm_provider='openai'."""

    # ─── Application ──────────────────────────────────────────────────────────

    app_env: Literal["development", "staging", "production"] = "development"
    """Application environment.
    Controls SQL echo logging (development only) and debug behaviour.
    """

    cache_ttl_seconds: int = 300
    """How long (in seconds) menu data is cached in Redis.
    Lower values mean fresher data but more database load.
    """

    # ─── Validators ───────────────────────────────────────────────────────────

    @field_validator("database_url")
    @classmethod
    def database_url_must_use_asyncpg(cls, v: str) -> str:
        """Enforce the asyncpg driver prefix.

        SQLAlchemy's async engine requires the asyncpg dialect prefix.
        A plain `postgresql://` URL will fail at engine creation time with
        a cryptic driver error — catch it here with a clear message instead.
        """
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                f"DATABASE_URL must use the asyncpg driver "
                f"(postgresql+asyncpg://...), got: '{v}'. "
                f"Change the scheme to 'postgresql+asyncpg' and ensure asyncpg is installed."
            )
        return v

    @field_validator("cache_ttl_seconds")
    @classmethod
    def cache_ttl_must_be_positive(cls, v: int) -> int:
        """Cache TTL of zero or below disables caching silently — reject it."""
        if v <= 0:
            raise ValueError(
                f"CACHE_TTL_SECONDS must be a positive integer, got {v}. "
                f"Minimum recommended value is 30 seconds."
            )
        return v

    @model_validator(mode="after")
    def llm_api_key_required_for_provider(self) -> "Settings":
        """Ensure the API key for the configured LLM provider is present.

        Raises at startup rather than at first agent call — avoids a silent
        failure that only surfaces when a customer sends their first message.
        """
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError(
                "LLM_PROVIDER is set to 'anthropic' but ANTHROPIC_API_KEY is missing. "
                "Set ANTHROPIC_API_KEY in your .env file or environment."
            )
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError(
                "LLM_PROVIDER is set to 'openai' but OPENAI_API_KEY is missing. "
                "Set OPENAI_API_KEY in your .env file or environment."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the application Settings instance, constructing it on first call.

    Cached with `lru_cache(maxsize=1)` — Settings is only instantiated once
    per process lifetime. This means env vars are read once at startup.

    In tests, call `get_settings.cache_clear()` before patching env vars to
    force re-instantiation with the test environment.
    """
    return Settings()
