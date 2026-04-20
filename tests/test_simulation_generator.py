from sentinelops.simulation.generator import (
    generate_named_scenario,
    generate_scenario_payload,
    list_scenarios,
)


def test_scenario_catalog_exposes_multiple_benchmark_families() -> None:
    """Verifies the simulator exposes multiple scenario families rather than one fixed failure pattern."""

    scenario_ids = {scenario.scenario_id for scenario in list_scenarios()}
    assert {"db_latency", "payment_timeout", "auth_outage", "cache_stampede", "gateway_503"} <= scenario_ids


def test_generate_named_scenario_returns_logs_alerts_and_definition() -> None:
    """Verifies named scenario generation returns payload data alongside its expected benchmark metadata."""

    logs, alerts, definition = generate_named_scenario("auth_outage", seed=7)
    assert logs
    assert alerts
    assert definition.expected_top_cause == "auth-service"


def test_generate_scenario_payload_is_json_ready() -> None:
    """Verifies scenario payload helper emits API-ready logs and alerts with benchmark metadata included."""

    payload = generate_scenario_payload("cache_stampede", seed=11)
    assert payload["scenario_id"] == "cache_stampede"
    assert payload["expected_top_cause"] == "cache-service"
    assert payload["logs"]
    assert payload["alerts"]
