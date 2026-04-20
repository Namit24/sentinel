from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.models.alert import Alert
from sentinelops.models.prompt_run import PromptRun


def _safe_float(value: float | None) -> float:
    """Normalizes nullable aggregate outputs to stable float values."""

    return float(value) if value is not None else 0.0


def _distribution_from_counts(rows: list[tuple[str | None, int]]) -> dict[str, float]:
    """Converts grouped count rows into normalized probability distribution values."""

    normalized_counts: dict[str, int] = {}
    for severity, count in rows:
        key = str(severity or "UNKNOWN").upper()
        normalized_counts[key] = normalized_counts.get(key, 0) + int(count)

    total = sum(normalized_counts.values())
    if total == 0:
        return {}
    return {key: value / total for key, value in normalized_counts.items()}


async def get_prompt_run_stats(db: AsyncSession, window_hours: int = 24) -> dict:
    """Returns aggregate prompt run health metrics for the requested recent time window."""

    cutoff = datetime.now(UTC) - timedelta(hours=window_hours)

    total_stmt = select(func.count(PromptRun.id)).where(PromptRun.created_at >= cutoff)
    success_stmt = select(func.count(PromptRun.id)).where(
        PromptRun.created_at >= cutoff,
        PromptRun.success.is_(True),
    )
    fallback_stmt = select(func.count(PromptRun.id)).where(
        PromptRun.created_at >= cutoff,
        PromptRun.fallback_used.is_(True),
    )
    mean_stmt = select(
        func.avg(PromptRun.confidence_score),
        func.avg(PromptRun.latency_ms),
    ).where(PromptRun.created_at >= cutoff)
    by_version_stmt = (
        select(PromptRun.prompt_version, func.count(PromptRun.id))
        .where(PromptRun.created_at >= cutoff)
        .group_by(PromptRun.prompt_version)
    )

    total_runs = int((await db.scalar(total_stmt)) or 0)
    success_runs = int((await db.scalar(success_stmt)) or 0)
    fallback_runs = int((await db.scalar(fallback_stmt)) or 0)
    mean_confidence, mean_latency = (await db.execute(mean_stmt)).one()
    by_version_rows = (await db.execute(by_version_stmt)).all()

    return {
        "total_runs": total_runs,
        "success_rate": (success_runs / total_runs) if total_runs else 0.0,
        "fallback_rate": (fallback_runs / total_runs) if total_runs else 0.0,
        "mean_confidence": _safe_float(mean_confidence),
        "mean_latency_ms": _safe_float(mean_latency),
        "runs_by_version": {str(version): int(count) for version, count in by_version_rows},
    }


async def get_confidence_trend(db: AsyncSession, window_hours: int = 24) -> list[dict]:
    """Returns chronological prompt-run confidence points for dashboard time-series visualization."""

    cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
    statement = (
        select(PromptRun.created_at, PromptRun.confidence_score, PromptRun.fallback_used)
        .where(PromptRun.created_at >= cutoff)
        .order_by(PromptRun.created_at.asc())
    )

    rows = (await db.execute(statement)).all()
    return [
        {
            "timestamp": created_at.isoformat(),
            "confidence_score": float(confidence_score),
            "fallback_used": bool(fallback_used),
        }
        for created_at, confidence_score, fallback_used in rows
    ]


async def get_telemetry_drift_stats(db: AsyncSession, window_hours: int = 24) -> dict:
    """Compares recent alert severity distribution with the all-time baseline to detect drift."""

    cutoff = datetime.now(UTC) - timedelta(hours=window_hours)

    baseline_stmt = select(Alert.severity, func.count(Alert.id)).group_by(Alert.severity)
    recent_stmt = (
        select(Alert.severity, func.count(Alert.id))
        .where(Alert.timestamp >= cutoff)
        .group_by(Alert.severity)
    )

    baseline_distribution = _distribution_from_counts((await db.execute(baseline_stmt)).all())
    recent_distribution = _distribution_from_counts((await db.execute(recent_stmt)).all())

    all_keys = set(baseline_distribution) | set(recent_distribution)
    drift_score = float(
        sum(abs(baseline_distribution.get(key, 0.0) - recent_distribution.get(key, 0.0)) for key in all_keys)
    )

    return {
        "baseline_distribution": baseline_distribution,
        "recent_distribution": recent_distribution,
        "drift_score": drift_score,
        "drift_detected": drift_score > 0.15,
        "window_hours": window_hours,
    }