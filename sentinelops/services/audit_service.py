import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def log_event(
    db: AsyncSession,
    event_type: str,
    description: str,
    incident_id: str | UUID | None = None,
    approval_request_id: str | UUID | None = None,
    actor: str = "system",
    payload: dict | None = None,
    auto_commit: bool = True,
) -> AuditLog | None:
    """Writes a best-effort audit event and never lets audit persistence failures break caller flows."""

    try:
        incident_uuid = UUID(str(incident_id)) if incident_id is not None else None
        approval_uuid = UUID(str(approval_request_id)) if approval_request_id is not None else None
    except ValueError:
        logger.exception("Invalid UUID while preparing audit event payload")
        return None

    try:
        event = AuditLog(
            incident_id=incident_uuid,
            approval_request_id=approval_uuid,
            event_type=event_type,
            actor=actor,
            description=description,
            payload=payload,
        )
        # Use a savepoint so audit failures do not poison the caller's broader transaction.
        async with db.begin_nested():
            db.add(event)
            await db.flush()
        if auto_commit:
            await db.commit()
            await db.refresh(event)
        return event
    except Exception:
        logger.exception("Failed to persist audit event: %s", event_type)
        if auto_commit:
            try:
                await db.rollback()
            except Exception:
                logger.exception("Failed to rollback after audit log write failure")
        return None


async def get_audit_trail(incident_id: str, db: AsyncSession) -> list[AuditLog]:
    """Returns a chronological event trail for one incident so humans can reconstruct every decision step."""

    statement = (
        select(AuditLog)
        .where(AuditLog.incident_id == UUID(incident_id))
        .order_by(AuditLog.created_at.asc())
    )
    rows = await db.scalars(statement)
    return list(rows.all())
