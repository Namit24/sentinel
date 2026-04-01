from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.database import get_db
from sentinelops.schemas.approval import AuditEventRead
from sentinelops.schemas.incident import IncidentListItem, IncidentRead
from sentinelops.schemas.root_cause import RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation
from sentinelops.services.incident_service import (
    get_incident,
    get_incident_audit_trail,
    get_root_cause_report,
    get_runbook_report,
    list_incidents,
)

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


@router.get("/incidents/{incident_id}/runbook")
async def get_runbook_route(
    incident_id: UUID, db: AsyncSession = Depends(get_db)
) -> RunbookRecommendation:
    """Returns persisted runbook recommendation for one incident if indexing and synthesis are available."""

    report = await get_runbook_report(db=db, incident_id=incident_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Runbook recommendation not available. Ensure /admin/index-runbooks has been called.",
        )
    return report


@router.get("/incidents/{incident_id}/audit-trail")
async def get_audit_trail_route(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[AuditEventRead]:
    """Returns immutable chronological decision events so responders can inspect full incident history."""

    events = await get_incident_audit_trail(db=db, incident_id=incident_id)
    return [AuditEventRead.model_validate(event) for event in events]