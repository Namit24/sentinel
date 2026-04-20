from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _safe_mean(values: list[float]) -> float:
    """Returns arithmetic mean or zero when a metric distribution is empty."""

    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    """Computes a simple linear percentile so latency summaries do not require external deps."""

    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _dominant_stage(row: dict[str, Any]) -> str | None:
    """Returns the slowest internal stage for one run so latency spikes are easier to explain."""

    stage_map = {
        "grouping_ms": "grouping",
        "root_cause_ms": "root_cause",
        "runbook_ms": "runbook",
        "approval_ms": "approval",
    }
    values = {
        label: float(row.get(key, 0.0))
        for key, label in stage_map.items()
        if row.get(key) is not None
    }
    if not values:
        return None
    return max(values, key=values.get)


def _spike_threshold(values: list[float]) -> float:
    """Computes a simple outlier threshold so dashboards can flag unusually slow runs."""

    if not values:
        return 0.0
    if len(values) < 4:
        return _percentile(values, 0.95)
    q1 = _percentile(values, 0.25)
    q3 = _percentile(values, 0.75)
    return q3 + (1.5 * (q3 - q1))


def summarize_results(raw_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregates raw benchmark runs into a compact summary consumed by docs and dashboards."""

    successful = [row for row in raw_results if row.get("success")]
    failures = [row for row in raw_results if not row.get("success")]

    latencies = [float(row.get("latency_seconds", 0.0)) for row in successful]
    grouping_stage_ms = [float(row.get("grouping_ms", 0.0)) for row in successful if row.get("grouping_ms") is not None]
    root_cause_stage_ms = [
        float(row.get("root_cause_ms", 0.0)) for row in successful if row.get("root_cause_ms") is not None
    ]
    runbook_stage_ms = [float(row.get("runbook_ms", 0.0)) for row in successful if row.get("runbook_ms") is not None]
    approval_stage_ms = [float(row.get("approval_ms", 0.0)) for row in successful if row.get("approval_ms") is not None]
    pipeline_totals_ms = [
        float(row.get("pipeline_total_ms", 0.0)) for row in successful if row.get("pipeline_total_ms") is not None
    ]
    grouping_confidences = [
        float(row.get("grouping_confidence", 0.0))
        for row in successful
        if row.get("grouping_confidence") is not None
    ]
    runbook_confidences = [
        float(row.get("runbook_confidence", 0.0))
        for row in successful
        if row.get("runbook_confidence") is not None
    ]
    root_cause_confidences = [
        float(row.get("root_cause_confidence", 0.0))
        for row in successful
        if row.get("root_cause_confidence") is not None
    ]

    truth_rows = [row for row in successful if row.get("top_cause_correct") is not None]
    correct_rows = [row for row in truth_rows if row.get("top_cause_correct") is True]
    source_truth_rows = [
        row for row in successful if row.get("runbook_expected_file_hit") is not None
    ]
    source_hit_rows = [
        row for row in source_truth_rows if row.get("runbook_expected_file_hit") is True
    ]

    source_counter: Counter[str] = Counter()
    for row in successful:
        source_counter.update(str(item) for item in row.get("runbook_source_files", []))

    top_cause_counter = Counter(
        str(row.get("top_cause_service"))
        for row in successful
        if row.get("top_cause_service")
    )
    policy_status_counter = Counter(
        str(row.get("policy_status"))
        for row in successful
        if row.get("policy_status")
    )
    risk_level_counter = Counter(
        str(row.get("risk_level"))
        for row in successful
        if row.get("risk_level")
    )
    reviewer_tier_counter = Counter(
        str(row.get("reviewer_tier"))
        for row in successful
        if row.get("reviewer_tier")
    )
    spike_threshold = _spike_threshold(latencies)
    latency_spike_runs = [
        {
            "run_index": row.get("run_index"),
            "scenario_id": row.get("scenario_id"),
            "scenario_title": row.get("scenario_title"),
            "latency_seconds": row.get("latency_seconds"),
            "pipeline_total_ms": row.get("pipeline_total_ms"),
            "dominant_stage": _dominant_stage(row),
            "grouping_ms": row.get("grouping_ms"),
            "root_cause_ms": row.get("root_cause_ms"),
            "runbook_ms": row.get("runbook_ms"),
            "approval_ms": row.get("approval_ms"),
            "fallback_used": row.get("fallback_used"),
            "analysis_method": row.get("analysis_method"),
            "policy_status": row.get("policy_status"),
        }
        for row in successful
        if float(row.get("latency_seconds", 0.0)) > spike_threshold
    ]
    slowest_runs = [
        {
            "run_index": row.get("run_index"),
            "scenario_id": row.get("scenario_id"),
            "scenario_title": row.get("scenario_title"),
            "latency_seconds": row.get("latency_seconds"),
            "pipeline_total_ms": row.get("pipeline_total_ms"),
            "dominant_stage": _dominant_stage(row),
            "top_cause_service": row.get("top_cause_service"),
            "policy_status": row.get("policy_status"),
        }
        for row in sorted(successful, key=lambda row: float(row.get("latency_seconds", 0.0)), reverse=True)[:5]
    ]

    scenario_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_results:
        scenario_id = str(row.get("scenario_id", "unknown"))
        scenario_groups[scenario_id].append(row)

    scenario_breakdown: list[dict[str, Any]] = []
    for scenario_id, rows in sorted(scenario_groups.items()):
        scenario_success = [row for row in rows if row.get("success")]
        scenario_truth = [row for row in scenario_success if row.get("top_cause_correct") is not None]
        scenario_sources = [
            row for row in scenario_success if row.get("runbook_expected_file_hit") is not None
        ]
        scenario_breakdown.append(
            {
                "scenario_id": scenario_id,
                "scenario_title": rows[0].get("scenario_title", scenario_id),
                "expected_top_cause": rows[0].get("expected_top_cause"),
                "runs": len(rows),
                "successful_runs": len(scenario_success),
                "fallback_rate": (
                    sum(1 for row in scenario_success if row.get("fallback_used")) / len(scenario_success)
                    if scenario_success
                    else 0.0
                ),
                "top1_accuracy": (
                    sum(1 for row in scenario_truth if row.get("top_cause_correct")) / len(scenario_truth)
                    if scenario_truth
                    else None
                ),
                "runbook_source_hit_rate": (
                    sum(1 for row in scenario_sources if row.get("runbook_expected_file_hit"))
                    / len(scenario_sources)
                    if scenario_sources
                    else None
                ),
                "mean_latency_seconds": _safe_mean(
                    [float(row.get("latency_seconds", 0.0)) for row in scenario_success]
                ),
                "top_causes": dict(
                    Counter(
                        str(row.get("top_cause_service"))
                        for row in scenario_success
                        if row.get("top_cause_service")
                    )
                ),
            }
        )

    summary = {
        "total_runs": len(raw_results),
        "successful_runs": len(successful),
        "failed_runs": len(failures),
        "overall_success_rate": len(successful) / len(raw_results) if raw_results else 0.0,
        "root_cause_top1_accuracy": len(correct_rows) / len(truth_rows) if truth_rows else None,
        "root_cause_top1_count": len(correct_rows),
        "root_cause_failures": [
            {
                "scenario_id": row.get("scenario_id"),
                "run_index": row.get("run_index"),
                "expected_top_cause": row.get("expected_top_cause"),
                "observed_top_cause": row.get("top_cause_service"),
            }
            for row in truth_rows
            if row.get("top_cause_correct") is False
        ],
        "grouping_fallback_rate": (
            sum(1 for row in successful if row.get("fallback_used")) / len(successful)
            if successful
            else 0.0
        ),
        "grouping_fallback_count": sum(1 for row in successful if row.get("fallback_used")),
        "grouping_llm_success_rate": (
            sum(1 for row in successful if not row.get("fallback_used")) / len(successful)
            if successful
            else 0.0
        ),
        "mean_grouping_confidence": _safe_mean(grouping_confidences),
        "grouping_confidence_distribution": grouping_confidences,
        "runbook_grounding_rate": (
            sum(1 for row in successful if row.get("runbook_grounded")) / len(successful)
            if successful
            else 0.0
        ),
        "runbook_correct_source_rate": (
            len(source_hit_rows) / len(source_truth_rows) if source_truth_rows else None
        ),
        "mean_runbook_confidence": _safe_mean(runbook_confidences),
        "runbook_confidence_distribution": runbook_confidences,
        "mean_root_cause_confidence": _safe_mean(root_cause_confidences),
        "root_cause_confidence_distribution": root_cause_confidences,
        "graph_only_rate": (
            sum(1 for row in successful if row.get("analysis_method") == "graph_only") / len(successful)
            if successful
            else 0.0
        ),
        "mean_latency_seconds": _safe_mean(latencies),
        "p50_latency_seconds": _percentile(latencies, 0.50),
        "p95_latency_seconds": _percentile(latencies, 0.95),
        "max_latency_seconds": max(latencies) if latencies else 0.0,
        "latency_distribution": latencies,
        "latency_spike_threshold_seconds": spike_threshold,
        "latency_spike_count": len(latency_spike_runs),
        "latency_spike_runs": latency_spike_runs,
        "slowest_runs": slowest_runs,
        "mean_pipeline_total_ms": _safe_mean(pipeline_totals_ms),
        "p95_pipeline_total_ms": _percentile(pipeline_totals_ms, 0.95),
        "pipeline_stage_means_ms": {
            "grouping": _safe_mean(grouping_stage_ms),
            "root_cause": _safe_mean(root_cause_stage_ms),
            "runbook": _safe_mean(runbook_stage_ms),
            "approval": _safe_mean(approval_stage_ms),
        },
        "pipeline_stage_p95_ms": {
            "grouping": _percentile(grouping_stage_ms, 0.95),
            "root_cause": _percentile(root_cause_stage_ms, 0.95),
            "runbook": _percentile(runbook_stage_ms, 0.95),
            "approval": _percentile(approval_stage_ms, 0.95),
        },
        "top_cause_distribution": [row.get("top_cause_service") for row in successful if row.get("top_cause_service")],
        "top_cause_counts": dict(top_cause_counter),
        "source_file_frequency": dict(source_counter),
        "policy_status_counts": dict(policy_status_counter),
        "risk_level_counts": dict(risk_level_counter),
        "reviewer_tier_counts": dict(reviewer_tier_counter),
        "scenario_breakdown": scenario_breakdown,
    }
    return summary


def write_results(
    raw_results: list[dict[str, Any]],
    summary: dict[str, Any],
    results_dir: str | Path,
) -> None:
    """Writes raw and summary benchmark results to disk in a dashboard-friendly JSON format."""

    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw_results.json").write_text(
        json.dumps(raw_results, indent=2),
        encoding="utf-8",
    )
    (directory / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
