import os
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from fastapi import FastAPI
from sqlalchemy import func, select, text

from sentinelops.config import settings
from sentinelops import models  # noqa: F401
from sentinelops.database import AsyncSessionLocal, engine
from sentinelops.models.runbook_chunk import RunbookChunk
from sentinelops.routers import admin, approvals, ingest, incidents, metrics
from sentinelops.services.llm_guard import breaker_snapshots
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
app.include_router(metrics.router, prefix="/api/v1", tags=["metrics"])
app.include_router(admin.router, tags=["admin"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])


async def _build_health_payload() -> dict:
    """Builds a readiness snapshot including DB status, runbook inventory, and LLM guard state."""

    db_status = "ok"
    db_error = None
    runbook_chunks = 0

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "error"
        db_error = str(exc)

    if db_status == "ok":
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(func.count()).select_from(RunbookChunk))
                runbook_chunks = int(result.scalar() or 0)
        except Exception as exc:
            db_status = "error"
            db_error = str(exc)

    breakers = breaker_snapshots()
    open_breakers = sum(1 for snapshot in breakers.values() if snapshot.get("open"))
    status = "error" if db_status != "ok" else "degraded" if open_breakers else "ok"

    return {
        "status": status,
        "environment": settings.ENVIRONMENT,
        "database": {"status": db_status, "error": db_error},
        "runbook_chunks": runbook_chunks,
        "llm_breakers": breakers,
        "open_breakers": open_breakers,
        "controls": {
            "grouping_timeout_seconds": settings.GROUPING_TIMEOUT_SECONDS,
            "runbook_synthesis_timeout_seconds": settings.RUNBOOK_SYNTHESIS_TIMEOUT_SECONDS,
            "circuit_breaker_failure_threshold": settings.LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            "circuit_breaker_reset_seconds": settings.LLM_CIRCUIT_BREAKER_RESET_SECONDS,
            "policy_allow_confidence_threshold": settings.POLICY_ALLOW_CONFIDENCE_THRESHOLD,
            "policy_review_confidence_threshold": settings.POLICY_REVIEW_CONFIDENCE_THRESHOLD,
            "policy_block_on_ungrounded_runbook": settings.POLICY_BLOCK_ON_UNGROUNDED_RUNBOOK,
        },
    }


@app.get("/health")
async def health():
    """Simple health check endpoint."""

    payload = await _build_health_payload()
    return {
        "status": payload["status"],
        "environment": payload["environment"],
        "database": payload["database"]["status"],
        "runbook_chunks": payload["runbook_chunks"],
        "open_breakers": payload["open_breakers"],
    }


@app.get("/health/detailed")
async def health_detailed():
    """Detailed health endpoint for dashboards and operational diagnostics."""

    return await _build_health_payload()


def _run_local_server() -> None:
    """Starts Uvicorn when the module is executed directly as a script."""

    import uvicorn

    host = os.getenv("SENTINELOPS_HOST", "0.0.0.0")
    port = int(os.getenv("SENTINELOPS_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, reload=False)


if __name__ == "__main__":
    _run_local_server()
