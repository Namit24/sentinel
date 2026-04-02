from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from metrics import compute_metrics
from visualize import generate_charts

GROUND_TRUTH = {
    "top_cause": "db-primary",
    "expected_runbook_sources": ["db_latency.md"],
    "failure_scenario": "db_latency_cascade",
}


def _ensure_repo_root_on_path() -> None:
    """Adds repository root to sys.path so eval scripts can import backend modules reliably."""

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def parse_args() -> argparse.Namespace:
    """Parses CLI flags so evaluation runs can be configured for speed, target API, and output location."""

    parser = argparse.ArgumentParser(description="SentinelOps synthetic benchmark harness")
    parser.add_argument("--runs", type=int, default=20, help="Number of simulation runs")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000", help="FastAPI base URL")
    parser.add_argument("--output", type=str, default="eval/results", help="Output directory")
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=2.0,
        help="Delay between runs to reduce provider throttling and stabilize LLM-path measurements",
    )
    return parser.parse_args()


def _collect_run_result(run_index: int, total_runs: int, api_url: str, console: Console) -> dict[str, Any]:
    """Executes one synthetic ingest call and extracts benchmark fields while tolerating API failures."""

    from sentinelops.simulation.generator import generate_alerts, generate_incident_scenario

    logs = [entry.model_dump(mode="json") for entry in generate_incident_scenario()]
    alerts = [alert.model_dump(mode="json") for alert in generate_alerts()]

    started = time.perf_counter()
    base_record: dict[str, Any] = {
        "run_index": run_index,
        "success": False,
        "error": None,
        "incident_id": None,
        "fallback_used": None,
        "grouping_confidence": None,
        "top_cause_service": None,
        "root_cause_confidence": None,
        "analysis_method": None,
        "runbook_source_files": [],
        "runbook_grounded": None,
        "runbook_confidence": None,
        "latency_seconds": None,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{api_url.rstrip('/')}/api/v1/ingest",
                json={"logs": logs, "alerts": alerts},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        base_record["error"] = str(exc)
        base_record["latency_seconds"] = round(time.perf_counter() - started, 4)
        console.print(
            f"Run {run_index:02d}/{total_runs:02d} | top_cause=n/a ✗ | fallback=n/a | latency={base_record['latency_seconds']:.2f}s",
            style="red",
        )
        return base_record

    elapsed = round(time.perf_counter() - started, 4)
    group_data = payload.get("group_data") or {}
    groups = group_data.get("result") or []
    first_group = groups[0] if groups else {}

    root_cause = payload.get("root_cause_data") or {}
    candidates = root_cause.get("candidates") or []
    top_candidate = candidates[0] if candidates else {}

    runbook = payload.get("runbook_data") or {}

    top_service = top_candidate.get("service")
    correct = top_service == GROUND_TRUTH["top_cause"]

    base_record.update(
        {
            "success": True,
            "incident_id": payload.get("id"),
            "fallback_used": bool(group_data.get("fallback_used", False)),
            "grouping_confidence": float(first_group.get("confidence_score", group_data.get("confidence_score", 0.0))),
            "top_cause_service": top_service,
            "root_cause_confidence": float(top_candidate.get("combined_score", 0.0)),
            "analysis_method": root_cause.get("analysis_method"),
            "runbook_source_files": list(runbook.get("source_files") or []),
            "runbook_grounded": bool(runbook.get("grounded", False)),
            "runbook_confidence": float(runbook.get("confidence_score", 0.0)),
            "latency_seconds": elapsed,
        }
    )

    marker = "✓" if correct else "✗"
    marker_style = "green" if correct else "red"
    console.print(
        f"Run {run_index:02d}/{total_runs:02d} | top_cause={top_service} {marker} | "
        f"fallback={base_record['fallback_used']} | latency={elapsed:.2f}s",
        style=marker_style,
    )
    return base_record


def _build_summary_table(metrics: dict[str, Any]) -> Table:
    """Builds a rich summary table with key benchmark metrics for terminal reporting and quick sharing."""

    table = Table(title=f"SentinelOps AI — Eval Summary\nN={metrics['total_runs']} runs", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="magenta")

    table.add_row("Root Cause Top-1 Accuracy", f"{metrics['root_cause_top1_accuracy'] * 100:.1f}%")
    table.add_row("LLM Grouping Success Rate", f"{metrics['grouping_llm_success_rate'] * 100:.1f}%")
    table.add_row("Runbook Grounding Rate", f"{metrics['runbook_grounding_rate'] * 100:.1f}%")
    table.add_row("Correct Source Citation Rate", f"{metrics['runbook_correct_source_rate'] * 100:.1f}%")
    table.add_row("Mean Pipeline Latency", f"{metrics['mean_latency_seconds']:.2f}s")
    table.add_row("P95 Pipeline Latency", f"{metrics['p95_latency_seconds']:.2f}s")
    table.add_row("Graph+Vector Analysis Rate", f"{(1 - metrics['graph_only_rate']) * 100:.1f}%")
    table.add_row("Successful Runs", f"{metrics['successful_runs']}/{metrics['total_runs']}")
    return table


def main() -> None:
    """Runs the full synthetic benchmark pipeline, computes metrics, renders charts, and saves artifacts."""

    _ensure_repo_root_on_path()
    args = parse_args()
    console = Console()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []

    progress = Progress(
        TextColumn("[bold blue]Running eval"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    )

    with progress:
        task_id = progress.add_task("runs", total=args.runs)
        for run_number in range(1, args.runs + 1):
            result = _collect_run_result(run_number, args.runs, args.api_url, console)
            results.append(result)
            progress.advance(task_id, 1)
            if run_number < args.runs and args.delay_seconds > 0:
                time.sleep(args.delay_seconds)

    raw_path = output_dir / "raw_results.json"
    raw_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    metrics = compute_metrics(results, GROUND_TRUTH)

    run_records: list[dict[str, Any]] = []
    for row in results:
        if not row.get("success"):
            run_records.append(
                {
                    "run_index": row["run_index"],
                    "latency_seconds": float(row.get("latency_seconds") or 0.0),
                    "outcome": "failed",
                }
            )
            continue

        is_correct = row.get("top_cause_service") == GROUND_TRUTH["top_cause"]
        run_records.append(
            {
                "run_index": row["run_index"],
                "latency_seconds": float(row.get("latency_seconds") or 0.0),
                "outcome": "correct" if is_correct else "incorrect",
            }
        )

    metrics["run_records"] = run_records

    chart_paths = generate_charts(metrics, str(output_dir))

    summary_json = {key: value for key, value in metrics.items() if key != "run_records"}
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary_json, indent=2), encoding="utf-8")

    console.print()
    console.print(_build_summary_table(metrics))
    console.print()
    console.print(f"Raw results: {raw_path}")
    console.print(f"Summary: {summary_path}")
    console.print("Charts:")
    for chart in chart_paths:
        console.print(f"- {chart}")


if __name__ == "__main__":
    main()
