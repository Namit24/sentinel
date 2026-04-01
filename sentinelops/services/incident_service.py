import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.models.alert import Alert
from sentinelops.models.incident import Incident
from sentinelops.models.log_entry import LogEntry
from sentinelops.schemas.alert import AlertCreate
from sentinelops.schemas.incident import GroupingOutput, IncidentListItem, IncidentRead
from sentinelops.schemas.log_entry import RawLogEntryCreate
from sentinelops.services.grouper import group_telemetry

logger = logging.getLogger(__name__)
_MEMORY_INCIDENTS: dict[UUID, IncidentRead] = {}


def _to_incident_read(incident: Incident) -> IncidentRead:
    """Maps ORM incidents into API schema so handlers return a stable contract."""

    grouping = GroupingOutput.model_validate(incident.group_data)
    return IncidentRead(
        id=incident.id,
        created_at=incident.created_at,
        status=incident.status,
        affected_services=incident.affected_services,
        raw_alert_ids=incident.raw_alert_ids,
        group_data=grouping,
        confidence_score=incident.confidence_score,
        fallback_used=incident.fallback_used,
        evidence=grouping.evidence,
    )


async def ingest_and_group(
    db: AsyncSession, logs: list[RawLogEntryCreate], alerts: list[AlertCreate]
) -> IncidentRead:
    """Persists incoming telemetry, groups incidents, and stores the resulting grouped incident atomically."""

    grouped = await group_telemetry(logs)
    affected_services = sorted(
        {
            service
            for group in grouped.result
            for service in group.affected_services
            if isinstance(service, str)
        }
    )

    try:
        for log in logs:
            db.add(
                LogEntry(
                    timestamp=log.timestamp,
                    service_name=log.service_name,
                    log_level=log.log_level.upper(),
                    message=log.message,
                    trace_id=log.trace_id,
                )
            )

        for alert in alerts:
            db.add(
                Alert(
                    alert_id=alert.alert_id,
                    service_name=alert.service_name,
                    severity=alert.severity,
                    description=alert.description,
                    timestamp=alert.timestamp,
                    status=alert.status,
                )
            )

        incident = Incident(
            status="OPEN",
            affected_services=affected_services,
            raw_alert_ids=[alert.alert_id for alert in alerts],
            group_data=grouped.model_dump(),
            confidence_score=grouped.confidence_score,
            fallback_used=grouped.fallback_used,
        )
        db.add(incident)
        await db.commit()
        await db.refresh(incident)
        return _to_incident_read(incident)
    except Exception:
        logger.exception("Database write failed; storing incident in memory fallback")
        await db.rollback()
        memory_incident = IncidentRead(
            id=uuid4(),
            created_at=datetime.now(UTC),
            status="OPEN",
            affected_services=affected_services,
            raw_alert_ids=[alert.alert_id for alert in alerts],
            group_data=grouped,
            confidence_score=grouped.confidence_score,
            fallback_used=grouped.fallback_used,
            evidence=grouped.evidence,
        )
        _MEMORY_INCIDENTS[memory_incident.id] = memory_incident
        return memory_incident


async def list_incidents(db: AsyncSession) -> list[IncidentListItem]:
    """Returns all incidents in descending create order for operational triage dashboards."""

    try:
        result = await db.scalars(select(Incident).order_by(Incident.created_at.desc()))
        return [
            IncidentListItem(
                id=item.id,
                status=item.status,
                affected_services=item.affected_services,
                confidence_score=item.confidence_score,
                created_at=item.created_at,
            )
            for item in result.all()
        ]
    except Exception:
        logger.exception("Database list query failed; using memory fallback")
        return [
            IncidentListItem(
                id=item.id,
                status=item.status,
                affected_services=item.affected_services,
                confidence_score=item.confidence_score,
                created_at=item.created_at,
            )
            for item in _MEMORY_INCIDENTS.values()
        ]


async def get_incident(db: AsyncSession, incident_id: UUID) -> IncidentRead | None:
    """Fetches one incident by id to support detailed evidence review and audit use cases."""

    try:
        incident = await db.get(Incident, incident_id)
        if incident is None:
            return _MEMORY_INCIDENTS.get(incident_id)
        return _to_incident_read(incident)
    except Exception:
        logger.exception("Database detail query failed; using memory fallback")
        return _MEMORY_INCIDENTS.get(incident_id)