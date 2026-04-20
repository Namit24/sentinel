import pandas as pd
import streamlit as st

from api import get_confidence_trend, get_drift_stats, get_prompt_health


@st.cache_data(ttl=30)
def _load_prompt_health() -> dict:
    """Fetches prompt health metrics with short-lived caching for responsive dashboards."""

    return get_prompt_health()


@st.cache_data(ttl=30)
def _load_confidence_trend() -> list[dict]:
    """Fetches confidence trend points with short-lived caching for chart rendering."""

    return get_confidence_trend()


@st.cache_data(ttl=30)
def _load_drift_stats() -> dict:
    """Fetches drift metrics with short-lived caching for observability section refreshes."""

    return get_drift_stats()


st.title("MLOps Model Health")

if st.button("Refresh", use_container_width=False):
    st.cache_data.clear()
    st.rerun()

prompt_health = _load_prompt_health()
trend_points = _load_confidence_trend()
drift_stats = _load_drift_stats()

st.subheader("Prompt Performance (last 24h)")
metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
metric_col1.metric("Total Runs", int(prompt_health.get("total_runs", 0)))
metric_col2.metric("Success Rate", f"{float(prompt_health.get('success_rate', 0.0)) * 100:.1f}%")
metric_col3.metric("Fallback Rate", f"{float(prompt_health.get('fallback_rate', 0.0)) * 100:.1f}%")
metric_col4.metric("Mean Confidence", f"{float(prompt_health.get('mean_confidence', 0.0)):.3f}")

st.metric("Mean Latency (ms)", f"{float(prompt_health.get('mean_latency_ms', 0.0)):.1f}")

runs_by_version = prompt_health.get("runs_by_version") or {}
if runs_by_version:
    version_rows = [{"prompt_version": key, "runs": int(value)} for key, value in runs_by_version.items()]
    st.dataframe(pd.DataFrame(version_rows), use_container_width=True)
else:
    st.dataframe(pd.DataFrame(columns=["prompt_version", "runs"]), use_container_width=True)

st.subheader("Confidence Trend")
if not trend_points:
    st.info("No prompt runs recorded yet. Run a simulation first.")
else:
    trend_df = pd.DataFrame(trend_points)
    trend_df["timestamp"] = pd.to_datetime(trend_df["timestamp"], errors="coerce")
    trend_df = trend_df.dropna(subset=["timestamp"]).sort_values("timestamp")
    if trend_df.empty:
        st.info("No prompt runs recorded yet. Run a simulation first.")
    else:
        st.line_chart(
            trend_df.set_index("timestamp")[["confidence_score"]],
            use_container_width=True,
        )
        fallback_count = int(trend_df["fallback_used"].fillna(False).astype(bool).sum())
        st.caption(f"Fallback points in window: {fallback_count}")

st.subheader("Telemetry Drift Detection")
st.metric("Drift Score", f"{float(drift_stats.get('drift_score', 0.0)):.3f}")
if bool(drift_stats.get("drift_detected", False)):
    st.warning("Drift detected — input distribution has shifted")
else:
    st.success("No drift detected")

baseline_col, recent_col = st.columns(2)
baseline_distribution = drift_stats.get("baseline_distribution") or {}
recent_distribution = drift_stats.get("recent_distribution") or {}

baseline_rows = [
    {"severity": key, "proportion": float(value)}
    for key, value in baseline_distribution.items()
]
recent_rows = [
    {"severity": key, "proportion": float(value)}
    for key, value in recent_distribution.items()
]

with baseline_col:
    st.caption("Baseline Distribution")
    st.dataframe(pd.DataFrame(baseline_rows), use_container_width=True)

with recent_col:
    st.caption("Recent Distribution")
    st.dataframe(pd.DataFrame(recent_rows), use_container_width=True)

st.caption(
    "Drift score measures how much the recent alert severity distribution differs from the all-time baseline. "
    "Score > 0.15 triggers a warning."
)