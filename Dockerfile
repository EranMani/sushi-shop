# Dockerfile — FastAPI application image
#
# Base: python:3.12-slim (not Alpine — asyncpg requires gcc/musl on Alpine,
# adding build toolchain for a marginal size saving is not worth the complexity).
#
# Package installer: uv (Astral). Pulled from the official distroless image via
# a multi-stage COPY — no pip overhead, no curl/wget, binary is pinned to an
# exact version tag so builds are reproducible across environments.
#
# Lockfile note: uv can resolve from a uv.lock file for fully pinned, byte-for-byte
# reproducible installs (`uv sync --frozen`). No lockfile is committed yet — run
# `uv lock` locally to generate one, then commit uv.lock alongside pyproject.toml.
# Once present, replace `uv pip install .` below with `uv sync --frozen --no-dev`.
#
# Entrypoint strategy: CMD runs alembic upgrade head before starting uvicorn.
# This guarantees the schema is current every time the container starts,
# without requiring a manual migration step. The worker service overrides CMD.

# Stage 1: pull the uv binary from the official distroless image.
# Pinning to a specific tag (not :latest) keeps builds deterministic — a tag bump
# is an explicit, reviewable change rather than a silent dependency drift.
FROM ghcr.io/astral-sh/uv:0.6.14 AS uv-binary

# Stage 2: application image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy uv from the official image — single binary, no pip, no extra OS packages.
# Placed in /usr/local/bin so it is on PATH without any shell profile changes.
COPY --from=uv-binary /uv /usr/local/bin/uv

# Install system dependencies required by asyncpg and other compiled packages.
# wget removed — it was unused. gcc + libpq-dev are still required: asyncpg
# compiles a C extension at install time and links against the postgres client lib.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency declaration first — Docker layer caching means this layer
# is only rebuilt when pyproject.toml changes, not on every source change.
# If a uv.lock file exists alongside pyproject.toml, copy it here too so the
# resolver layer also caches correctly when the lockfile is present.
COPY pyproject.toml .

# Install Python dependencies (production only — no dev/test extras in the image).
# UV_SYSTEM_PYTHON=1 tells uv to install into the system Python interpreter
# rather than creating a virtual environment, which is the correct behaviour
# inside a container where the image itself is the isolation boundary.
# UV_COMPILE_BYTECODE=1 pre-compiles .pyc files at build time so the first
# import at runtime does not pay the compilation cost.
RUN UV_SYSTEM_PYTHON=1 UV_COMPILE_BYTECODE=1 uv pip install --no-cache .

# Copy the application source
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Copy entrypoint script and make it executable
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Expose the port uvicorn will listen on
EXPOSE 8000

# ENTRYPOINT runs entrypoint.sh, which runs migrations then execs uvicorn.
# exec inside the script replaces sh with uvicorn — uvicorn becomes PID 1
# and receives SIGTERM directly on `docker stop`, enabling graceful shutdown.
# The Celery worker service overrides this entirely via `command:` in docker-compose.yml.
ENTRYPOINT ["./entrypoint.sh"]
