from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from sentinelops.schemas.alert import AlertCreate
from sentinelops.schemas.log_entry import RawLogEntryCreate
from sentinelops.schemas.root_cause import RootCauseReport


class IncidentGroup(BaseModel):
    """Represents one grouped cluster of events to keep root-cause reasoning explainable."""

    group_id: str
    likely_cause: str
    affected_services: list[str]
    supporting_events: list[dict]
    confidence_score: float = Field(ge=0.0, le=1.0)


class GroupingOutput(BaseModel):
    """Defines the strict envelope returned by grouping engines so APIs stay schema-safe."""

    result: list[IncidentGroup]
    confidence_score: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    fallback_used: bool
    fallback_reason: str | None = None


class IncidentRead(BaseModel):
    """Returns a full incident snapshot including grouped data and evidence for auditability."""

    id: UUID
    created_at: datetime
    status: str
    affected_services: list[str]
    raw_alert_ids: list[str]
    group_data: GroupingOutput
    confidence_score: float = Field(ge=0.0, le=1.0)
    fallback_used: bool
    evidence: list[str]
    top_cause_service: str | None = None
    root_cause_data: RootCauseReport | None = None

    model_config = {"from_attributes": True}


class IncidentListItem(BaseModel):
    """Provides a lightweight incident projection for list views and quick triage scanning."""

    id: UUID
    status: str
    affected_services: list[str]
    confidence_score: float = Field(ge=0.0, le=1.0)
    created_at: datetime

    model_config = {"from_attributes": True}


class IngestPayload(BaseModel):
    """Bundles telemetry logs and alerts in one request to keep ingestion atomic."""

    logs: list[RawLogEntryCreate]
    alerts: list[AlertCreate]