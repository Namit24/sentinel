import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from sentinelops.config import settings
from sentinelops.routers import ingest, incidents

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events for the FastAPI app."""
    logger.info("SentinelOps starting up — environment: %s", settings.ENVIRONMENT)
    yield
    logger.info("SentinelOps shutting down")


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