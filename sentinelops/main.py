import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from sqlalchemy import func, select, text

from sentinelops.config import settings
from sentinelops.database import AsyncSessionLocal, engine
from sentinelops import models  # noqa: F401
from sentinelops.models.runbook_chunk import RunbookChunk
from sentinelops.routers import admin, approvals, ingest, incidents
from sentinelops.services.vector_store import index_runbooks

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

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.count()).select_from(RunbookChunk))
        count = result.scalar()
        if count == 0:
            indexed = await index_runbooks(db)
            logger.info("Auto-indexed %d runbook chunks on startup.", indexed)
        else:
            logger.info("Runbook index already populated (%d chunks).", count)

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
app.include_router(approvals.router, prefix="/api/v1", tags=["approvals"])
app.include_router(admin.router, tags=["admin"])


@app.get("/health")
async def health():
    """Simple health check endpoint."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}