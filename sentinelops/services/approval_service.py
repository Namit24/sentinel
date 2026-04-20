from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.models.approval_request import ApprovalRequest
from sentinelops.models.audit_log import AuditEventType
from sentinelops.schemas.policy import PolicyDecision
from sentinelops.schemas.root_cause import RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation
from sentinelops.services.audit_service import log_event

AUTO_ESCALATE_THRESHOLD = 0.4
HUMAN_REVIEW_THRESHOLD = 0.7


def _build_recommendation_summary(
    report: RootCauseReport,
    runbook: RunbookRecommendation,
    policy_decision: PolicyDecision | None = None,
) -> str:
    """Builds a concise plain-English review payload so responders can approve quickly with context."""

    step_preview = "; ".join(runbook.steps[:3]) if runbook.steps else "No concrete steps generated"
    urgency = (
        "High-risk: low confidence requires immediate escalation review"
        if report.confidence_score < HUMAN_REVIEW_THRESHOLD
        else "Standard review"
    )
    policy_summary = ""
    if policy_decision is not None:
        policy_summary = (
            f" Policy: {policy_decision.policy_status} "
            f"(risk={policy_decision.risk_level}, reviewer={policy_decision.reviewer_tier})."
        )
    return (
        f"Top suspected cause: {report.top_cause}. "
        f"Confidence: {report.confidence_score:.2f}. "
        f"Suggested actions: {step_preview}. "
        f"Review mode: {urgency}."
        f"{policy_summary}"
    )


def _derive_escalation_reason(
    report: RootCauseReport,
    policy_decision: PolicyDecision | None,
) -> str | None:
    """Derives the strongest escalation rationale so operators see why extra review is required."""

    if policy_decision is not None and policy_decision.policy_status in {"ESCALATE_REQUIRED", "BLOCKED"}:
        reason = policy_decision.reasons[0] if policy_decision.reasons else "Policy requires elevated review."
        return (
            f"Policy {policy_decision.policy_status} for reviewer tier "
            f"{policy_decision.reviewer_tier}: {reason}"
        )

    if report.confidence_score < AUTO_ESCALATE_THRESHOLD:
        return (
            f"Confidence {report.confidence_score:.2f} is below auto-escalate threshold "
            f"{AUTO_ESCALATE_THRESHOLD:.2f}."
        )

    return None


async def create_approval_request(
    incident_id: str,
    report: RootCauseReport,
    runbook: RunbookRecommendation,
    db: AsyncSession,
    policy_decision: PolicyDecision | None = None,
    auto_commit: bool = True,
) -> ApprovalRequest:
    """Creates a pending human decision record and emits audit events for request creation and escalation."""

    confidence = policy_decision.confidence_score if policy_decision is not None else report.confidence_score
    escalation_reason = _derive_escalation_reason(report=report, policy_decision=policy_decision)
    auto_escalated = escalation_reason is not None

    approval = ApprovalRequest(
        incident_id=UUID(incident_id),
        status="PENDING",
        recommendation_summary=_build_recommendation_summary(report, runbook, policy_decision),
        top_cause=report.top_cause,
        confidence_score=confidence,
        auto_escalated=auto_escalated,
        escalation_reason=escalation_reason,
    )
    db.add(approval)
    await db.flush()

    await log_event(
        db=db,
        event_type=AuditEventType.APPROVAL_REQUESTED,
        description="Approval request created for incident remediation recommendation.",
        incident_id=incident_id,
        approval_request_id=approval.id,
        payload={
            "status": approval.status,
            "top_cause": approval.top_cause,
            "confidence_score": approval.confidence_score,
            "auto_escalated": approval.auto_escalated,
            "policy_status": policy_decision.policy_status if policy_decision is not None else None,
            "reviewer_tier": policy_decision.reviewer_tier if policy_decision is not None else None,
        },
        auto_commit=False,
    )

    if auto_escalated:
        await log_event(
            db=db,
            event_type=AuditEventType.ESCALATION_TRIGGERED,
            description="Approval request auto-escalated due to low confidence.",
            incident_id=incident_id,
            approval_request_id=approval.id,
            payload={"reason": escalation_reason},
            auto_commit=False,
        )

    if auto_commit:
        await db.commit()
        await db.refresh(approval)
    return approval


async def approve_request(approval_id: str, reviewed_by: str, db: AsyncSession) -> ApprovalRequest:
    """Marks a pending approval request as approved and logs the human decision for auditing."""

    approval = await db.get(ApprovalRequest, UUID(approval_id))
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != "PENDING":
        raise ValueError("Approval request is no longer pending")

    approval.status = "APPROVED"
    approval.reviewed_by = reviewed_by
    approval.reviewed_at = datetime.now(UTC)
    db.add(approval)
    await log_event(
        db=db,
        event_type=AuditEventType.APPROVAL_GRANTED,
        description="Approval request approved by human reviewer.",
        incident_id=approval.incident_id,
        approval_request_id=approval.id,
        actor=reviewed_by,
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(approval)
    return approval


async def reject_request(
    approval_id: str,
    reviewed_by: str,
    reason: str,
    db: AsyncSession,
) -> ApprovalRequest:
    """Marks a pending approval request as rejected and records the reason in the audit timeline."""

    if not reason or not reason.strip():
        raise ValueError("Rejection reason is required")

    approval = await db.get(ApprovalRequest, UUID(approval_id))
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != "PENDING":
        raise ValueError("Approval request is no longer pending")

    approval.status = "REJECTED"
    approval.reviewed_by = reviewed_by
    approval.reviewed_at = datetime.now(UTC)
    db.add(approval)
    await log_event(
        db=db,
        event_type=AuditEventType.APPROVAL_REJECTED,
        description="Approval request rejected by human reviewer.",
        incident_id=approval.incident_id,
        approval_request_id=approval.id,
        actor=reviewed_by,
        payload={"reason": reason.strip()},
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(approval)
    return approval


async def escalate_request(
    approval_id: str,
    reviewed_by: str,
    reason: str,
    db: AsyncSession,
) -> ApprovalRequest:
    """Escalates a pending approval request and logs escalation rationale for incident command visibility."""

    if not reason or not reason.strip():
        raise ValueError("Escalation reason is required")

    approval = await db.get(ApprovalRequest, UUID(approval_id))
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != "PENDING":
        raise ValueError("Approval request is no longer pending")

    approval.status = "ESCALATED"
    approval.auto_escalated = True
    approval.escalation_reason = reason.strip()
    approval.reviewed_by = reviewed_by
    approval.reviewed_at = datetime.now(UTC)
    db.add(approval)
    await log_event(
        db=db,
        event_type=AuditEventType.ESCALATION_TRIGGERED,
        description="Approval request escalated for additional human review.",
        incident_id=approval.incident_id,
        approval_request_id=approval.id,
        actor=reviewed_by,
        payload={"reason": reason.strip()},
        auto_commit=False,
    )
    await db.commit()
    await db.refresh(approval)
    return approval
