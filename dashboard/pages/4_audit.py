from datetime import datetime

import streamlit as st

from api import get_audit_trail, get_incidents

st.title("Audit Trail")


@st.cache_data(ttl=10)
def _cached_incidents() -> list:
    """Caches incidents for selectbox population to minimize repeated list requests on rerender."""

    return get_incidents()


def _event_color(event_type: str) -> str:
    """Maps event type to dashboard color tokens so high-signal decision events stand out visually."""

    if event_type == "APPROVAL_GRANTED":
        return "green"
    if event_type in {"APPROVAL_REJECTED", "FALLBACK_USED"}:
        return "red"
    if event_type == "ESCALATION_TRIGGERED":
        return "orange"
    return "blue"


def _parse_time(value: str) -> datetime | None:
    """Parses ISO timestamps safely so resolution-time metrics can be computed without crashes."""

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


try:
    incidents = _cached_incidents()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

incident_ids = [item.get("id") for item in incidents if item.get("id")]
selected = st.selectbox("Incident", options=incident_ids, index=None)

if selected:
    try:
        events = get_audit_trail(selected)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    for event in events:
        color = _event_color(event.get("event_type", ""))
        with st.container(border=True):
            left, right = st.columns([1, 5])
            with left:
                st.markdown(
                    f"<span style='color:{color}; font-weight:700'>{event.get('event_type', 'UNKNOWN')}</span>",
                    unsafe_allow_html=True,
                )
            with right:
                st.write(
                    f"{event.get('actor', 'unknown')} · {event.get('created_at', 'unknown time')}"
                )
                st.write(event.get("description", ""))
            if event.get("payload") is not None:
                with st.expander("Payload"):
                    st.json(event.get("payload"))

    total_events = len(events)
    fallback_count = sum(1 for event in events if event.get("event_type") == "FALLBACK_USED")

    created_event = next((event for event in events if event.get("event_type") == "INCIDENT_CREATED"), None)
    first_time = _parse_time(created_event.get("created_at")) if created_event else None
    last_time = _parse_time(events[-1].get("created_at")) if events else None
    if first_time and last_time:
        duration = str(last_time - first_time)
    else:
        duration = "N/A"

    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total events", total_events)
    col2.metric("Fallbacks used", fallback_count)
    col3.metric("Observed timeline", duration)
    st.caption("Observed timeline measures the first-to-last recorded audit event, not incident closure SLA.")
