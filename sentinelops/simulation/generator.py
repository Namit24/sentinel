from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sentinelops.schemas.alert import AlertCreate
from sentinelops.schemas.log_entry import RawLogEntryCreate


@dataclass(frozen=True)
class ScenarioDefinition:
    """Describes one synthetic incident family used for demos, tests, and benchmark runs."""

    scenario_id: str
    title: str
    description: str
    expected_top_cause: str
    affected_services: tuple[str, ...]
    expected_runbook_files: tuple[str, ...]


_SCENARIOS: dict[str, ScenarioDefinition] = {
    "db_latency": ScenarioDefinition(
        scenario_id="db_latency",
        title="DB Latency Cascade",
        description="Primary database latency spreads into payment timeouts and gateway 503s.",
        expected_top_cause="db-primary",
        affected_services=("db-primary", "payment-service", "api-gateway"),
        expected_runbook_files=("db_latency.md", "payment_timeout.md", "api_gateway_503.md"),
    ),
    "payment_timeout": ScenarioDefinition(
        scenario_id="payment_timeout",
        title="Payment Timeout Storm",
        description="Payment-service times out under load and degrades upstream request handling.",
        expected_top_cause="payment-service",
        affected_services=("payment-service", "api-gateway"),
        expected_runbook_files=("payment_timeout.md", "api_gateway_503.md"),
    ),
    "auth_outage": ScenarioDefinition(
        scenario_id="auth_outage",
        title="Auth Service Outage",
        description="Authentication failures propagate into gateway login and session errors.",
        expected_top_cause="auth-service",
        affected_services=("auth-service", "api-gateway"),
        expected_runbook_files=("auth_outage.md", "api_gateway_503.md"),
    ),
    "cache_stampede": ScenarioDefinition(
        scenario_id="cache_stampede",
        title="Cache Stampede",
        description="Cache miss storms amplify load and destabilize dependent payment traffic.",
        expected_top_cause="cache-service",
        affected_services=("cache-service", "payment-service", "db-primary"),
        expected_runbook_files=("cache_stampede.md", "payment_timeout.md", "db_latency.md"),
    ),
    "gateway_503": ScenarioDefinition(
        scenario_id="gateway_503",
        title="Gateway 503 Spike",
        description="Gateway routing and upstream exhaustion create a user-visible 503 incident.",
        expected_top_cause="api-gateway",
        affected_services=("api-gateway",),
        expected_runbook_files=("api_gateway_503.md",),
    ),
}


def _random_timestamp(rng: random.Random, start: datetime, end: datetime) -> datetime:
    """Creates realistic spread in event timing so deduplication behaves like production traffic."""

    delta_seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randint(0, max(delta_seconds, 1)))


def _noise_log(rng: random.Random, timestamp: datetime) -> RawLogEntryCreate:
    """Builds routine operational logs that act as distractors for preprocessing quality checks."""

    noise_pool = [
        ("auth-service", "INFO", "Token refresh completed for active session"),
        ("auth-service", "INFO", "OIDC metadata cache refreshed"),
        ("cache-service", "WARN", "Cache miss ratio exceeded baseline threshold"),
        ("api-gateway", "INFO", "Request completed with status 200"),
        ("payment-service", "INFO", "Payment reconciliation worker heartbeat"),
        ("db-primary", "INFO", "Checkpoint completed within target window"),
    ]
    service_name, log_level, message = rng.choice(noise_pool)
    return RawLogEntryCreate(
        timestamp=timestamp,
        service_name=service_name,
        log_level=log_level,
        message=message,
        trace_id=None,
    )


def _build_logs(
    rng: random.Random,
    failure_templates: list[tuple[str, str, str]],
    *,
    total_entries_range: tuple[int, int] = (220, 420),
    noise_ratio: float = 0.60,
) -> list[RawLogEntryCreate]:
    """Generates one noisy scenario timeline by mixing routine traffic with repeated failure templates."""

    total_entries = rng.randint(*total_entries_range)
    noise_target = int(total_entries * noise_ratio)
    failure_target = max(total_entries - noise_target, len(failure_templates))

    base_time = datetime.now(UTC) - timedelta(minutes=30)
    end_time = datetime.now(UTC)
    trace_id = f"trace-{uuid4()}"
    logs: list[RawLogEntryCreate] = []

    for _ in range(noise_target):
        logs.append(_noise_log(rng, _random_timestamp(rng, base_time, end_time)))

    for index in range(failure_target):
        service_name, log_level, message = failure_templates[index % len(failure_templates)]
        logs.append(
            RawLogEntryCreate(
                timestamp=base_time + timedelta(seconds=35 * index),
                service_name=service_name,
                log_level=log_level,
                message=message,
                trace_id=trace_id,
            )
        )

    rng.shuffle(logs)
    return logs


def _build_alerts(
    rng: random.Random,
    alert_templates: list[tuple[str, str, str]],
    *,
    extra_noise: list[tuple[str, str, str]] | None = None,
) -> list[AlertCreate]:
    """Creates alert payloads aligned to the chosen scenario while retaining some realistic background noise."""

    base_time = datetime.now(UTC) - timedelta(minutes=20)
    selected = list(alert_templates)
    if extra_noise:
        noise_count = min(len(extra_noise), max(1, len(alert_templates) // 2))
        selected.extend(rng.sample(extra_noise, noise_count))

    rng.shuffle(selected)
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


def _db_latency_bundle(rng: random.Random) -> tuple[list[RawLogEntryCreate], list[AlertCreate]]:
    """Builds the original DB latency cascade scenario used in the first project benchmark."""

    logs = _build_logs(
        rng,
        [
            ("db-primary", "WARN", "High query latency detected on primary node"),
            ("db-primary", "ERROR", "Query latency exceeded timeout threshold"),
            ("payment-service", "ERROR", "Timeout waiting for db-primary response"),
            ("api-gateway", "ERROR", "Upstream payment-service request failed with 503"),
            ("api-gateway", "CRITICAL", "Request storm: payment-service unavailable"),
        ],
        noise_ratio=0.65,
    )
    alerts = _build_alerts(
        rng,
        [
            ("db-primary", "HIGH", "Primary database query latency breach"),
            ("db-primary", "CRITICAL", "Database timeout rate critical"),
            ("payment-service", "HIGH", "Payment dependency timeout surge"),
            ("api-gateway", "HIGH", "Gateway 503 rate elevated"),
            ("api-gateway", "CRITICAL", "API gateway upstream dependency unavailable"),
        ],
        extra_noise=[
            ("cache-service", "LOW", "Cache miss warning burst"),
            ("auth-service", "LOW", "Routine auth anomaly check warning"),
            ("payment-service", "MEDIUM", "Payment retry queue growing"),
        ],
    )
    return logs, alerts


def _payment_timeout_bundle(rng: random.Random) -> tuple[list[RawLogEntryCreate], list[AlertCreate]]:
    """Builds a payment-service-led incident where timeouts dominate before hard failure."""

    logs = _build_logs(
        rng,
        [
            ("payment-service", "ERROR", "Request deadline exceeded while authorizing payment"),
            ("payment-service", "CRITICAL", "Circuit breaker opened on payment execution path"),
            ("api-gateway", "ERROR", "Payment upstream returned deadline exceeded"),
            ("api-gateway", "WARN", "Retry amplification detected on /payments"),
        ],
        noise_ratio=0.58,
    )
    alerts = _build_alerts(
        rng,
        [
            ("payment-service", "CRITICAL", "Payment authorization timeout storm"),
            ("payment-service", "HIGH", "Payment worker queue backlog rising"),
            ("api-gateway", "HIGH", "Gateway payment route latency elevated"),
        ],
        extra_noise=[
            ("db-primary", "LOW", "Read latency mildly elevated"),
            ("cache-service", "LOW", "Cache refill rate above baseline"),
        ],
    )
    return logs, alerts


def _auth_outage_bundle(rng: random.Random) -> tuple[list[RawLogEntryCreate], list[AlertCreate]]:
    """Builds an auth-service outage where login and token validation paths fail upstream."""

    logs = _build_logs(
        rng,
        [
            ("auth-service", "ERROR", "Token introspection timed out against auth backend"),
            ("auth-service", "CRITICAL", "Session validation requests failing across replicas"),
            ("api-gateway", "ERROR", "Login route upstream auth-service unavailable"),
            ("api-gateway", "WARN", "Gateway auth retries rising above safety budget"),
        ],
        noise_ratio=0.57,
    )
    alerts = _build_alerts(
        rng,
        [
            ("auth-service", "CRITICAL", "Authentication success rate below threshold"),
            ("auth-service", "HIGH", "Token validation latency elevated"),
            ("api-gateway", "HIGH", "Gateway auth route failures increasing"),
        ],
        extra_noise=[
            ("db-primary", "LOW", "Replica lag within tolerance"),
            ("cache-service", "LOW", "Session cache churn warning"),
        ],
    )
    return logs, alerts


def _cache_stampede_bundle(rng: random.Random) -> tuple[list[RawLogEntryCreate], list[AlertCreate]]:
    """Builds a cache miss storm that spills into payment and database pressure."""

    logs = _build_logs(
        rng,
        [
            ("cache-service", "WARN", "Hot key refill contention causing cache miss storm"),
            ("cache-service", "ERROR", "Cache lock contention delaying hot key recomputation"),
            ("payment-service", "ERROR", "Timeout waiting for cache-service on checkout flow"),
            ("db-primary", "WARN", "Read surge driven by cache fallback traffic"),
        ],
        noise_ratio=0.59,
    )
    alerts = _build_alerts(
        rng,
        [
            ("cache-service", "CRITICAL", "Cache miss ratio spike on critical key family"),
            ("payment-service", "HIGH", "Checkout latency elevated due to cache fallback"),
            ("db-primary", "MEDIUM", "Database read amplification detected"),
        ],
        extra_noise=[
            ("api-gateway", "LOW", "Route latency slightly above baseline"),
            ("auth-service", "LOW", "Session refresh queue growing"),
        ],
    )
    return logs, alerts


def _gateway_503_bundle(rng: random.Random) -> tuple[list[RawLogEntryCreate], list[AlertCreate]]:
    """Builds a gateway-focused incident where routing and upstream target selection degrade visibly."""

    logs = _build_logs(
        rng,
        [
            ("api-gateway", "ERROR", "Gateway upstream target returned repeated 503 responses"),
            ("api-gateway", "CRITICAL", "Gateway request storm causing widespread 503 saturation"),
            ("api-gateway", "WARN", "Health check churn increasing across target pools"),
        ],
        noise_ratio=0.62,
    )
    alerts = _build_alerts(
        rng,
        [
            ("api-gateway", "CRITICAL", "API gateway 503 ratio above incident threshold"),
            ("api-gateway", "HIGH", "Gateway upstream target health degraded"),
        ],
        extra_noise=[
            ("payment-service", "LOW", "Transient timeout retries observed"),
            ("auth-service", "LOW", "Minor auth route latency increase"),
        ],
    )
    return logs, alerts


_SCENARIO_GENERATORS = {
    "db_latency": _db_latency_bundle,
    "payment_timeout": _payment_timeout_bundle,
    "auth_outage": _auth_outage_bundle,
    "cache_stampede": _cache_stampede_bundle,
    "gateway_503": _gateway_503_bundle,
}


def list_scenarios() -> list[ScenarioDefinition]:
    """Returns the full synthetic scenario catalog for UI selectors and benchmark tooling."""

    return [definition for _, definition in sorted(_SCENARIOS.items(), key=lambda item: item[0])]


def get_scenario_definition(scenario_id: str) -> ScenarioDefinition:
    """Returns one scenario definition and raises clearly when callers request an unknown scenario."""

    try:
        return _SCENARIOS[scenario_id]
    except KeyError as exc:
        known = ", ".join(sorted(_SCENARIOS))
        raise ValueError(f"Unknown scenario '{scenario_id}'. Known scenarios: {known}") from exc


def generate_named_scenario(
    scenario_id: str = "db_latency",
    *,
    seed: int | None = None,
) -> tuple[list[RawLogEntryCreate], list[AlertCreate], ScenarioDefinition]:
    """Generates one named scenario bundle with optional deterministic seeding for benchmarks."""

    scenario = get_scenario_definition(scenario_id)
    rng = random.Random(seed)
    logs, alerts = _SCENARIO_GENERATORS[scenario_id](rng)
    return logs, alerts, scenario


def generate_scenario_payload(
    scenario_id: str = "db_latency",
    *,
    seed: int | None = None,
) -> dict:
    """Builds a JSON-ready scenario payload so dashboards and eval tools can call the API directly."""

    logs, alerts, scenario = generate_named_scenario(scenario_id=scenario_id, seed=seed)
    return {
        "scenario_id": scenario.scenario_id,
        "scenario_title": scenario.title,
        "expected_top_cause": scenario.expected_top_cause,
        "expected_runbook_files": list(scenario.expected_runbook_files),
        "logs": [entry.model_dump(mode="json") for entry in logs],
        "alerts": [alert.model_dump(mode="json") for alert in alerts],
    }


def generate_incident_scenario(seed: int | None = None) -> list[RawLogEntryCreate]:
    """Preserves the original helper API by returning the default DB latency scenario logs."""

    logs, _, _ = generate_named_scenario("db_latency", seed=seed)
    return logs


def generate_alerts(seed: int | None = None) -> list[AlertCreate]:
    """Preserves the original helper API by returning the default DB latency scenario alerts."""

    _, alerts, _ = generate_named_scenario("db_latency", seed=seed)
    return alerts
