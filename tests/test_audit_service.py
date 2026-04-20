import asyncio
from uuid import uuid4

import pytest

from sentinelops.database import AsyncSessionLocal, engine
from sentinelops.models.audit_log import AuditLog
from sentinelops.services.audit_service import get_audit_trail, log_event


@pytest.fixture(autouse=True)
async def _reset_engine_pool() -> None:
    """Disposes pooled async connections between tests so audit DB access stays loop-safe."""

    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.asyncio
async def test_log_event_never_raises_with_invalid_incident_id() -> None:
    """Verifies audit logging is best-effort and does not raise when incident identifiers are malformed."""

    async with AsyncSessionLocal() as db:
        event = await log_event(
            db=db,
            event_type="INCIDENT_CREATED",
            description="Attempting invalid UUID write",
            incident_id="not-a-uuid",
        )
        assert event is None


@pytest.mark.asyncio
async def test_get_audit_trail_returns_chronological_order() -> None:
    """Verifies incident-specific audit trail is returned in ascending created-time order."""

    incident_id = str(uuid4())
    async with AsyncSessionLocal() as db:
        await log_event(
            db=db,
            event_type="INCIDENT_CREATED",
            description="first",
            incident_id=incident_id,
        )
        await asyncio.sleep(0.01)
        await log_event(
            db=db,
            event_type="GROUPING_COMPLETED",
            description="second",
            incident_id=incident_id,
        )
        trail = await get_audit_trail(incident_id=incident_id, db=db)
        assert len(trail) >= 2
        descriptions = [event.description for event in trail[-2:]]
        assert descriptions == ["first", "second"]


@pytest.mark.asyncio
async def test_audit_rows_are_append_only() -> None:
    """Verifies attempted ORM updates to audit rows are rejected, preserving immutable history."""

    incident_id = str(uuid4())
    async with AsyncSessionLocal() as db:
        created = await log_event(
            db=db,
            event_type="INCIDENT_CREATED",
            description="immutable snapshot",
            incident_id=incident_id,
        )
        assert created is not None
        audit_id = created.id

        row = await db.get(AuditLog, audit_id)
        assert row is not None
        row.description = "tampered"

        with pytest.raises(ValueError):
            await db.commit()

        await db.rollback()
        unchanged = await db.get(AuditLog, audit_id)
        assert unchanged is not None
        assert unchanged.description == "immutable snapshot"
