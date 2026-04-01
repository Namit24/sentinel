from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AlertCreate(BaseModel):
    """Validates incoming alert payloads so grouped incidents can reference canonical alerts."""

    alert_id: str = Field(min_length=1, max_length=255)
    service_name: str = Field(min_length=1, max_length=255)
    severity: str = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1)
    timestamp: datetime
    status: str = Field(default="OPEN", min_length=1, max_length=32)


class AlertRead(AlertCreate):
    """Represents persisted alerts returned by APIs or used in incident drill-down views."""

    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}