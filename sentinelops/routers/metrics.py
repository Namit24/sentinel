from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.database import get_db
from sentinelops.services.metrics_service import (
    get_confidence_trend,
    get_prompt_run_stats,
    get_telemetry_drift_stats,
)

router = APIRouter()


@router.get("/metrics/prompt-health")
async def get_prompt_health_route(db: AsyncSession = Depends(get_db)) -> dict:
    """Returns 24h prompt run health aggregates for operational MLOps monitoring."""

    return await get_prompt_run_stats(db=db, window_hours=24)


@router.get("/metrics/confidence-trend")
async def get_confidence_trend_route(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Returns 24h confidence time-series points for model behavior trend visualization."""

    return await get_confidence_trend(db=db, window_hours=24)


@router.get("/metrics/drift")
async def get_drift_stats_route(db: AsyncSession = Depends(get_db)) -> dict:
    """Returns 24h telemetry drift summary against all-time baseline severity distribution."""

    return await get_telemetry_drift_stats(db=db, window_hours=24)