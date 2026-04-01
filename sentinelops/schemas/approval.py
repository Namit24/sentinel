from datetime import datetime

from pydantic import BaseModel, field_validator


class ApprovalRequestRead(BaseModel):
    """Represents a human-review approval request returned to operators for decision-making workflows."""

    id: str
    incident_id: str
    status: str
    recommendation_summary: str
    top_cause: str
    confidence_score: float
    auto_escalated: bool
    escalation_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", "incident_id", mode="before")
    @classmethod
    def _coerce_uuid_fields(cls, value):
        """Normalizes UUID-backed ORM identifiers into string API fields for stable wire format."""

        return str(value)


class ApprovalAction(BaseModel):
    """Captures reviewer identity and optional reason for approval workflow state transitions."""

    reviewed_by: str
    reason: str | None = None


class AuditEventRead(BaseModel):
    """Provides a serializable audit event view for immutable incident decision timeline responses."""

    id: str
    event_type: str
    actor: str
    description: str
    payload: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, value):
        """Normalizes UUID-backed audit identifiers into string API fields for JSON responses."""

        return str(value)
