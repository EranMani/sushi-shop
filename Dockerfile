# Dockerfile — FastAPI application image
#
# Base: python:3.12-slim (not Alpine — asyncpg requires gcc/musl on Alpine,
# adding build toolchain for a marginal size saving is not worth the complexity).
#
# Entrypoint strategy: CMD runs alembic upgrade head before starting uvicorn.
# This guarantees the schema is current every time the container starts,
# without requiring a manual migration step. The worker service overrides CMD.

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies required by asyncpg and other compiled packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency declaration first — Docker layer caching means this layer
# is only rebuilt when pyproject.toml changes, not on every source change.
COPY pyproject.toml .

# Install Python dependencies (production only — no dev/test deps in the image)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy the application source
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Expose the port uvicorn will listen on
EXPOSE 8000

# Default command: run Alembic migrations then start the API server.
# The Celery worker service overrides this CMD in docker-compose.yml.
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000"]
