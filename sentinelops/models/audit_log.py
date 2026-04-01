import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, event, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sentinelops.database import Base


class AuditEventType:
    """Defines canonical audit event names so logs remain queryable and consistent."""

    INCIDENT_CREATED = "INCIDENT_CREATED"
    GROUPING_COMPLETED = "GROUPING_COMPLETED"
    ROOT_CAUSE_RANKED = "ROOT_CAUSE_RANKED"
    RUNBOOK_RETRIEVED = "RUNBOOK_RETRIEVED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    ESCALATION_TRIGGERED = "ESCALATION_TRIGGERED"
    FALLBACK_USED = "FALLBACK_USED"


class AuditLog(Base):
    """Stores immutable system and human decision events for incident-level traceability."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


@event.listens_for(AuditLog, "before_update", propagate=True)
def _prevent_audit_updates(mapper, connection, target):
    """Prevents audit row mutation so the decision history remains immutable once written."""

    raise ValueError("Audit log is append-only and cannot be updated.")


@event.listens_for(AuditLog, "before_delete", propagate=True)
def _prevent_audit_deletes(mapper, connection, target):
    """Prevents audit row deletion to preserve a complete timeline for compliance and debugging."""

    raise ValueError("Audit log is append-only and cannot be deleted.")
