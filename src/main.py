# src/main.py — FastAPI application entry point
#
# Commit 01: Bare skeleton. Single health check route only.
# Rex takes ownership of this file from Commit 02 onward.
# Do not add application logic here until Rex's commits begin.

from fastapi import FastAPI

app = FastAPI(
    title="Sushi Shop",
    description="Sushi restaurant simulation with AI ordering assistant",
    version="0.1.0",
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint used by Docker health checks and Nginx upstream monitoring."""
    return {"status": "ok"}
