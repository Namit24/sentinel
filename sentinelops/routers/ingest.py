from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.database import get_db
from sentinelops.schemas.incident import IncidentRead, IngestPayload
from sentinelops.services.incident_service import ingest_and_group

router = APIRouter()


@router.post("/ingest")
async def ingest_telemetry(payload: IngestPayload, db: AsyncSession = Depends(get_db)) -> IncidentRead:
    """Ingests telemetry bundles and delegates grouping/persistence to service-layer orchestration."""

    return await ingest_and_group(db=db, logs=payload.logs, alerts=payload.alerts)