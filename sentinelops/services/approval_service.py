from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.models.approval_request import ApprovalRequest
from sentinelops.models.audit_log import AuditEventType
from sentinelops.schemas.root_cause import RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation
from sentinelops.services.audit_service import log_event

AUTO_ESCALATE_THRESHOLD = 0.4
HUMAN_REVIEW_THRESHOLD = 0.7


def _build_recommendation_summary(report: RootCauseReport, runbook: RunbookRecommendation) -> str:
    """Builds a concise plain-English review payload so responders can approve quickly with context."""

    step_preview = "; ".join(runbook.steps[:3]) if runbook.steps else "No concrete steps generated"
    urgency = (
        "High-risk: low confidence requires immediate escalation review"
        if report.confidence_score < HUMAN_REVIEW_THRESHOLD
        else "Standard review"
    )
    return (
        f"Top suspected cause: {report.top_cause}. "
        f"Confidence: {report.confidence_score:.2f}. "
        f"Suggested actions: {step_preview}. "
        f"Review mode: {urgency}."
    )


async def create_approval_request(
    incident_id: str,
    report: RootCauseReport,
    runbook: RunbookRecommendation,
    db: AsyncSession,
) -> ApprovalRequest:
    """Creates a pending human decision record and emits audit events for request creation and escalation."""

    confidence = report.confidence_score
    auto_escalated = confidence < AUTO_ESCALATE_THRESHOLD
    escalation_reason = (
        f"Confidence {confidence:.2f} is below auto-escalate threshold {AUTO_ESCALATE_THRESHOLD:.2f}."
        if auto_escalated
        else None
    )

    approval = ApprovalRequest(
        incident_id=UUID(incident_id),
        status="PENDING",
        recommendation_summary=_build_recommendation_summary(report, runbook),
        top_cause=report.top_cause,
        confidence_score=confidence,
        auto_escalated=auto_escalated,
        escalation_reason=escalation_reason,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

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
        },
    )

    if auto_escalated:
        await log_event(
            db=db,
            event_type=AuditEventType.ESCALATION_TRIGGERED,
            description="Approval request auto-escalated due to low confidence.",
            incident_id=incident_id,
            approval_request_id=approval.id,
            payload={"reason": escalation_reason},
        )

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
    await db.commit()
    await db.refresh(approval)

    await log_event(
        db=db,
        event_type=AuditEventType.APPROVAL_GRANTED,
        description="Approval request approved by human reviewer.",
        incident_id=approval.incident_id,
        approval_request_id=approval.id,
        actor=reviewed_by,
    )
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
    await db.commit()
    await db.refresh(approval)

    await log_event(
        db=db,
        event_type=AuditEventType.APPROVAL_REJECTED,
        description="Approval request rejected by human reviewer.",
        incident_id=approval.incident_id,
        approval_request_id=approval.id,
        actor=reviewed_by,
        payload={"reason": reason.strip()},
    )
    return approval


async def escalate_request(approval_id: str, reason: str, db: AsyncSession) -> ApprovalRequest:
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
    approval.reviewed_at = datetime.now(UTC)
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

    await log_event(
        db=db,
        event_type=AuditEventType.ESCALATION_TRIGGERED,
        description="Approval request escalated for additional human review.",
        incident_id=approval.incident_id,
        approval_request_id=approval.id,
        payload={"reason": reason.strip()},
    )
    return approval
