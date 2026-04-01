import streamlit as st

from api import approve, escalate, get_pending_approvals, reject

st.title("Pending Approvals")

if st.button("Refresh"):
    st.cache_data.clear()
    st.rerun()


@st.cache_data(ttl=10)
def _cached_pending() -> list:
    """Caches pending approvals list briefly so queue interactions remain fast and stable."""

    return get_pending_approvals()


try:
    pending = _cached_pending()
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()

if not pending:
    st.info("No pending approvals. System is clear.")

for item in pending:
    approval_id = item["id"]
    incident_id = item.get("incident_id", "")
    score = float(item.get("confidence_score", 0.0))

    reviewer_key = f"reviewer_{approval_id}"
    reason_key = f"reason_{approval_id}"
    if reviewer_key not in st.session_state:
        st.session_state[reviewer_key] = ""
    if reason_key not in st.session_state:
        st.session_state[reason_key] = ""

    with st.container(border=True):
        st.markdown(
            f"**PENDING** · Incident: `{incident_id[:8]}` · Confidence: `{score * 100:.1f}%`"
        )
        st.write(f"Top cause: **{item.get('top_cause', '-') }**")
        summary = item.get("recommendation_summary", "")
        short_summary = summary if len(summary) <= 200 else summary[:200] + "..."
        st.write(short_summary)

        if item.get("auto_escalated"):
            st.warning(f"AUTO-ESCALATED: {item.get('escalation_reason') or 'Low confidence'}")

        st.text_input("Reviewed by", key=reviewer_key)
        st.text_input("Rejection/Escalation reason", key=reason_key)

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Approve ✓", key=f"approve_{approval_id}"):
                reviewed_by = st.session_state[reviewer_key].strip()
                if not reviewed_by:
                    st.warning("Reviewed by is required.")
                else:
                    try:
                        approve(approval_id, reviewed_by)
                        st.success("Approval granted.")
                        st.cache_data.clear()
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))

        with col2:
            if st.button("Reject ✗", key=f"reject_{approval_id}"):
                reviewed_by = st.session_state[reviewer_key].strip()
                reason = st.session_state[reason_key].strip()
                if not reviewed_by:
                    st.warning("Reviewed by is required.")
                elif not reason:
                    st.warning("Reason is required for rejection.")
                else:
                    try:
                        reject(approval_id, reviewed_by, reason)
                        st.success("Approval rejected.")
                        st.cache_data.clear()
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))

        with col3:
            if st.button("Escalate ↑", key=f"escalate_{approval_id}"):
                reviewed_by = st.session_state[reviewer_key].strip()
                reason = st.session_state[reason_key].strip()
                if not reviewed_by:
                    st.warning("Reviewed by is required.")
                elif not reason:
                    st.warning("Reason is required for escalation.")
                else:
                    try:
                        escalate(approval_id, reviewed_by, reason)
                        st.success("Approval escalated.")
                        st.cache_data.clear()
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))
