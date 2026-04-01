from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RawLogEntryCreate(BaseModel):
    """Validates incoming telemetry logs so preprocessing receives normalized fields."""

    timestamp: datetime
    service_name: str = Field(min_length=1, max_length=255)
    log_level: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1)
    trace_id: str | None = Field(default=None, max_length=255)


class RawLogEntryRead(RawLogEntryCreate):
    """Represents persisted raw logs returned by API responses and internal lookups."""

    id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}