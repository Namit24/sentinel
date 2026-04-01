import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from sqlalchemy import text

from sentinelops.config import settings
from sentinelops.database import engine
from sentinelops import models  # noqa: F401
from sentinelops.routers import ingest, incidents

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify DB is reachable. Shutdown: log goodbye."""
    logger.info("SentinelOps starting — environment: %s", settings.ENVIRONMENT)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified.")
    except Exception as e:
        logger.error("Database unreachable at startup: %s", e)
        raise
    yield
    logger.info("SentinelOps shutting down.")


app = FastAPI(
    title="SentinelOps AI",
    description="Explainable AI system for enterprise incident triage",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
app.include_router(incidents.router, prefix="/api/v1", tags=["incidents"])


@app.get("/health")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}