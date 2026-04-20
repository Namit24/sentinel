from eval.metrics import summarize_results


def test_summarize_results_computes_accuracy_and_source_hits() -> None:
    """Verifies benchmark summarization preserves top-cause and source-hit rates across scenarios."""

    raw_results = [
        {
            "scenario_id": "db_latency",
            "scenario_title": "DB Latency Cascade",
            "expected_top_cause": "db-primary",
            "run_index": 1,
            "success": True,
            "fallback_used": False,
            "grouping_confidence": 0.9,
            "top_cause_service": "db-primary",
            "top_cause_correct": True,
            "root_cause_confidence": 0.95,
            "analysis_method": "graph+vector",
            "runbook_source_files": ["db_latency.md", "payment_timeout.md"],
            "runbook_grounded": True,
            "runbook_confidence": 0.8,
            "runbook_expected_file_hit": True,
            "latency_seconds": 12.5,
        },
        {
            "scenario_id": "gateway_503",
            "scenario_title": "Gateway 503 Spike",
            "expected_top_cause": "api-gateway",
            "run_index": 2,
            "success": True,
            "fallback_used": True,
            "grouping_confidence": 0.3,
            "top_cause_service": "payment-service",
            "top_cause_correct": False,
            "root_cause_confidence": 0.65,
            "analysis_method": "graph_only",
            "runbook_source_files": ["api_gateway_503.md"],
            "runbook_grounded": True,
            "runbook_confidence": 0.6,
            "runbook_expected_file_hit": True,
            "latency_seconds": 18.0,
        },
    ]

    summary = summarize_results(raw_results)

    assert summary["total_runs"] == 2
    assert summary["successful_runs"] == 2
    assert summary["root_cause_top1_accuracy"] == 0.5
    assert summary["grouping_fallback_rate"] == 0.5
    assert summary["runbook_correct_source_rate"] == 1.0
    assert any(row["scenario_id"] == "db_latency" for row in summary["scenario_breakdown"])


def test_summarize_results_handles_failures_without_crashing() -> None:
    """Verifies failed runs remain represented in the summary without corrupting success-only metrics."""

    raw_results = [
        {
            "scenario_id": "auth_outage",
            "scenario_title": "Auth Service Outage",
            "expected_top_cause": "auth-service",
            "run_index": 1,
            "success": False,
            "error": "timeout",
            "latency_seconds": 30.0,
        }
    ]

    summary = summarize_results(raw_results)

    assert summary["total_runs"] == 1
    assert summary["successful_runs"] == 0
    assert summary["failed_runs"] == 1
    assert summary["overall_success_rate"] == 0.0


def test_summarize_results_reports_stage_metrics_and_latency_spikes() -> None:
    """Verifies benchmark summary exposes dominant-stage spike diagnostics and policy distributions."""

    raw_results = [
        {
            "scenario_id": "db_latency",
            "scenario_title": "DB Latency Cascade",
            "expected_top_cause": "db-primary",
            "run_index": 1,
            "success": True,
            "fallback_used": False,
            "grouping_confidence": 0.9,
            "top_cause_service": "db-primary",
            "top_cause_correct": True,
            "root_cause_confidence": 0.85,
            "analysis_method": "graph+vector",
            "runbook_source_files": ["db_latency.md"],
            "runbook_grounded": True,
            "runbook_confidence": 0.8,
            "runbook_expected_file_hit": True,
            "policy_status": "ALLOW_HUMAN_REVIEW",
            "risk_level": "LOW",
            "reviewer_tier": "operator",
            "grouping_ms": 100.0,
            "root_cause_ms": 120.0,
            "runbook_ms": 140.0,
            "approval_ms": 20.0,
            "pipeline_total_ms": 380.0,
            "latency_seconds": 1.0,
        },
        {
            "scenario_id": "gateway_503",
            "scenario_title": "Gateway 503 Spike",
            "expected_top_cause": "api-gateway",
            "run_index": 2,
            "success": True,
            "fallback_used": True,
            "grouping_confidence": 0.4,
            "top_cause_service": "api-gateway",
            "top_cause_correct": True,
            "root_cause_confidence": 0.62,
            "analysis_method": "graph_only",
            "runbook_source_files": ["api_gateway_503.md"],
            "runbook_grounded": True,
            "runbook_confidence": 0.7,
            "runbook_expected_file_hit": True,
            "policy_status": "ESCALATE_REQUIRED",
            "risk_level": "HIGH",
            "reviewer_tier": "senior-operator",
            "grouping_ms": 200.0,
            "root_cause_ms": 150.0,
            "runbook_ms": 1600.0,
            "approval_ms": 25.0,
            "pipeline_total_ms": 1975.0,
            "latency_seconds": 5.0,
        },
        {
            "scenario_id": "payment_timeout",
            "scenario_title": "Payment Timeout Burst",
            "expected_top_cause": "payment-service",
            "run_index": 3,
            "success": True,
            "fallback_used": False,
            "grouping_confidence": 0.88,
            "top_cause_service": "payment-service",
            "top_cause_correct": True,
            "root_cause_confidence": 0.82,
            "analysis_method": "graph+vector",
            "runbook_source_files": ["payment_timeout.md"],
            "runbook_grounded": True,
            "runbook_confidence": 0.78,
            "runbook_expected_file_hit": True,
            "policy_status": "RESTRICTED_REVIEW",
            "risk_level": "MEDIUM",
            "reviewer_tier": "operator",
            "grouping_ms": 110.0,
            "root_cause_ms": 130.0,
            "runbook_ms": 150.0,
            "approval_ms": 18.0,
            "pipeline_total_ms": 408.0,
            "latency_seconds": 1.2,
        },
        {
            "scenario_id": "auth_outage",
            "scenario_title": "Auth Service Outage",
            "expected_top_cause": "auth-service",
            "run_index": 4,
            "success": True,
            "fallback_used": False,
            "grouping_confidence": 0.86,
            "top_cause_service": "auth-service",
            "top_cause_correct": True,
            "root_cause_confidence": 0.81,
            "analysis_method": "graph+vector",
            "runbook_source_files": ["auth_outage.md"],
            "runbook_grounded": True,
            "runbook_confidence": 0.75,
            "runbook_expected_file_hit": True,
            "policy_status": "ALLOW_HUMAN_REVIEW",
            "risk_level": "LOW",
            "reviewer_tier": "operator",
            "grouping_ms": 115.0,
            "root_cause_ms": 125.0,
            "runbook_ms": 145.0,
            "approval_ms": 21.0,
            "pipeline_total_ms": 406.0,
            "latency_seconds": 1.1,
        },
    ]

    summary = summarize_results(raw_results)

    assert summary["pipeline_stage_means_ms"]["runbook"] > summary["pipeline_stage_means_ms"]["approval"]
    assert summary["policy_status_counts"]["ALLOW_HUMAN_REVIEW"] == 2
    assert summary["latency_spike_count"] == 1
    assert summary["latency_spike_runs"][0]["dominant_stage"] == "runbook"
