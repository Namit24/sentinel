from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from sentinelops.schemas.alert import AlertCreate
from sentinelops.schemas.approval import ApprovalRequestRead
from sentinelops.schemas.log_entry import RawLogEntryCreate
from sentinelops.schemas.policy import PolicyDecision
from sentinelops.schemas.root_cause import RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation


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


class PipelineMetrics(BaseModel):
    """Persists stage-level latency and control metadata so operators can diagnose slow or risky runs."""

    grouping_ms: float = Field(ge=0.0)
    root_cause_ms: float = Field(ge=0.0)
    runbook_ms: float = Field(ge=0.0)
    approval_ms: float = Field(ge=0.0)
    total_ms: float = Field(ge=0.0)
    log_count: int = Field(ge=0)
    alert_count: int = Field(ge=0)
    fallback_used: bool
    analysis_method: str
    runbook_grounded: bool


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
    runbook_data: RunbookRecommendation | None = None
    pipeline_metrics: PipelineMetrics | None = None
    policy_data: PolicyDecision | None = None
    approval_request: ApprovalRequestRead | None = None

    model_config = {"from_attributes": True}


class IncidentListItem(BaseModel):
    """Provides a lightweight incident projection for list views and quick triage scanning."""

    id: UUID
    status: str
    affected_services: list[str]
    confidence_score: float = Field(ge=0.0, le=1.0)
    top_cause_service: str | None = None
    fallback_used: bool = False
    risk_level: str | None = None
    policy_status: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IngestPayload(BaseModel):
    """Bundles telemetry logs and alerts in one request to keep ingestion atomic."""

    logs: list[RawLogEntryCreate]
    alerts: list[AlertCreate]
