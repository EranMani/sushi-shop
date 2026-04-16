#!/bin/sh
# entrypoint.sh — FastAPI container entrypoint
#
# Runs Alembic migrations then hands off to uvicorn.
# `exec` replaces this shell process with uvicorn, making uvicorn PID 1.
# This ensures SIGTERM from Docker (on container stop) reaches uvicorn directly,
# allowing it to finish in-flight requests before shutting down gracefully.
# Without exec, sh is PID 1 and may not forward SIGTERM — uvicorn gets killed hard.

set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
