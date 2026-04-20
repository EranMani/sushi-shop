# src/main.py — FastAPI application entry point

from fastapi import FastAPI

from src.api.routes.ingredients import router as ingredients_router
from src.api.routes.meals import router as meals_router

app = FastAPI(
    title="Sushi Shop",
    description="Sushi restaurant simulation with AI ordering assistant",
    version="0.1.0",
)

# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(meals_router)
app.include_router(ingredients_router)


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Health check endpoint used by Docker health checks and Nginx upstream monitoring."""
    return {"status": "ok"}
