import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.models.alert import Alert
from sentinelops.models.approval_request import ApprovalRequest
from sentinelops.models.audit_log import AuditEventType
from sentinelops.models.incident import Incident
from sentinelops.models.log_entry import LogEntry
from sentinelops.schemas.approval import ApprovalRequestRead
from sentinelops.schemas.alert import AlertCreate
from sentinelops.schemas.incident import GroupingOutput, IncidentListItem, IncidentRead, PipelineMetrics
from sentinelops.schemas.log_entry import RawLogEntryCreate
from sentinelops.schemas.policy import PolicyDecision
from sentinelops.schemas.runbook import RunbookRecommendation
from sentinelops.services.approval_service import create_approval_request
from sentinelops.services.audit_service import get_audit_trail, log_event
from sentinelops.services.grouper import group_telemetry
from sentinelops.services.policy_engine import build_policy_decision
from sentinelops.services.root_cause_ranker import rank_root_causes
from sentinelops.services.runbook_retriever import get_runbook_recommendation
from sentinelops.services.vector_store import embed_incident, incident_to_text

logger = logging.getLogger(__name__)
_MEMORY_INCIDENTS: dict[UUID, IncidentRead] = {}


async def _get_latest_approval_request(db: AsyncSession, incident_id: UUID) -> ApprovalRequest | None:
    """Fetches the newest approval request for an incident so API consumers always see current review state."""

    statement = (
        select(ApprovalRequest)
        .where(ApprovalRequest.incident_id == incident_id)
        .order_by(ApprovalRequest.created_at.desc())
    )
    rows = await db.scalars(statement)
    return rows.first()


def _to_incident_read(incident: Incident, approval_request: ApprovalRequestRead | None = None) -> IncidentRead:
    """Maps ORM incidents into API schema so handlers return a stable contract."""

    grouping = GroupingOutput.model_validate(incident.group_data)
    root_cause_data = None
    runbook_data = None
    pipeline_metrics = None
    policy_data = None
    if incident.root_cause_data is not None:
        from sentinelops.schemas.root_cause import RootCauseReport

        root_cause_data = RootCauseReport.model_validate(incident.root_cause_data)
    if incident.runbook_data is not None:
        runbook_data = RunbookRecommendation.model_validate(incident.runbook_data)
    if incident.pipeline_metrics is not None:
        pipeline_metrics = PipelineMetrics.model_validate(incident.pipeline_metrics)
    if incident.policy_data is not None:
        policy_data = PolicyDecision.model_validate(incident.policy_data)

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
        top_cause_service=incident.top_cause_service,
        root_cause_data=root_cause_data,
        runbook_data=runbook_data,
        pipeline_metrics=pipeline_metrics,
        policy_data=policy_data,
        approval_request=approval_request,
    )


async def ingest_and_group(
    db: AsyncSession, logs: list[RawLogEntryCreate], alerts: list[AlertCreate]
) -> IncidentRead:
    """Persists incoming telemetry, groups incidents, and stores the resulting grouped incident atomically."""

    pipeline_started = perf_counter()
    grouping_started = perf_counter()
    grouped = await group_telemetry(logs, db=db)
    grouping_ms = (perf_counter() - grouping_started) * 1000.0
    report = None
    runbook_recommendation = None
    policy_decision = None
    approval_read = None
    root_cause_ms = 0.0
    runbook_ms = 0.0
    approval_ms = 0.0
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
        await db.flush()
        await log_event(
            db=db,
            event_type=AuditEventType.INCIDENT_CREATED,
            description="Incident record created from incoming telemetry bundle.",
            incident_id=incident.id,
            payload={"affected_services": affected_services, "raw_alert_ids": [alert.alert_id for alert in alerts]},
            auto_commit=False,
        )

        await log_event(
            db=db,
            event_type=AuditEventType.GROUPING_COMPLETED,
            description="Telemetry grouping completed.",
            incident_id=incident.id,
            payload={
                "confidence_score": grouped.confidence_score,
                "fallback_used": grouped.fallback_used,
            },
            auto_commit=False,
        )

        if grouped.fallback_used:
            await log_event(
                db=db,
                event_type=AuditEventType.FALLBACK_USED,
                description="Fallback grouping path used due to LLM unavailability or malformed output.",
                incident_id=incident.id,
                payload={"fallback_reason": grouped.fallback_reason},
                auto_commit=False,
            )

        incident.embedding = embed_incident(incident_to_text(incident))
        root_cause_started = perf_counter()
        report = await rank_root_causes(
            incident_id=str(incident.id),
            grouping_output=grouped,
            db=db,
        )
        root_cause_ms = (perf_counter() - root_cause_started) * 1000.0
        incident.root_cause_data = report.model_dump()
        incident.top_cause_service = report.top_cause

        await log_event(
            db=db,
            event_type=AuditEventType.ROOT_CAUSE_RANKED,
            description="Root cause ranking completed.",
            incident_id=incident.id,
            payload={
                "top_cause": report.top_cause,
                "confidence_score": report.confidence_score,
            },
            auto_commit=False,
        )

        incident.embedding = embed_incident(incident_to_text(incident))
        runbook_started = perf_counter()
        runbook_recommendation = await get_runbook_recommendation(report=report, db=db)
        runbook_ms = (perf_counter() - runbook_started) * 1000.0
        incident.runbook_data = runbook_recommendation.model_dump()
        await log_event(
            db=db,
            event_type=AuditEventType.RUNBOOK_RETRIEVED,
            description="Runbook retrieval and synthesis completed.",
            incident_id=incident.id,
            payload={
                "grounded": runbook_recommendation.grounded,
                "source_files": runbook_recommendation.source_files,
            },
            auto_commit=False,
        )

        policy_decision = build_policy_decision(
            grouping_output=grouped,
            report=report,
            runbook=runbook_recommendation,
        )
        incident.policy_data = policy_decision.model_dump()

        approval_started = perf_counter()
        approval = await create_approval_request(
            incident_id=str(incident.id),
            report=report,
            runbook=runbook_recommendation,
            db=db,
            policy_decision=policy_decision,
            auto_commit=False,
        )
        approval_ms = (perf_counter() - approval_started) * 1000.0
        total_ms = (perf_counter() - pipeline_started) * 1000.0
        incident.pipeline_metrics = PipelineMetrics(
            grouping_ms=round(grouping_ms, 3),
            root_cause_ms=round(root_cause_ms, 3),
            runbook_ms=round(runbook_ms, 3),
            approval_ms=round(approval_ms, 3),
            total_ms=round(total_ms, 3),
            log_count=len(logs),
            alert_count=len(alerts),
            fallback_used=grouped.fallback_used,
            analysis_method=report.analysis_method,
            runbook_grounded=runbook_recommendation.grounded,
        ).model_dump()
        db.add(incident)
        await db.commit()
        await db.refresh(incident)
        await db.refresh(approval)
        approval_read = ApprovalRequestRead.model_validate(approval)
        return _to_incident_read(incident, approval_request=approval_read)
    except Exception:
        logger.exception("Database write failed; storing incident in memory fallback")
        await db.rollback()
        total_ms = (perf_counter() - pipeline_started) * 1000.0
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
            top_cause_service=report.top_cause if report is not None else None,
            root_cause_data=report,
            runbook_data=runbook_recommendation,
            pipeline_metrics=PipelineMetrics(
                grouping_ms=round(grouping_ms, 3),
                root_cause_ms=round(root_cause_ms, 3),
                runbook_ms=round(runbook_ms, 3),
                approval_ms=round(approval_ms, 3),
                total_ms=round(total_ms, 3),
                log_count=len(logs),
                alert_count=len(alerts),
                fallback_used=grouped.fallback_used,
                analysis_method=report.analysis_method if report is not None else "grouping_only",
                runbook_grounded=bool(runbook_recommendation.grounded) if runbook_recommendation is not None else False,
            ),
            policy_data=policy_decision,
            approval_request=approval_read,
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
                top_cause_service=item.top_cause_service,
                fallback_used=item.fallback_used,
                risk_level=(item.policy_data or {}).get("risk_level") if item.policy_data else None,
                policy_status=(item.policy_data or {}).get("policy_status") if item.policy_data else None,
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
                top_cause_service=item.top_cause_service,
                fallback_used=item.fallback_used,
                risk_level=item.policy_data.risk_level if item.policy_data else None,
                policy_status=item.policy_data.policy_status if item.policy_data else None,
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
        approval = await _get_latest_approval_request(db, incident_id)
        approval_read = ApprovalRequestRead.model_validate(approval) if approval is not None else None
        return _to_incident_read(incident, approval_request=approval_read)
    except Exception:
        logger.exception("Database detail query failed; using memory fallback")
        return _MEMORY_INCIDENTS.get(incident_id)


async def get_root_cause_report(db: AsyncSession, incident_id: UUID):
    """Returns stored root-cause report when available so API handlers stay thin and deterministic."""

    incident = await db.get(Incident, incident_id)
    if incident is None or incident.root_cause_data is None:
        return None
    from sentinelops.schemas.root_cause import RootCauseReport

    return RootCauseReport.model_validate(incident.root_cause_data)


async def get_runbook_report(db: AsyncSession, incident_id: UUID):
    """Returns stored runbook recommendation for one incident when retrieval synthesis has completed."""

    incident = await db.get(Incident, incident_id)
    if incident is None or incident.runbook_data is None:
        return None
    return RunbookRecommendation.model_validate(incident.runbook_data)


async def get_incident_audit_trail(db: AsyncSession, incident_id: UUID):
    """Returns immutable chronological audit entries for one incident's full decision lifecycle."""

    return await get_audit_trail(str(incident_id), db)
