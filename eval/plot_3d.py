from __future__ import annotations

import json
import os
import warnings
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


def _load_raw_results(results_dir: str | Path) -> list[dict]:
    """Loads normalized raw benchmark rows from one evaluation results directory."""

    path = Path(results_dir) / "raw_results.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _successful_rows(raw_results: list[dict]) -> list[dict]:
    """Returns successful benchmark rows so plots represent actual pipeline executions."""

    return [row for row in raw_results if row.get("success")]


def _save(fig: plt.Figure, path: Path) -> Path:
    """Saves a matplotlib figure at publication quality and closes it immediately."""

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Tight layout not applied.*")
        fig.tight_layout()
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return path


def _short_label(row: dict) -> str:
    """Builds a concise point label that is readable inside dense 3D scatter plots."""

    scenario = str(row.get("scenario_id", "run"))
    run_index = row.get("run_index", "?")
    return f"{scenario[:10]}-{run_index}"


def _scenario_color_map(rows: list[dict]) -> dict[str, tuple]:
    """Returns stable scenario colors so related plots share the same visual mapping."""

    scenarios = sorted({str(row.get("scenario_id", "unknown")) for row in rows})
    cmap = plt.get_cmap("tab10")
    return {scenario: cmap(index % 10) for index, scenario in enumerate(scenarios)}


def plot_confidence_latency_landscape(rows: list[dict], output_path: Path) -> Path | None:
    """Plots grouping/root-cause confidence against end-to-end latency for each benchmark run."""

    required = {"grouping_confidence", "root_cause_confidence", "latency_seconds", "runbook_confidence"}
    if not rows or not any(all(row.get(key) is not None for key in required) for row in rows):
        return None

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection="3d")

    x = [float(row.get("grouping_confidence", 0.0)) for row in rows]
    y = [float(row.get("root_cause_confidence", 0.0)) for row in rows]
    z = [float(row.get("latency_seconds", 0.0)) for row in rows]
    c = [float(row.get("runbook_confidence", 0.0)) for row in rows]
    max_total = max(float(row.get("pipeline_total_ms", 0.0) or 0.0) for row in rows) or 1.0
    sizes = [60.0 + (120.0 * (float(row.get("pipeline_total_ms", 0.0) or 0.0) / max_total)) for row in rows]

    scatter = ax.scatter(
        x,
        y,
        z,
        c=c,
        cmap="viridis",
        s=sizes,
        alpha=0.9,
        edgecolors="black",
        linewidths=0.6,
    )
    for row, xv, yv, zv in zip(rows, x, y, z, strict=False):
        ax.text(xv, yv, zv, _short_label(row), fontsize=7)

    ax.set_title("3D Confidence-Latency Landscape")
    ax.set_xlabel("Grouping confidence")
    ax.set_ylabel("Root-cause confidence")
    ax.set_zlabel("Latency (s)")
    ax.view_init(elev=24, azim=34)
    colorbar = fig.colorbar(scatter, ax=ax, shrink=0.72, pad=0.1)
    colorbar.set_label("Runbook confidence")

    return _save(fig, output_path)


def plot_stage_latency_controls(rows: list[dict], output_path: Path) -> Path | None:
    """Plots stage latency vs pipeline total with policy status overlays for each benchmark run."""

    stage_keys = ("grouping_ms", "runbook_ms", "pipeline_total_ms")
    if not rows or not any(all(row.get(key) is not None for key in stage_keys) for row in rows):
        return None

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection="3d")

    policy_values = sorted({str(row.get("policy_status", "UNKNOWN")) for row in rows})
    palette = plt.get_cmap("Set2")
    color_map = {policy: palette(index % palette.N) for index, policy in enumerate(policy_values)}

    for policy in policy_values:
        policy_rows = [row for row in rows if str(row.get("policy_status", "UNKNOWN")) == policy]
        ax.scatter(
            [float(row.get("grouping_ms", 0.0)) / 1000.0 for row in policy_rows],
            [float(row.get("runbook_ms", 0.0)) / 1000.0 for row in policy_rows],
            [float(row.get("pipeline_total_ms", 0.0)) / 1000.0 for row in policy_rows],
            color=color_map[policy],
            s=90,
            alpha=0.9,
            edgecolors="black",
            linewidths=0.6,
            label=policy,
        )
        for row in policy_rows:
            ax.text(
                float(row.get("grouping_ms", 0.0)) / 1000.0,
                float(row.get("runbook_ms", 0.0)) / 1000.0,
                float(row.get("pipeline_total_ms", 0.0)) / 1000.0,
                _short_label(row),
                fontsize=7,
            )

    ax.set_title("3D Stage Latency by Policy Outcome")
    ax.set_xlabel("Grouping latency (s)")
    ax.set_ylabel("Runbook latency (s)")
    ax.set_zlabel("Pipeline total (s)")
    ax.view_init(elev=26, azim=36)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 1.0))

    return _save(fig, output_path)


def plot_scenario_stage_bars(rows: list[dict], output_path: Path) -> Path | None:
    """Plots mean stage latency per scenario as a 3D bar chart for documentation-friendly comparison."""

    stage_names = ("grouping_ms", "root_cause_ms", "runbook_ms", "approval_ms")
    stage_labels = {
        "grouping_ms": "grouping",
        "root_cause_ms": "root cause",
        "runbook_ms": "runbook",
        "approval_ms": "approval",
    }
    eligible = [row for row in rows if all(row.get(stage) is not None for stage in stage_names)]
    if not eligible:
        return None

    scenario_groups: dict[str, list[dict]] = defaultdict(list)
    for row in eligible:
        scenario_groups[str(row.get("scenario_id", "unknown"))].append(row)

    scenarios = sorted(scenario_groups)
    fig = plt.figure(figsize=(11, 8))
    ax = fig.add_subplot(111, projection="3d")
    stage_palette = plt.get_cmap("Set3")
    stage_colors = {stage: stage_palette(index % stage_palette.N) for index, stage in enumerate(stage_names)}

    dx = 0.55
    dy = 0.55
    for x_index, scenario in enumerate(scenarios):
        rows_for_scenario = scenario_groups[scenario]
        for y_index, stage in enumerate(stage_names):
            values = [float(row.get(stage, 0.0)) / 1000.0 for row in rows_for_scenario]
            height = sum(values) / len(values) if values else 0.0
            ax.bar3d(
                x_index,
                y_index,
                0.0,
                dx,
                dy,
                height,
                color=stage_colors[stage],
                alpha=0.85,
                shade=True,
            )

    ax.set_title("3D Mean Stage Latency by Scenario")
    ax.set_xlabel("Scenario")
    ax.set_ylabel("Pipeline stage")
    ax.set_zlabel("Mean latency (s)")
    ax.set_xticks([index + (dx / 2.0) for index in range(len(scenarios))])
    ax.set_xticklabels(scenarios, rotation=20, ha="right")
    ax.set_yticks([index + (dy / 2.0) for index in range(len(stage_names))])
    ax.set_yticklabels([stage_labels[stage] for stage in stage_names])
    ax.view_init(elev=27, azim=-48)
    legend_items = [Patch(facecolor=stage_colors[stage], label=stage_labels[stage]) for stage in stage_names]
    ax.legend(handles=legend_items, loc="upper left", bbox_to_anchor=(0.0, 1.0))

    return _save(fig, output_path)


def plot_volume_risk(rows: list[dict], output_path: Path) -> Path | None:
    """Plots incident size, alert volume, and latency with scenario-colored markers."""

    required = {"log_count", "alert_count", "latency_seconds"}
    if not rows or not any(all(row.get(key) is not None for key in required) for row in rows):
        return None

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection="3d")
    scenario_colors = _scenario_color_map(rows)

    for scenario, color in scenario_colors.items():
        scenario_rows = [row for row in rows if str(row.get("scenario_id", "unknown")) == scenario]
        ax.scatter(
            [float(row.get("log_count", 0.0)) for row in scenario_rows],
            [float(row.get("alert_count", 0.0)) for row in scenario_rows],
            [float(row.get("latency_seconds", 0.0)) for row in scenario_rows],
            color=color,
            s=90,
            alpha=0.9,
            edgecolors="black",
            linewidths=0.6,
            label=scenario,
        )
        for row in scenario_rows:
            ax.text(
                float(row.get("log_count", 0.0)),
                float(row.get("alert_count", 0.0)),
                float(row.get("latency_seconds", 0.0)),
                str(row.get("risk_level", "unknown"))[:7],
                fontsize=7,
            )

    ax.set_title("3D Incident Volume, Alert Count, and Latency")
    ax.set_xlabel("Log count")
    ax.set_ylabel("Alert count")
    ax.set_zlabel("Latency (s)")
    ax.view_init(elev=24, azim=42)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 1.0))

    return _save(fig, output_path)


def generate_3d_plots(results_dir: str | Path) -> list[Path]:
    """Generates 3D benchmark figures from saved raw benchmark results."""

    results_path = Path(results_dir)
    rows = _successful_rows(_load_raw_results(results_path))
    if not rows:
        return []

    outputs = [
        plot_confidence_latency_landscape(rows, results_path / "benchmark_3d_confidence_latency.png"),
        plot_stage_latency_controls(rows, results_path / "benchmark_3d_stage_latency.png"),
        plot_scenario_stage_bars(rows, results_path / "benchmark_3d_scenario_stage_bars.png"),
        plot_volume_risk(rows, results_path / "benchmark_3d_volume_risk.png"),
    ]
    return [path for path in outputs if path is not None]
