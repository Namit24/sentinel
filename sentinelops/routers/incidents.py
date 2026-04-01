from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.database import get_db
from sentinelops.schemas.incident import IncidentListItem, IncidentRead
from sentinelops.services.incident_service import get_incident, list_incidents

router = APIRouter()


@router.get("/incidents")
async def list_incidents_route(db: AsyncSession = Depends(get_db)) -> list[IncidentListItem]:
    """Lists all grouped incidents so responders can prioritize active investigations."""

    return await list_incidents(db=db)


@router.get("/incidents/{incident_id}")
async def get_incident_route(incident_id: UUID, db: AsyncSession = Depends(get_db)) -> IncidentRead:
    """Returns one incident including evidence so operators can inspect grouping rationale."""

    incident = await get_incident(db=db, incident_id=incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident