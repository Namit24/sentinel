from datetime import datetime

import pandas as pd
import streamlit as st

from api import get_audit_trail, get_incident, get_incidents, get_root_cause, get_runbook

st.title("All Incidents")


@st.cache_data(ttl=10)
def _cached_incidents() -> list:
    """Caches incident list to keep table interactions responsive while reducing repeated API calls."""

    return get_incidents()


@st.cache_data(ttl=10)
def _cached_incident_detail(incident_id: str) -> dict:
    """Caches per-incident detail lookups so table enrichment does not repeatedly call the same endpoint."""

    return get_incident(incident_id)


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
    incident_id = item.get("id")
    top_cause = item.get("top_cause_service")
    if incident_id and not top_cause:
        try:
            details = _cached_incident_detail(str(incident_id))
            top_cause = details.get("top_cause_service")
        except RuntimeError:
            top_cause = "-"

    rows.append(
        {
            "id_full": incident_id,
            "ID": str(incident_id or "")[:8],
            "Created at": _fmt_time(str(item.get("created_at", ""))),
            "Status": item.get("status", ""),
            "Top cause service": top_cause or "-",
            "Confidence score": f"{float(item.get('confidence_score', 0.0)) * 100:.1f}%",
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
    tab_root, tab_runbook, tab_audit = st.tabs(["Root Cause", "Runbook", "Audit Trail"])

    with tab_root:
        try:
            report = get_root_cause(selected)
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
        except RuntimeError as exc:
            st.error(str(exc))

    with tab_runbook:
        try:
            runbook = get_runbook(selected)
            st.write(f"Top cause: **{runbook.get('top_cause', 'unknown')}**")
            st.write(f"Confidence: **{runbook.get('confidence_score', 0):.2f}**")
            for index, step in enumerate(runbook.get("steps") or [], start=1):
                st.markdown(f"{index}. {step}")
            sources = runbook.get("source_files") or []
            st.info("Sources: " + " | ".join(sources) if sources else "Sources: none")
        except RuntimeError as exc:
            st.error(str(exc))

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
