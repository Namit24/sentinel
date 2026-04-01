from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.database import get_db
from sentinelops.models.approval_request import ApprovalRequest
from sentinelops.schemas.approval import ApprovalAction, ApprovalRequestRead
from sentinelops.services.approval_service import approve_request, escalate_request, reject_request

router = APIRouter()


@router.get("/approvals/pending")
async def list_pending_approvals(db: AsyncSession = Depends(get_db)) -> list[ApprovalRequestRead]:
    """Returns pending human-review requests in FIFO order so operators can process approvals consistently."""

    statement = (
        select(ApprovalRequest)
        .where(ApprovalRequest.status == "PENDING")
        .order_by(ApprovalRequest.created_at.asc())
    )
    rows = await db.scalars(statement)
    return [ApprovalRequestRead.model_validate(item) for item in rows.all()]


@router.get("/approvals/{approval_id}")
async def get_approval_request(approval_id: UUID, db: AsyncSession = Depends(get_db)) -> ApprovalRequestRead:
    """Returns one approval request so operators can inspect confidence and recommendation context."""

    approval = await db.get(ApprovalRequest, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return ApprovalRequestRead.model_validate(approval)


@router.post("/approvals/{approval_id}/approve")
async def approve_approval_request(
    approval_id: UUID,
    action: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestRead:
    """Approves a pending request and records reviewer identity for immutable audit traceability."""

    try:
        approval = await approve_request(str(approval_id), action.reviewed_by, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApprovalRequestRead.model_validate(approval)


@router.post("/approvals/{approval_id}/reject")
async def reject_approval_request(
    approval_id: UUID,
    action: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestRead:
    """Rejects a pending request when reviewer deems recommendation unsafe or insufficiently grounded."""

    try:
        approval = await reject_request(str(approval_id), action.reviewed_by, action.reason or "", db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApprovalRequestRead.model_validate(approval)


@router.post("/approvals/{approval_id}/escalate")
async def escalate_approval_request(
    approval_id: UUID,
    action: ApprovalAction,
    db: AsyncSession = Depends(get_db),
) -> ApprovalRequestRead:
    """Escalates a pending request when reviewer needs broader incident-command involvement."""

    try:
        approval = await escalate_request(str(approval_id), action.reason or "", db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApprovalRequestRead.model_validate(approval)
