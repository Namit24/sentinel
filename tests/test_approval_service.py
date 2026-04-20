from uuid import uuid4

import pytest

from sentinelops.database import AsyncSessionLocal, engine
from sentinelops.models.incident import Incident
from sentinelops.schemas.policy import PolicyDecision
from sentinelops.schemas.root_cause import RootCauseCandidate, RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation
from sentinelops.services.approval_service import (
    AUTO_ESCALATE_THRESHOLD,
    approve_request,
    create_approval_request,
    reject_request,
)


def _build_report(confidence_score: float) -> RootCauseReport:
    """Builds deterministic root-cause report input so approval behaviors can be asserted precisely."""

    return RootCauseReport(
        incident_id=str(uuid4()),
        candidates=[
            RootCauseCandidate(
                service="db-primary",
                graph_score=1.0,
                similarity_score=0.5,
                combined_score=confidence_score,
                rank=1,
                evidence=["db timeout evidence"],
                similar_incident_ids=[],
            )
        ],
        top_cause="db-primary",
        confidence_score=confidence_score,
        graph_path=["db-primary", "api-gateway"],
        analysis_method="graph+vector",
    )


def _build_runbook(incident_id: str, confidence_score: float) -> RunbookRecommendation:
    """Builds deterministic grounded runbook payload used by approval request creation tests."""

    return RunbookRecommendation(
        incident_id=incident_id,
        top_cause="db-primary",
        steps=["Throttle traffic", "Check pool saturation", "Rollback recent query change"],
        source_chunks=["db_latency_1"],
        source_files=["db_latency.md"],
        confidence_score=confidence_score,
        grounded=True,
        raw_synthesis="Grounded remediation recommendation.",
    )


async def _create_incident_row() -> str:
    """Creates a minimal incident row required by the approval foreign-key relationship."""

    async with AsyncSessionLocal() as db:
        incident = Incident(
            status="OPEN",
            affected_services=["db-primary"],
            raw_alert_ids=[f"alert-{uuid4()}"] ,
            group_data={
                "result": [],
                "confidence_score": 0.5,
                "evidence": [],
                "fallback_used": False,
                "fallback_reason": None,
            },
            confidence_score=0.5,
            fallback_used=False,
        )
        db.add(incident)
        await db.commit()
        await db.refresh(incident)
        return str(incident.id)


@pytest.fixture(autouse=True)
async def _reset_engine_pool() -> None:
    """Disposes pooled async connections between tests so each asyncio loop starts with a fresh pool."""

    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_approval_request_auto_escalates_when_confidence_low() -> None:
    """Verifies confidence below auto-escalation threshold creates pending request with escalation metadata."""

    incident_id = await _create_incident_row()
    report = _build_report(confidence_score=AUTO_ESCALATE_THRESHOLD - 0.1)
    runbook = _build_runbook(incident_id=incident_id, confidence_score=0.6)

    async with AsyncSessionLocal() as db:
        approval = await create_approval_request(incident_id, report, runbook, db)
        assert approval.status == "PENDING"
        assert approval.auto_escalated is True
        assert approval.escalation_reason is not None


@pytest.mark.asyncio
async def test_create_approval_request_no_auto_escalation_when_confidence_high() -> None:
    """Verifies confidence at or above threshold keeps request pending without auto-escalation marker."""

    incident_id = await _create_incident_row()
    report = _build_report(confidence_score=AUTO_ESCALATE_THRESHOLD + 0.2)
    runbook = _build_runbook(incident_id=incident_id, confidence_score=0.8)

    async with AsyncSessionLocal() as db:
        approval = await create_approval_request(incident_id, report, runbook, db)
        assert approval.status == "PENDING"
        assert approval.auto_escalated is False
        assert approval.escalation_reason is None


@pytest.mark.asyncio
async def test_create_approval_request_respects_policy_escalation_even_with_high_confidence() -> None:
    """Verifies policy controls can force escalation when confidence alone would not."""

    incident_id = await _create_incident_row()
    report = _build_report(confidence_score=AUTO_ESCALATE_THRESHOLD + 0.4)
    runbook = _build_runbook(incident_id=incident_id, confidence_score=0.9)
    policy = PolicyDecision(
        policy_status="BLOCKED",
        risk_level="CRITICAL",
        reviewer_tier="incident-commander",
        human_action_required=True,
        reasons=["Runbook recommendation is not grounded in indexed source material."],
        control_flags=["UNGROUNDED_RUNBOOK"],
        confidence_score=0.9,
    )

    async with AsyncSessionLocal() as db:
        approval = await create_approval_request(
            incident_id,
            report,
            runbook,
            db,
            policy_decision=policy,
        )
        assert approval.status == "PENDING"
        assert approval.auto_escalated is True
        assert approval.escalation_reason is not None
        assert "Policy BLOCKED" in approval.escalation_reason
        assert "incident-commander" in approval.recommendation_summary


@pytest.mark.asyncio
async def test_approve_request_blocks_double_approval() -> None:
    """Verifies approving an already-approved request raises ValueError to prevent duplicate decisioning."""

    incident_id = await _create_incident_row()
    report = _build_report(confidence_score=0.9)
    runbook = _build_runbook(incident_id=incident_id, confidence_score=0.9)

    async with AsyncSessionLocal() as db:
        approval = await create_approval_request(incident_id, report, runbook, db)
        approved = await approve_request(str(approval.id), "operator-a", db)
        assert approved.status == "APPROVED"

        with pytest.raises(ValueError):
            await approve_request(str(approval.id), "operator-b", db)


@pytest.mark.asyncio
async def test_reject_request_requires_reason() -> None:
    """Verifies rejection enforces non-empty reviewer rationale for audit accountability."""

    incident_id = await _create_incident_row()
    report = _build_report(confidence_score=0.6)
    runbook = _build_runbook(incident_id=incident_id, confidence_score=0.7)

    async with AsyncSessionLocal() as db:
        approval = await create_approval_request(incident_id, report, runbook, db)
        with pytest.raises(ValueError):
            await reject_request(str(approval.id), "operator-a", "", db)
