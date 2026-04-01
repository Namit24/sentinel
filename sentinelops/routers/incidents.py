from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.database import get_db
from sentinelops.schemas.incident import IncidentListItem, IncidentRead
from sentinelops.schemas.root_cause import RootCauseReport
from sentinelops.services.incident_service import get_incident, get_root_cause_report, list_incidents

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


@router.get("/incidents/{incident_id}/root-cause")
async def get_root_cause_route(
    incident_id: UUID, db: AsyncSession = Depends(get_db)
) -> RootCauseReport:
    """Returns persisted root-cause analysis for one incident when available for downstream triage."""

    report = await get_root_cause_report(db=db, incident_id=incident_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Root cause analysis not yet available.")
    return report