import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from api import run_ingest

st.title("Simulate Incident")
st.write("Triggers the synthetic DB latency cascade scenario and runs the full pipeline.")


if st.button("Run Simulation", type="primary"):
    try:
        repo_root = Path(__file__).resolve().parents[2]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from sentinelops.simulation.generator import generate_alerts, generate_incident_scenario

        logs = [entry.model_dump(mode="json") for entry in generate_incident_scenario()]
        alerts = [alert.model_dump(mode="json") for alert in generate_alerts()]
        result = run_ingest(logs, alerts)

        st.success(f"Simulation complete. Incident ID: {result['id']}")

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

            def _highlight_rank_one(row):
                """Highlights top-ranked row so operators can quickly identify primary hypothesis."""

                return ["background-color: #fff3cd" if row.get("rank") == 1 else "" for _ in row]

            if root_df.empty:
                st.info("No root-cause candidates available.")
            else:
                st.dataframe(root_df.style.apply(_highlight_rank_one, axis=1), use_container_width=True)

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
    except RuntimeError as exc:
        st.error(str(exc))
