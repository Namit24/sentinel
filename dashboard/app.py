import streamlit as st
import pandas as pd

from api import check_health_detailed, get_incidents, get_pending_approvals

st.set_page_config(page_title="SentinelOps Operator Dashboard", page_icon="🛡️", layout="wide")


@st.cache_data(ttl=10)
def _cached_incidents() -> list:
    """Caches incident list briefly to reduce API load during frequent Streamlit rerenders."""

    return get_incidents()


@st.cache_data(ttl=10)
def _cached_pending() -> list:
    """Caches pending approvals briefly so queue metrics remain responsive without API hammering."""

    return get_pending_approvals()


st.title("SentinelOps AI")
st.write("Operator console for incident triage, runbook review, and human approval decisions.")

health = None
connected = False
try:
    health = check_health_detailed()
    connected = True
except RuntimeError as exc:
    st.error(str(exc))

if connected:
    st.success("API Status: Connected")
else:
    st.error("API Status: Unreachable")

col1, col2, col3, col4 = st.columns(4)
if connected:
    try:
        incidents = _cached_incidents()
        pending = _cached_pending()
        confidence_values = [float(item.get("confidence_score", 0.0)) for item in incidents]
        mean_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        fallback_count = sum(1 for item in incidents if item.get("fallback_used"))
        open_breakers = int(health.get("open_breakers", 0))
        with col1:
            st.metric("Total incidents", len(incidents))
        with col2:
            st.metric("Pending approvals", len(pending))
        with col3:
            st.metric("Mean confidence", f"{mean_confidence * 100:.1f}%")
        with col4:
            st.metric("Fallback runs", fallback_count, delta=f"Open breakers: {open_breakers}")

        ops1, ops2 = st.columns(2)
        with ops1:
            st.metric("Indexed runbook chunks", int(health.get("runbook_chunks", 0)))
        with ops2:
            st.metric("Database", str((health.get("database") or {}).get("status", "unknown")).upper())

        top_cause_counts: dict[str, int] = {}
        for item in incidents:
            top_cause = item.get("top_cause_service")
            if not top_cause:
                continue
            top_cause_counts[top_cause] = top_cause_counts.get(top_cause, 0) + 1
        if top_cause_counts:
            st.caption("Observed top-cause distribution")
            st.bar_chart(
                pd.DataFrame(
                    [{"service": key, "count": value} for key, value in top_cause_counts.items()]
                ).set_index("service"),
                use_container_width=True,
            )

        breakers = health.get("llm_breakers") or {}
        if breakers:
            st.caption("LLM guard status")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "component": name,
                            "open": bool(snapshot.get("open")),
                            "open_for_seconds": float(snapshot.get("open_for_seconds", 0.0)),
                            "last_error": snapshot.get("last_error") or "-",
                        }
                        for name, snapshot in breakers.items()
                    ]
                ),
                use_container_width=True,
            )

        st.caption(f"API environment: `{health.get('environment', 'unknown')}`")
    except RuntimeError as exc:
        st.error(str(exc))
        with col1:
            st.metric("Total incidents", "-")
        with col2:
            st.metric("Pending approvals", "-")
        with col3:
            st.metric("Mean confidence", "-")
        with col4:
            st.metric("Fallback runs", "-")
        st.caption(f"API environment: `{health.get('environment', 'unknown')}`")
else:
    with col1:
        st.metric("Total incidents", "-")
    with col2:
        st.metric("Pending approvals", "-")
    with col3:
        st.metric("Mean confidence", "-")
    with col4:
        st.metric("Fallback runs", "-")
    st.caption("API environment: `-`")

st.info("Use the sidebar to navigate.")
