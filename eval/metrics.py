from __future__ import annotations

from typing import Any

import numpy as np


def _safe_mean(values: list[float]) -> float:
    """Returns a numeric mean for non-empty lists and 0.0 otherwise so metrics remain stable."""

    if not values:
        return 0.0
    return float(np.mean(values))


def _safe_percentile(values: list[float], percentile: int) -> float:
    """Returns a percentile for non-empty lists and 0.0 otherwise to avoid evaluation crashes."""

    if not values:
        return 0.0
    return float(np.percentile(values, percentile))


def compute_metrics(results: list[dict[str, Any]], ground_truth: dict[str, Any]) -> dict[str, Any]:
    """Computes benchmark metrics from per-run results against fixed synthetic scenario ground truth."""

    total_runs = len(results)
    successful_runs = [row for row in results if row.get("success")]
    failed_runs = [row for row in results if not row.get("success")]

    expected_top_cause = ground_truth["top_cause"]
    expected_sources = set(ground_truth["expected_runbook_sources"])

    top_causes = [row.get("top_cause_service") for row in successful_runs]
    top1_correct_rows = [row for row in successful_runs if row.get("top_cause_service") == expected_top_cause]
    incorrect_rows = [row for row in successful_runs if row.get("top_cause_service") != expected_top_cause]

    fallback_rows = [row for row in successful_runs if row.get("fallback_used")]
    grouping_confidence = [float(row.get("grouping_confidence", 0.0)) for row in successful_runs]

    grounded_rows = [row for row in successful_runs if bool(row.get("runbook_grounded"))]
    source_correct_rows = [
        row
        for row in successful_runs
        if expected_sources.issubset(set(row.get("runbook_source_files") or []))
    ]
    runbook_confidence = [float(row.get("runbook_confidence", 0.0)) for row in successful_runs]

    root_cause_confidence = [float(row.get("root_cause_confidence", 0.0)) for row in successful_runs]
    graph_only_rows = [row for row in successful_runs if row.get("analysis_method") == "graph_only"]

    latencies = [float(row.get("latency_seconds", 0.0)) for row in successful_runs]

    root_cause_failures = sorted(
        {str(row.get("top_cause_service", "unknown")) for row in incorrect_rows if row.get("top_cause_service")}
    )

    successful_count = len(successful_runs)
    failed_count = len(failed_runs)

    quality_denominator = successful_count if successful_count else 1

    return {
        "root_cause_top1_accuracy": float(len(top1_correct_rows) / quality_denominator)
        if successful_count
        else 0.0,
        "root_cause_top1_count": len(top1_correct_rows),
        "root_cause_failures": root_cause_failures,
        "grouping_fallback_rate": float(len(fallback_rows) / quality_denominator)
        if successful_count
        else 0.0,
        "grouping_fallback_count": len(fallback_rows),
        "grouping_llm_success_rate": float((successful_count - len(fallback_rows)) / quality_denominator)
        if successful_count
        else 0.0,
        "mean_grouping_confidence": _safe_mean(grouping_confidence),
        "grouping_confidence_distribution": grouping_confidence,
        "runbook_grounding_rate": float(len(grounded_rows) / quality_denominator)
        if successful_count
        else 0.0,
        "runbook_correct_source_rate": float(len(source_correct_rows) / quality_denominator)
        if successful_count
        else 0.0,
        "mean_runbook_confidence": _safe_mean(runbook_confidence),
        "runbook_confidence_distribution": runbook_confidence,
        "mean_root_cause_confidence": _safe_mean(root_cause_confidence),
        "root_cause_confidence_distribution": root_cause_confidence,
        "graph_only_rate": float(len(graph_only_rows) / quality_denominator)
        if successful_count
        else 0.0,
        "mean_latency_seconds": _safe_mean(latencies),
        "p50_latency_seconds": _safe_percentile(latencies, 50),
        "p95_latency_seconds": _safe_percentile(latencies, 95),
        "max_latency_seconds": float(max(latencies)) if latencies else 0.0,
        "latency_distribution": latencies,
        "total_runs": total_runs,
        "successful_runs": successful_count,
        "failed_runs": failed_count,
        "overall_success_rate": float(successful_count / total_runs) if total_runs else 0.0,
        "top_cause_distribution": top_causes,
    }
