from datetime import UTC, datetime, timedelta

from sentinelops.schemas.log_entry import RawLogEntryCreate
from sentinelops.services.preprocessor import deduplicate_logs, filter_logs, structure_for_llm


def _log(service: str, level: str, message: str, seconds: int) -> RawLogEntryCreate:
    """Builds deterministic test logs so preprocessing behavior can be asserted precisely."""

    base = datetime(2026, 4, 1, tzinfo=UTC)
    return RawLogEntryCreate(
        timestamp=base + timedelta(seconds=seconds),
        service_name=service,
        log_level=level,
        message=message,
        trace_id="trace-test",
    )


def test_info_logs_dropped_when_error_rate_low() -> None:
    """Verifies low-error services lose INFO noise to keep downstream grouping focused."""

    logs = [
        _log("auth-service", "INFO", "Heartbeat", 0),
        _log("auth-service", "INFO", "Token refreshed", 5),
        _log("auth-service", "WARN", "Slight auth latency", 10),
    ]
    filtered = filter_logs(logs)
    assert all(entry.log_level != "INFO" for entry in filtered)
    assert len(filtered) == 1


def test_info_logs_kept_when_service_error_rate_above_ten_percent() -> None:
    """Verifies contextual INFO is preserved when a service is unstable enough to need richer clues."""

    logs = [
        _log("payment-service", "INFO", "Worker tick", 0),
        _log("payment-service", "INFO", "Queue depth healthy", 2),
        _log("payment-service", "ERROR", "Timeout waiting for db", 4),
    ]
    filtered = filter_logs(logs)
    assert sum(1 for item in filtered if item.log_level == "INFO") == 2
    assert sum(1 for item in filtered if item.log_level == "ERROR") == 1


def test_repeated_messages_within_sixty_seconds_are_deduplicated() -> None:
    """Verifies repeated service-message pairs in one minute collapse to a single counted entry."""

    logs = [
        _log("api-gateway", "ERROR", "Upstream timeout", 0),
        _log("api-gateway", "ERROR", "Upstream timeout", 10),
        _log("api-gateway", "ERROR", "Upstream timeout", 20),
    ]
    deduped = deduplicate_logs(logs)
    assert len(deduped) == 1
    assert deduped[0]["count"] == 3


def test_structure_output_never_exceeds_eighty_entries() -> None:
    """Verifies hard cap enforcement so prompts never exceed the LLM payload budget."""

    deduped = [
        {
            "timestamp": datetime(2026, 4, 1, tzinfo=UTC) + timedelta(seconds=index),
            "service": f"service-{index}",
            "log_level": "ERROR" if index % 2 == 0 else "WARN",
            "message": f"Timeout waiting for dependency {index}",
            "count": 1,
            "trace_id": "trace-test",
        }
        for index in range(150)
    ]
    structured = structure_for_llm(deduped)
    assert len(structured) <= 80


def test_deduplicate_logs_redacts_sensitive_tokens_before_llm_structuring() -> None:
    """Verifies emails, JWT-like strings, and PAN-like values are removed from model-facing payloads."""

    logs = [
        _log(
            "auth-service",
            "ERROR",
            "User jane.doe@example.com failed auth with token "
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature and card 4111 1111 1111 1111",
            0,
        )
    ]
    deduped = deduplicate_logs(logs)
    assert deduped
    message = deduped[0]["message"]
    assert "[REDACTED_EMAIL]" in message
    assert "[REDACTED_TOKEN]" in message
    assert "[REDACTED_PAN]" in message
