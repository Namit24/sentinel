import streamlit as st

from api import check_health, get_incidents, get_pending_approvals

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
    health = check_health()
    connected = True
except RuntimeError as exc:
    st.error(str(exc))

if connected:
    st.success("API Status: Connected")
else:
    st.error("API Status: Unreachable")

col1, col2, col3 = st.columns(3)
if connected:
    try:
        incidents = _cached_incidents()
        pending = _cached_pending()
        with col1:
            st.metric("Total incidents", len(incidents))
        with col2:
            st.metric("Pending approvals", len(pending))
        with col3:
            st.metric("API environment", str(health.get("environment", "unknown")))
    except RuntimeError as exc:
        st.error(str(exc))
        with col1:
            st.metric("Total incidents", "-")
        with col2:
            st.metric("Pending approvals", "-")
        with col3:
            st.metric("API environment", str(health.get("environment", "unknown")))
else:
    with col1:
        st.metric("Total incidents", "-")
    with col2:
        st.metric("Pending approvals", "-")
    with col3:
        st.metric("API environment", "-")

st.info("Use the sidebar to navigate.")
