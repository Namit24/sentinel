from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
import sys

import httpx

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from eval.metrics import summarize_results, write_results
from eval.plot_3d import generate_3d_plots
from sentinelops.simulation.generator import generate_named_scenario, list_scenarios


def _parse_args() -> argparse.Namespace:
    """Parses benchmark CLI arguments so evaluation can run against any local or remote API URL."""

    parser = argparse.ArgumentParser(description="Run SentinelOps multi-scenario benchmark harness.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="SentinelOps API base URL")
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Scenario id to evaluate. Repeat to include multiple scenarios. Defaults to all.",
    )
    parser.add_argument(
        "--runs-per-scenario",
        type=int,
        default=4,
        help="Number of runs to execute for each selected scenario.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.5,
        help="Delay inserted between benchmark runs to reduce API burstiness.",
    )
    parser.add_argument(
        "--results-dir",
        default="eval/results",
        help="Directory where raw_results.json and summary.json will be written.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="Per-request timeout budget for the ingest API.",
    )
    return parser.parse_args()


def _selected_scenarios(explicit: list[str]) -> list[str]:
    """Returns either caller-selected scenarios or the full catalog when none are specified."""

    if explicit:
        return explicit
    return [scenario.scenario_id for scenario in list_scenarios()]


def _result_row(
    *,
    scenario_id: str,
    scenario_title: str,
    expected_top_cause: str,
    expected_runbook_files: list[str],
    run_index: int,
    elapsed_seconds: float,
    response: dict,
) -> dict:
    """Extracts one normalized raw benchmark row from an ingest API response payload."""

    group_data = response.get("group_data") or {}
    root_cause = response.get("root_cause_data") or {}
    runbook = response.get("runbook_data") or {}
    pipeline = response.get("pipeline_metrics") or {}
    policy = response.get("policy_data") or {}
    top_cause = response.get("top_cause_service") or root_cause.get("top_cause")
    source_files = list(runbook.get("source_files") or [])

    return {
        "scenario_id": scenario_id,
        "scenario_title": scenario_title,
        "expected_top_cause": expected_top_cause,
        "run_index": run_index,
        "success": True,
        "error": None,
        "incident_id": response.get("id"),
        "fallback_used": bool(response.get("fallback_used")),
        "grouping_confidence": group_data.get("confidence_score", response.get("confidence_score")),
        "top_cause_service": top_cause,
        "top_cause_correct": top_cause == expected_top_cause if top_cause else None,
        "root_cause_confidence": root_cause.get("confidence_score"),
        "analysis_method": root_cause.get("analysis_method"),
        "fallback_reason": group_data.get("fallback_reason"),
        "runbook_source_files": source_files,
        "runbook_grounded": bool(runbook.get("grounded")),
        "runbook_confidence": runbook.get("confidence_score"),
        "runbook_expected_file_hit": any(item in source_files for item in expected_runbook_files),
        "policy_status": policy.get("policy_status"),
        "risk_level": policy.get("risk_level"),
        "reviewer_tier": policy.get("reviewer_tier"),
        "control_flags": list(policy.get("control_flags") or []),
        "grouping_ms": pipeline.get("grouping_ms"),
        "root_cause_ms": pipeline.get("root_cause_ms"),
        "runbook_ms": pipeline.get("runbook_ms"),
        "approval_ms": pipeline.get("approval_ms"),
        "pipeline_total_ms": pipeline.get("total_ms"),
        "log_count": pipeline.get("log_count"),
        "alert_count": pipeline.get("alert_count"),
        "approval_auto_escalated": bool((response.get("approval_request") or {}).get("auto_escalated")),
        "latency_seconds": round(elapsed_seconds, 4),
    }


def main() -> None:
    """Runs a multi-scenario API benchmark and writes normalized JSON outputs for dashboard consumption."""

    args = _parse_args()
    scenarios = _selected_scenarios(args.scenario)
    results: list[dict] = []
    scenario_catalog = {item.scenario_id: item for item in list_scenarios()}

    run_counter = 0
    with httpx.Client(timeout=args.timeout_seconds) as client:
        for scenario_id in scenarios:
            scenario = scenario_catalog[scenario_id]
            for scenario_run in range(1, args.runs_per_scenario + 1):
                run_counter += 1
                logs, alerts, definition = generate_named_scenario(
                    scenario_id=scenario_id,
                    seed=run_counter,
                )
                payload = {
                    "logs": [entry.model_dump(mode="json") for entry in logs],
                    "alerts": [alert.model_dump(mode="json") for alert in alerts],
                }

                started = time.perf_counter()
                try:
                    response = client.post(
                        f"{args.base_url.rstrip('/')}/api/v1/ingest",
                        json=payload,
                    )
                    response.raise_for_status()
                    elapsed = time.perf_counter() - started
                    results.append(
                        _result_row(
                            scenario_id=definition.scenario_id,
                            scenario_title=definition.title,
                            expected_top_cause=definition.expected_top_cause,
                            expected_runbook_files=list(definition.expected_runbook_files),
                            run_index=run_counter,
                            elapsed_seconds=elapsed,
                            response=response.json(),
                        )
                    )
                except Exception as exc:
                    elapsed = time.perf_counter() - started
                    results.append(
                        {
                            "scenario_id": scenario.scenario_id,
                            "scenario_title": scenario.title,
                            "expected_top_cause": scenario.expected_top_cause,
                            "run_index": run_counter,
                            "success": False,
                            "error": str(exc),
                            "incident_id": None,
                            "fallback_used": None,
                            "grouping_confidence": None,
                            "top_cause_service": None,
                            "top_cause_correct": None,
                            "root_cause_confidence": None,
                            "analysis_method": None,
                            "fallback_reason": None,
                            "runbook_source_files": [],
                            "runbook_grounded": False,
                            "runbook_confidence": None,
                            "runbook_expected_file_hit": None,
                            "policy_status": None,
                            "risk_level": None,
                            "reviewer_tier": None,
                            "control_flags": [],
                            "grouping_ms": None,
                            "root_cause_ms": None,
                            "runbook_ms": None,
                            "approval_ms": None,
                            "pipeline_total_ms": None,
                            "log_count": None,
                            "alert_count": None,
                            "approval_auto_escalated": None,
                            "latency_seconds": round(elapsed, 4),
                        }
                    )

                if args.delay_seconds > 0:
                    time.sleep(args.delay_seconds)

    summary = summarize_results(results)
    write_results(results, summary, args.results_dir)
    try:
        generate_3d_plots(args.results_dir)
    except Exception as exc:
        print(f"warning: failed to generate 3D plots: {exc}", file=sys.stderr)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
