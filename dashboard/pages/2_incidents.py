from datetime import datetime

import pandas as pd
import streamlit as st

from api import get_audit_trail, get_incident, get_incidents

st.title("All Incidents")


@st.cache_data(ttl=10)
def _cached_incidents() -> list:
    """Caches incident list to keep table interactions responsive while reducing repeated API calls."""

    return get_incidents()


def _fmt_time(value: str) -> str:
    """Formats ISO timestamps into concise operator-readable incident list values."""

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value


try:
    incidents = _cached_incidents()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

rows = []
for item in incidents:
    rows.append(
        {
            "id_full": item.get("id"),
            "ID": str(item.get("id") or "")[:8],
            "Created at": _fmt_time(str(item.get("created_at", ""))),
            "Status": item.get("status", ""),
            "Top cause service": item.get("top_cause_service") or "-",
            "Confidence score": f"{float(item.get('confidence_score', 0.0)) * 100:.1f}%",
            "Fallback used": "Yes" if item.get("fallback_used") else "No",
            "Policy status": item.get("policy_status") or "-",
            "Risk level": item.get("risk_level") or "-",
            "Affected services": ", ".join(item.get("affected_services", [])),
        }
    )

if rows:
    st.dataframe(
        pd.DataFrame(rows)[
            [
                "ID",
                "Created at",
                "Status",
                "Top cause service",
                "Confidence score",
                "Fallback used",
                "Policy status",
                "Risk level",
                "Affected services",
            ]
        ],
        use_container_width=True,
    )
else:
    st.info("No incidents found.")

incident_ids = [row["id_full"] for row in rows if row.get("id_full")]
selected = st.selectbox("Select an incident to inspect", options=incident_ids, index=None)

if selected:
    try:
        incident_detail = get_incident(selected)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    tab_summary, tab_root, tab_runbook, tab_audit = st.tabs(
        ["Summary", "Root Cause", "Runbook", "Audit Trail"]
    )

    with tab_summary:
        policy = incident_detail.get("policy_data") or {}
        pipeline = incident_detail.get("pipeline_metrics") or {}
        group_data = incident_detail.get("group_data") or {}

        sum1, sum2, sum3, sum4 = st.columns(4)
        sum1.metric("Top cause", incident_detail.get("top_cause_service") or "-")
        sum2.metric("Policy", policy.get("policy_status", "-"))
        sum3.metric("Risk", policy.get("risk_level", "-"))
        sum4.metric("Fallback", "Yes" if incident_detail.get("fallback_used") else "No")

        if policy:
            st.write("Policy reasons")
            for reason in policy.get("reasons") or []:
                st.markdown(f"- {reason}")
            flags = policy.get("control_flags") or []
            if flags:
                st.info("Control flags: " + " | ".join(flags))

        if pipeline:
            st.caption("Pipeline stage latency (ms)")
            st.bar_chart(
                pd.DataFrame(
                    [
                        {"stage": "grouping", "latency_ms": float(pipeline.get("grouping_ms", 0.0))},
                        {"stage": "root_cause", "latency_ms": float(pipeline.get("root_cause_ms", 0.0))},
                        {"stage": "runbook", "latency_ms": float(pipeline.get("runbook_ms", 0.0))},
                        {"stage": "approval", "latency_ms": float(pipeline.get("approval_ms", 0.0))},
                    ]
                ).set_index("stage"),
                use_container_width=True,
            )
            st.caption(
                f"Total pipeline time: {float(pipeline.get('total_ms', 0.0)):.1f}ms "
                f"| Analysis method: {pipeline.get('analysis_method', 'unknown')}"
            )

        fallback_reason = group_data.get("fallback_reason")
        if fallback_reason:
            st.warning(f"Fallback reason: {fallback_reason}")

    with tab_root:
        report = incident_detail.get("root_cause_data") or {}
        candidates = report.get("candidates") or []
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
        st.dataframe(root_df, use_container_width=True)
        if not root_df.empty:
            st.bar_chart(
                root_df.set_index("service")[
                    ["graph_score", "similarity_score", "combined_score"]
                ],
                use_container_width=True,
            )
        graph_path = report.get("graph_path") or []
        if graph_path:
            st.caption("Propagation path: " + " -> ".join(graph_path))

    with tab_runbook:
        runbook = incident_detail.get("runbook_data") or {}
        st.write(f"Top cause: **{runbook.get('top_cause', 'unknown')}**")
        st.write(f"Confidence: **{runbook.get('confidence_score', 0):.2f}**")
        for index, step in enumerate(runbook.get("steps") or [], start=1):
            st.markdown(f"{index}. {step}")
        sources = runbook.get("source_files") or []
        st.info("Sources: " + " | ".join(sources) if sources else "Sources: none")

    with tab_audit:
        try:
            events = get_audit_trail(selected)
            if not events:
                st.info("No audit events for this incident yet.")
            for event in events:
                with st.container(border=True):
                    st.markdown(f"**{event.get('event_type', 'UNKNOWN')}**")
                    st.caption(
                        f"Actor: {event.get('actor', 'unknown')} · {event.get('created_at', 'unknown time')}"
                    )
                    st.write(event.get("description", ""))
                    if event.get("payload") is not None:
                        with st.expander("Payload"):
                            st.json(event.get("payload"))
        except RuntimeError as exc:
            st.error(str(exc))
