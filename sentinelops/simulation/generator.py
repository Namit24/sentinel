import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sentinelops.schemas.alert import AlertCreate
from sentinelops.schemas.log_entry import RawLogEntryCreate

SERVICES = [
    "api-gateway",
    "auth-service",
    "payment-service",
    "db-primary",
    "cache-service",
]


def _random_timestamp(start: datetime, end: datetime) -> datetime:
    """Creates realistic spread in event timing so deduplication behaves like production traffic."""

    delta_seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, max(delta_seconds, 1)))


def _noise_log(timestamp: datetime) -> RawLogEntryCreate:
    """Builds routine operational logs that act as distractors for preprocessing quality checks."""

    noise_pool = [
        ("auth-service", "INFO", "Token refresh completed for active session"),
        ("auth-service", "INFO", "OIDC metadata cache refreshed"),
        ("cache-service", "WARN", "Cache miss ratio exceeded baseline threshold"),
        ("api-gateway", "INFO", "Request completed with status 200"),
        ("payment-service", "INFO", "Payment reconciliation worker heartbeat"),
    ]
    service_name, log_level, message = random.choice(noise_pool)
    return RawLogEntryCreate(
        timestamp=timestamp,
        service_name=service_name,
        log_level=log_level,
        message=message,
        trace_id=None,
    )


def generate_incident_scenario() -> list[RawLogEntryCreate]:
    """Generates a noisy failure cascade dataset to test ingestion, filtering, and grouping logic."""

    total_entries = random.randint(200, 500)
    noise_target = int(total_entries * 0.65)
    failure_target = total_entries - noise_target

    base_time = datetime.now(UTC) - timedelta(minutes=30)
    end_time = datetime.now(UTC)
    trace_id = f"trace-{uuid4()}"
    logs: list[RawLogEntryCreate] = []

    for _ in range(noise_target):
        logs.append(_noise_log(_random_timestamp(base_time, end_time)))

    failure_templates = [
        ("db-primary", "WARN", "High query latency detected on primary node"),
        ("db-primary", "ERROR", "Query latency exceeded timeout threshold"),
        ("payment-service", "ERROR", "Timeout waiting for db-primary response"),
        ("api-gateway", "ERROR", "Upstream payment-service request failed with 503"),
        ("api-gateway", "CRITICAL", "Request storm: payment-service unavailable"),
    ]

    for index in range(failure_target):
        service_name, log_level, message = failure_templates[index % len(failure_templates)]
        logs.append(
            RawLogEntryCreate(
                timestamp=base_time + timedelta(seconds=45 * index),
                service_name=service_name,
                log_level=log_level,
                message=message,
                trace_id=trace_id,
            )
        )

    random.shuffle(logs)
    return logs


def generate_alerts() -> list[AlertCreate]:
    """Creates scenario-aligned alerts so ingestion can persist external alert identifiers."""

    base_time = datetime.now(UTC) - timedelta(minutes=20)
    alert_templates = [
        ("db-primary", "HIGH", "Primary database query latency breach"),
        ("db-primary", "CRITICAL", "Database timeout rate critical"),
        ("payment-service", "HIGH", "Payment dependency timeout surge"),
        ("api-gateway", "HIGH", "Gateway 503 rate elevated"),
        ("api-gateway", "CRITICAL", "API gateway upstream dependency unavailable"),
        ("cache-service", "LOW", "Cache miss warning burst"),
        ("auth-service", "LOW", "Routine auth anomaly check warning"),
        ("payment-service", "MEDIUM", "Payment retry queue growing"),
    ]
    random.shuffle(alert_templates)
    count = random.randint(5, 10)
    selected = alert_templates[:count]

    alerts: list[AlertCreate] = []
    run_token = uuid4().hex[:8].upper()
    for index, (service_name, severity, description) in enumerate(selected):
        alerts.append(
            AlertCreate(
                alert_id=f"ALT-{run_token}-{1000 + index}",
                service_name=service_name,
                severity=severity,
                description=description,
                timestamp=base_time + timedelta(minutes=index),
                status="OPEN",
            )
        )
    return alerts