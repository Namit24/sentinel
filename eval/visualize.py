from __future__ import annotations

from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.style.use("dark_background")
ACCENT = "#00C49A"
WARN = "#FF6B6B"
NEUTRAL = "#888888"


def _save_figure(fig: plt.Figure, output_dir: Path, filename: str) -> str:
    """Saves one matplotlib figure to the output directory and returns the absolute file path."""

    output_path = output_dir / filename
    fig.tight_layout()
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(output_path)


def _chart_accuracy_summary(metrics: dict, output_dir: Path) -> str:
    """Builds a horizontal bar summary of key end-to-end accuracy rates for quick benchmark communication."""

    labels = [
        "Root Cause Top-1 Accuracy",
        "LLM Grouping Success Rate",
        "Runbook Grounding Rate",
        "Correct Source Citation Rate",
    ]
    values = [
        metrics["root_cause_top1_accuracy"] * 100,
        metrics["grouping_llm_success_rate"] * 100,
        metrics["runbook_grounding_rate"] * 100,
        metrics["runbook_correct_source_rate"] * 100,
    ]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(labels, values, color=[ACCENT, ACCENT, ACCENT, ACCENT])
    ax.set_xlim(0, 100)
    ax.set_xlabel("Percent")
    ax.set_title(f"SentinelOps AI — Pipeline Accuracy ({metrics['total_runs']} runs)")

    for bar, value in zip(bars, values):
        ax.text(value + 1, bar.get_y() + bar.get_height() / 2, f"{value:.1f}%", va="center")

    return _save_figure(fig, output_dir, "accuracy_summary.png")


def _hist_panel(ax: plt.Axes, values: list[float], title: str) -> None:
    """Renders one confidence histogram panel with mean marker and annotation for interpretability."""

    if values:
        mean_val = float(np.mean(values))
        ax.hist(values, bins=np.linspace(0, 1, 11), color=ACCENT, alpha=0.8, edgecolor=NEUTRAL)
        ax.axvline(mean_val, color=WARN, linestyle="--", linewidth=2)
        ax.text(mean_val + 0.01, ax.get_ylim()[1] * 0.85, f"mean={mean_val:.2f}", color=WARN)
    else:
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
    ax.set_xlim(0, 1)
    ax.set_title(title)
    ax.set_xlabel("Score")
    ax.set_ylabel("Count")


def _chart_confidence_distributions(metrics: dict, output_dir: Path) -> str:
    """Builds a three-panel confidence distribution figure for grouping, root-cause, and runbook stages."""

    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8), sharey=True)
    _hist_panel(axes[0], metrics["grouping_confidence_distribution"], "Grouping")
    _hist_panel(axes[1], metrics["root_cause_confidence_distribution"], "Root Cause")
    _hist_panel(axes[2], metrics["runbook_confidence_distribution"], "Runbook")
    fig.suptitle("Confidence Score Distributions")
    return _save_figure(fig, output_dir, "confidence_distributions.png")


def _chart_latency_breakdown(metrics: dict, output_dir: Path) -> str:
    """Builds latency boxplot with run-level points and p50/p95 overlays for pipeline performance diagnostics."""

    latencies = metrics["latency_distribution"]
    fig, ax = plt.subplots(figsize=(10, 5))

    if latencies:
        ax.boxplot(latencies, vert=True, patch_artist=True, boxprops={"facecolor": ACCENT, "alpha": 0.5})
        x_positions = np.random.normal(1, 0.03, size=len(latencies))
        ax.scatter(x_positions, latencies, color=NEUTRAL, alpha=0.55, s=20)
        p50 = metrics["p50_latency_seconds"]
        p95 = metrics["p95_latency_seconds"]
        ax.axhline(p50, color=ACCENT, linestyle="--", linewidth=1.5)
        ax.axhline(p95, color=WARN, linestyle="--", linewidth=1.5)
        ax.text(1.1, p50, f"p50={p50:.2f}s", color=ACCENT, va="bottom")
        ax.text(1.1, p95, f"p95={p95:.2f}s", color=WARN, va="bottom")

    ax.set_xticks([1])
    ax.set_xticklabels(["Pipeline"])
    ax.set_ylabel("Seconds")
    ax.set_title(f"End-to-End Pipeline Latency ({metrics['total_runs']} runs)")
    return _save_figure(fig, output_dir, "latency_breakdown.png")


def _chart_root_cause_ranking(metrics: dict, output_dir: Path) -> str:
    """Builds a donut-style root-cause top-1 distribution chart to highlight ranking reliability."""

    distribution = Counter(metrics.get("top_cause_distribution", []))
    total = sum(distribution.values())
    fig, ax = plt.subplots(figsize=(7, 7))

    if total == 0:
        ax.text(0.5, 0.5, "No successful runs", ha="center", va="center")
    elif len(distribution) == 1 and "db-primary" in distribution:
        ax.pie([1], colors=[ACCENT], wedgeprops={"width": 0.4})
        ax.text(0, 0, "100%\n— db-primary", ha="center", va="center", fontsize=14)
    else:
        labels = list(distribution.keys())
        values = [distribution[label] for label in labels]
        colors = [ACCENT if label == "db-primary" else WARN for label in labels]
        ax.pie(
            values,
            labels=labels,
            autopct=lambda pct: f"{pct:.1f}%",
            colors=colors,
            wedgeprops={"width": 0.4},
        )

    ax.set_title("Root Cause Top-1 Distribution")
    return _save_figure(fig, output_dir, "root_cause_ranking.png")


def _chart_run_timeline(metrics: dict, output_dir: Path) -> str:
    """Builds per-run latency timeline with rolling average and outcome-colored points for drift detection."""

    runs = metrics.get("run_records", [])
    fig, ax = plt.subplots(figsize=(12, 5))

    if runs:
        indices = [row["run_index"] for row in runs]
        latencies = [row["latency_seconds"] for row in runs]
        outcomes = [row["outcome"] for row in runs]

        series = pd.Series(latencies)
        rolling = series.rolling(window=5, min_periods=1).mean()

        ax.plot(indices, latencies, color=NEUTRAL, alpha=0.35, linewidth=1)
        ax.plot(indices, rolling, color=ACCENT, linewidth=2, label="Rolling avg (5)")

        color_map = {"correct": ACCENT, "incorrect": WARN, "failed": NEUTRAL}
        point_colors = [color_map.get(outcome, NEUTRAL) for outcome in outcomes]
        ax.scatter(indices, latencies, color=point_colors, s=40, alpha=0.9)

    ax.set_xlabel("Run index")
    ax.set_ylabel("Seconds")
    ax.set_title("Per-Run Latency + Outcome Timeline")
    ax.legend(loc="upper right")
    return _save_figure(fig, output_dir, "run_timeline.png")


def generate_charts(metrics: dict, output_dir: str) -> list[str]:
    """Generates all benchmark charts and returns absolute paths of saved PNG artifacts."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    return [
        _chart_accuracy_summary(metrics, out_dir),
        _chart_confidence_distributions(metrics, out_dir),
        _chart_latency_breakdown(metrics, out_dir),
        _chart_root_cause_ranking(metrics, out_dir),
        _chart_run_timeline(metrics, out_dir),
    ]
