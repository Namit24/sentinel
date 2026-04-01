import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from sentinelops.database import Base


class Incident(Base):
    """Stores grouped incident output so downstream triage can inspect evidence and confidence."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN", index=True)
    affected_services: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    raw_alert_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    group_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    root_cause_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    top_cause_service: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)