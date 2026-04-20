from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.schemas.log_entry import RawLogEntryCreate
from sentinelops.services.grouper import group_telemetry
from sentinelops.services.llm_client import LLMFallbackRequired


@pytest.mark.asyncio
async def test_fallback_used_when_llm_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies grouper switches to deterministic fallback when LLM path raises fallback signal."""

    async def _raise_fallback(self, structured_events: list[dict], db: AsyncSession):
        """Forces LLM fallback condition for deterministic test coverage."""

        raise LLMFallbackRequired("forced test failure")

    monkeypatch.setattr("sentinelops.services.llm_client.GeminiClient.group_incidents", _raise_fallback)
    logs = [
        RawLogEntryCreate(
            timestamp=datetime(2026, 4, 1, tzinfo=UTC),
            service_name="api-gateway",
            log_level="ERROR",
            message="Upstream timeout",
            trace_id="trace-test",
        )
    ]

    output = await group_telemetry(logs, db=None)  # type: ignore[arg-type]
    assert output.fallback_used is True
    assert output.fallback_reason is not None


@pytest.mark.asyncio
async def test_empty_input_returns_without_calling_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies empty telemetry exits early so no LLM call is attempted unnecessarily."""

    async def _should_not_run(self, structured_events: list[dict], db: AsyncSession):
        """Fails the test if empty-input short-circuit is broken."""

        raise AssertionError("LLM should not be called for empty input")

    monkeypatch.setattr(
        "sentinelops.services.llm_client.GeminiClient.group_incidents",
        _should_not_run,
    )
    output = await group_telemetry([], db=None)  # type: ignore[arg-type]
    assert output.result == []
    assert output.confidence_score == 0.0
    assert output.fallback_used is False