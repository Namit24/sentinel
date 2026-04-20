import json
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st

from api import index_runbooks, run_ingest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.metrics import summarize_results, write_results
from sentinelops.simulation.generator import generate_named_scenario, list_scenarios

RESULTS_DIR = REPO_ROOT / "eval" / "results"


def _discover_pngs(results_dir: Path) -> list[Path]:
    """Finds committed evaluation images recursively so new benchmark artifacts appear automatically."""

    return sorted(results_dir.rglob("*.png"))


def _load_json(path: Path) -> dict | list | None:
    """Loads one JSON artifact from disk when present and returns None when absent or invalid."""

    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _top_cause_counts(summary: dict, raw_results: list[dict]) -> dict[str, int]:
    """Returns stable top-cause frequency counts even when summary format differs across result versions."""

    counts = summary.get("top_cause_counts")
    if isinstance(counts, dict) and counts:
        return {str(key): int(value) for key, value in counts.items()}
    return dict(
        Counter(
            str(row.get("top_cause_service"))
            for row in raw_results
            if row.get("success") and row.get("top_cause_service")
        )
    )


def _render_summary(summary: dict, raw_results: list[dict], heading: str) -> None:
    """Renders benchmark metrics, charts, and raw result tables for either committed or live runs."""

    st.subheader(heading)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total runs", int(summary.get("total_runs", 0)))
    col2.metric("Success rate", f"{float(summary.get('overall_success_rate', 0.0)) * 100:.1f}%")
    accuracy = summary.get("root_cause_top1_accuracy")
    col3.metric("Top-1 accuracy", "-" if accuracy is None else f"{float(accuracy) * 100:.1f}%")
    col4.metric("Fallback rate", f"{float(summary.get('grouping_fallback_rate', 0.0)) * 100:.1f}%")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Mean latency", f"{float(summary.get('mean_latency_seconds', 0.0)):.2f}s")
    col6.metric("P95 latency", f"{float(summary.get('p95_latency_seconds', 0.0)):.2f}s")
    col7.metric(
        "Grounded runbooks",
        f"{float(summary.get('runbook_grounding_rate', 0.0)) * 100:.1f}%",
    )
    col8.metric("Spike runs", int(summary.get("latency_spike_count", 0)))

    col9, col10, col11, col12 = st.columns(4)
    col9.metric("Mean pipeline total", f"{float(summary.get('mean_pipeline_total_ms', 0.0)):.1f}ms")
    col10.metric("P95 pipeline total", f"{float(summary.get('p95_pipeline_total_ms', 0.0)):.1f}ms")
    source_rate = summary.get("runbook_correct_source_rate")
    col11.metric(
        "Expected source hit",
        "-" if source_rate is None else f"{float(source_rate) * 100:.1f}%",
    )
    col12.metric(
        "Graph-only rate",
        f"{float(summary.get('graph_only_rate', 0.0)) * 100:.1f}%",
    )

    if raw_results:
        latency_rows = [
            {
                "run_index": int(row.get("run_index", index + 1)),
                "latency_seconds": float(row.get("latency_seconds", 0.0)),
            }
            for index, row in enumerate(raw_results)
            if row.get("latency_seconds") is not None
        ]
        if latency_rows:
            st.caption("Latency by run")
            st.line_chart(
                pd.DataFrame(latency_rows).set_index("run_index"),
                use_container_width=True,
            )

        confidence_rows = [
            {
                "run_index": int(row.get("run_index", index + 1)),
                "grouping_confidence": float(row.get("grouping_confidence", 0.0))
                if row.get("grouping_confidence") is not None
                else 0.0,
                "root_cause_confidence": float(row.get("root_cause_confidence", 0.0))
                if row.get("root_cause_confidence") is not None
                else 0.0,
                "runbook_confidence": float(row.get("runbook_confidence", 0.0))
                if row.get("runbook_confidence") is not None
                else 0.0,
            }
            for index, row in enumerate(raw_results)
            if row.get("success")
        ]
        if confidence_rows:
            st.caption("Confidence traces")
            st.line_chart(
                pd.DataFrame(confidence_rows).set_index("run_index"),
                use_container_width=True,
            )

        stage_rows = [
            {
                "run_index": int(row.get("run_index", index + 1)),
                "grouping_ms": float(row.get("grouping_ms", 0.0)) if row.get("grouping_ms") is not None else 0.0,
                "root_cause_ms": float(row.get("root_cause_ms", 0.0))
                if row.get("root_cause_ms") is not None
                else 0.0,
                "runbook_ms": float(row.get("runbook_ms", 0.0)) if row.get("runbook_ms") is not None else 0.0,
                "approval_ms": float(row.get("approval_ms", 0.0)) if row.get("approval_ms") is not None else 0.0,
                "pipeline_total_ms": float(row.get("pipeline_total_ms", 0.0))
                if row.get("pipeline_total_ms") is not None
                else 0.0,
            }
            for index, row in enumerate(raw_results)
            if row.get("success") and row.get("pipeline_total_ms") is not None
        ]
        if stage_rows:
            st.caption("Pipeline stage latency (ms)")
            st.line_chart(
                pd.DataFrame(stage_rows).set_index("run_index"),
                use_container_width=True,
            )

    top_cause_counts = _top_cause_counts(summary, raw_results)
    if top_cause_counts:
        st.caption("Top-cause distribution")
        st.bar_chart(
            pd.DataFrame(
                [{"service": key, "count": value} for key, value in top_cause_counts.items()]
            ).set_index("service"),
            use_container_width=True,
        )

    source_frequency = summary.get("source_file_frequency") or {}
    if source_frequency:
        st.caption("Runbook source frequency")
        st.bar_chart(
            pd.DataFrame(
                [{"source_file": key, "count": value} for key, value in source_frequency.items()]
            ).set_index("source_file"),
            use_container_width=True,
        )

    policy_status_counts = summary.get("policy_status_counts") or {}
    if policy_status_counts:
        st.caption("Policy status distribution")
        st.bar_chart(
            pd.DataFrame(
                [{"policy_status": key, "count": value} for key, value in policy_status_counts.items()]
            ).set_index("policy_status"),
            use_container_width=True,
        )

    risk_level_counts = summary.get("risk_level_counts") or {}
    if risk_level_counts:
        st.caption("Risk level distribution")
        st.bar_chart(
            pd.DataFrame(
                [{"risk_level": key, "count": value} for key, value in risk_level_counts.items()]
            ).set_index("risk_level"),
            use_container_width=True,
        )

    scenario_breakdown = summary.get("scenario_breakdown") or []
    if scenario_breakdown:
        st.caption("Scenario breakdown")
        st.dataframe(pd.DataFrame(scenario_breakdown), use_container_width=True)

    spike_runs = summary.get("latency_spike_runs") or []
    if spike_runs:
        threshold = float(summary.get("latency_spike_threshold_seconds", 0.0))
        st.caption(f"Latency spike diagnostics (> {threshold:.2f}s)")
        st.dataframe(pd.DataFrame(spike_runs), use_container_width=True)

    slowest_runs = summary.get("slowest_runs") or []
    if slowest_runs:
        st.caption("Slowest runs")
        st.dataframe(pd.DataFrame(slowest_runs), use_container_width=True)

    if raw_results:
        st.caption("Raw runs")
        st.dataframe(pd.DataFrame(raw_results), use_container_width=True)


def _benchmark_row(
    *,
    scenario_id: str,
    scenario_title: str,
    expected_top_cause: str,
    expected_runbook_files: tuple[str, ...],
    run_index: int,
    elapsed_seconds: float,
    response: dict,
) -> dict:
    """Normalizes one live benchmark run so Streamlit and CLI evaluation share the same schema."""

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


st.title("Benchmark & Evaluation")
st.write("Inspect committed benchmark artifacts or run a fresh multi-scenario benchmark directly from Streamlit.")

committed_summary = _load_json(RESULTS_DIR / "summary.json")
committed_raw = _load_json(RESULTS_DIR / "raw_results.json")
if isinstance(committed_summary, dict) and isinstance(committed_raw, list):
    _render_summary(committed_summary, committed_raw, "Committed Results")
else:
    st.info("No committed evaluation JSON found in `eval/results` yet.")

available_pngs = _discover_pngs(RESULTS_DIR)
if available_pngs:
    with st.expander("Committed Graph Images"):
        for image_path in available_pngs:
            st.image(str(image_path), caption=image_path.name, use_container_width=True)

st.divider()
st.subheader("Live Benchmark")
scenario_catalog = {item.scenario_id: item for item in list_scenarios()}
selected_scenarios = st.multiselect(
    "Scenario coverage",
    options=list(scenario_catalog),
    default=list(scenario_catalog),
    format_func=lambda value: scenario_catalog[value].title,
)
runs_per_scenario = st.number_input("Runs per scenario", min_value=1, max_value=10, value=2)
delay_seconds = st.slider("Delay between runs (seconds)", min_value=0.0, max_value=3.0, value=0.2, step=0.1)
persist_results = st.checkbox("Persist live results to eval/results", value=False)
reindex_before_run = st.checkbox("Re-index runbooks before benchmark", value=False)

if st.button("Run Live Benchmark", type="primary", use_container_width=True):
    if not selected_scenarios:
        st.warning("Select at least one scenario.")
    else:
        try:
            if reindex_before_run:
                response = index_runbooks()
                st.info(f"Runbook index refreshed. Chunks indexed: {response.get('chunks_indexed', '?')}")

            progress = st.progress(0.0, text="Starting benchmark")
            total_runs = len(selected_scenarios) * int(runs_per_scenario)
            completed = 0
            raw_results: list[dict] = []

            for scenario_id in selected_scenarios:
                definition = scenario_catalog[scenario_id]
                for scenario_run in range(1, int(runs_per_scenario) + 1):
                    completed += 1
                    progress.progress(
                        completed / total_runs,
                        text=f"Running {definition.title} ({scenario_run}/{int(runs_per_scenario)})",
                    )
                    logs, alerts, scenario = generate_named_scenario(
                        scenario_id=scenario_id,
                        seed=completed,
                    )
                    started = time.perf_counter()
                    try:
                        response = run_ingest(
                            [entry.model_dump(mode="json") for entry in logs],
                            [alert.model_dump(mode="json") for alert in alerts],
                        )
                        elapsed = time.perf_counter() - started
                        raw_results.append(
                            _benchmark_row(
                                scenario_id=scenario.scenario_id,
                                scenario_title=scenario.title,
                                expected_top_cause=scenario.expected_top_cause,
                                expected_runbook_files=scenario.expected_runbook_files,
                                run_index=completed,
                                elapsed_seconds=elapsed,
                                response=response,
                            )
                        )
                    except RuntimeError as exc:
                        elapsed = time.perf_counter() - started
                        raw_results.append(
                            {
                                "scenario_id": scenario.scenario_id,
                                "scenario_title": scenario.title,
                                "expected_top_cause": scenario.expected_top_cause,
                                "run_index": completed,
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

                    if delay_seconds > 0:
                        time.sleep(float(delay_seconds))

            summary = summarize_results(raw_results)
            st.session_state["live_benchmark"] = {
                "summary": summary,
                "raw_results": raw_results,
            }
            progress.progress(1.0, text="Benchmark complete")

            if persist_results:
                write_results(raw_results, summary, RESULTS_DIR)
                st.success("Live benchmark results written to `eval/results`.")
        except RuntimeError as exc:
            st.error(str(exc))

live = st.session_state.get("live_benchmark")
if isinstance(live, dict):
    _render_summary(live.get("summary") or {}, live.get("raw_results") or [], "Live Benchmark Results")
