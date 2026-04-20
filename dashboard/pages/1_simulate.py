import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from api import index_runbooks, run_ingest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sentinelops.simulation.generator import generate_named_scenario, list_scenarios


def _render_result(result: dict, expected_top_cause: str) -> None:
    """Renders one enriched incident response so scenario validation is easy to inspect visually."""

    actual_top_cause = result.get("top_cause_service") or ((result.get("root_cause_data") or {}).get("top_cause"))
    if actual_top_cause == expected_top_cause:
        st.success(f"Top cause matched expectation: `{actual_top_cause}`")
    else:
        st.warning(f"Expected top cause `{expected_top_cause}`, observed `{actual_top_cause or 'unknown'}`")

    with st.expander("Grouping Result", expanded=True):
        groups = (result.get("group_data") or {}).get("result") or []
        table_data = [
            {
                "group_id": row.get("group_id"),
                "likely_cause": row.get("likely_cause"),
                "affected_services": ", ".join(row.get("affected_services", [])),
                "confidence_score": row.get("confidence_score"),
            }
            for row in groups
        ]
        st.dataframe(pd.DataFrame(table_data), use_container_width=True)

    with st.expander("Root Cause Ranking", expanded=True):
        candidates = (result.get("root_cause_data") or {}).get("candidates") or []
        root_df = pd.DataFrame(
            [
                {
                    "rank": row.get("rank"),
                    "service": row.get("service"),
                    "graph_score": row.get("graph_score"),
                    "similarity_score": row.get("similarity_score"),
                    "combined_score": row.get("combined_score"),
                }
                for row in candidates
            ]
        )
        if root_df.empty:
            st.info("No root-cause candidates available.")
        else:
            st.dataframe(root_df, use_container_width=True)
            chart_df = root_df.set_index("service")[["graph_score", "similarity_score", "combined_score"]]
            st.bar_chart(chart_df, use_container_width=True)

    with st.expander("Runbook Recommendation", expanded=True):
        runbook = result.get("runbook_data") or {}
        st.write(f"Top cause: **{runbook.get('top_cause', 'unknown')}**")
        st.write(f"Confidence: **{runbook.get('confidence_score', 0):.2f}**")
        for index, step in enumerate(runbook.get("steps") or [], start=1):
            st.markdown(f"{index}. {step}")

        sources = runbook.get("source_files") or []
        if sources:
            st.info("Sources: " + " | ".join(sources))
        else:
            st.info("No source files available.")

    with st.expander("Policy Controls", expanded=True):
        policy = result.get("policy_data") or {}
        if not policy:
            st.info("No policy decision attached to this incident.")
        else:
            status = policy.get("policy_status", "UNKNOWN")
            if status == "BLOCKED":
                st.error(f"Policy status: {status}")
            elif status in {"ESCALATE_REQUIRED", "RESTRICTED_REVIEW"}:
                st.warning(f"Policy status: {status}")
            else:
                st.success(f"Policy status: {status}")

            pol1, pol2, pol3 = st.columns(3)
            pol1.metric("Risk level", str(policy.get("risk_level", "unknown")).upper())
            pol2.metric("Reviewer tier", str(policy.get("reviewer_tier", "unknown")))
            pol3.metric("Policy confidence", f"{float(policy.get('confidence_score', 0.0)) * 100:.1f}%")

            reasons = policy.get("reasons") or []
            if reasons:
                st.write("Reasons")
                for reason in reasons:
                    st.markdown(f"- {reason}")

            flags = policy.get("control_flags") or []
            if flags:
                st.info("Control flags: " + " | ".join(flags))

    with st.expander("Pipeline Metrics", expanded=True):
        metrics = result.get("pipeline_metrics") or {}
        if not metrics:
            st.info("No pipeline timing metrics available.")
        else:
            met1, met2, met3, met4, met5 = st.columns(5)
            met1.metric("Grouping", f"{float(metrics.get('grouping_ms', 0.0)):.1f}ms")
            met2.metric("Root cause", f"{float(metrics.get('root_cause_ms', 0.0)):.1f}ms")
            met3.metric("Runbook", f"{float(metrics.get('runbook_ms', 0.0)):.1f}ms")
            met4.metric("Approval", f"{float(metrics.get('approval_ms', 0.0)):.1f}ms")
            met5.metric("Total", f"{float(metrics.get('total_ms', 0.0)):.1f}ms")

            stage_df = pd.DataFrame(
                [
                    {"stage": "grouping", "latency_ms": float(metrics.get("grouping_ms", 0.0))},
                    {"stage": "root_cause", "latency_ms": float(metrics.get("root_cause_ms", 0.0))},
                    {"stage": "runbook", "latency_ms": float(metrics.get("runbook_ms", 0.0))},
                    {"stage": "approval", "latency_ms": float(metrics.get("approval_ms", 0.0))},
                ]
            )
            st.bar_chart(stage_df.set_index("stage"), use_container_width=True)
            st.caption(
                "Analysis method: "
                f"`{metrics.get('analysis_method', 'unknown')}` | "
                f"Fallback used: `{metrics.get('fallback_used', False)}` | "
                f"Grounded runbook: `{metrics.get('runbook_grounded', False)}`"
            )

    with st.expander("Approval Request", expanded=True):
        approval = result.get("approval_request") or {}
        status = approval.get("status", "UNKNOWN")
        if status == "PENDING":
            st.warning("Status: PENDING")
        else:
            st.info(f"Status: {status}")

        st.write(approval.get("recommendation_summary", "No summary available."))
        confidence = float(approval.get("confidence_score", 0.0))
        st.progress(min(max(confidence, 0.0), 1.0), text=f"Confidence {confidence:.2f}")

        if approval.get("auto_escalated"):
            st.error(f"Auto-escalated: {approval.get('escalation_reason') or 'Low confidence'}")


st.title("Scenario Lab")
st.write("Run synthetic incidents across multiple failure families and inspect how the full pipeline responds.")

scenario_catalog = {item.scenario_id: item for item in list_scenarios()}
scenario_ids = list(scenario_catalog)

selected_scenario = st.selectbox(
    "Scenario",
    options=scenario_ids,
    format_func=lambda value: scenario_catalog[value].title,
)
scenario = scenario_catalog[selected_scenario]
seed = st.number_input(
    "Scenario seed",
    min_value=0,
    value=1,
    help="Change the seed to vary timestamps, alert ids, and noise while keeping the same scenario family.",
)

st.caption(scenario.description)
st.markdown(
    f"**Expected top cause:** `{scenario.expected_top_cause}`  \n"
    f"**Affected services:** `{', '.join(scenario.affected_services)}`  \n"
    f"**Expected runbooks:** `{', '.join(scenario.expected_runbook_files)}`"
)

left, right = st.columns([3, 1])
with left:
    run_clicked = st.button("Run Selected Scenario", type="primary", use_container_width=True)
with right:
    reindex_clicked = st.button("Index Runbooks", use_container_width=True)

if reindex_clicked:
    try:
        response = index_runbooks()
        st.success(f"Runbook indexing complete. Chunks indexed: {response.get('chunks_indexed', '?')}")
    except RuntimeError as exc:
        st.error(str(exc))

if run_clicked:
    try:
        logs, alerts, definition = generate_named_scenario(selected_scenario, seed=int(seed))
        result = run_ingest(
            [entry.model_dump(mode="json") for entry in logs],
            [alert.model_dump(mode="json") for alert in alerts],
        )
        st.session_state["last_simulation"] = {
            "scenario_id": definition.scenario_id,
            "scenario_title": definition.title,
            "expected_top_cause": definition.expected_top_cause,
            "result": result,
        }
        st.success(f"Simulation complete. Incident ID: {result['id']}")
    except RuntimeError as exc:
        st.error(str(exc))

last = st.session_state.get("last_simulation")
if last:
    if last.get("scenario_id") != selected_scenario:
        st.info(
            "Showing the last executed result from "
            f"`{last.get('scenario_title', last.get('scenario_id', 'unknown'))}`."
        )
    _render_result(last["result"], last.get("expected_top_cause", "unknown"))
