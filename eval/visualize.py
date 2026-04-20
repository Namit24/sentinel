from __future__ import annotations

import json
from pathlib import Path


def load_summary(results_dir: str | Path = "eval/results") -> dict:
    """Loads the saved evaluation summary JSON so CLI and docs can reuse one canonical artifact."""

    path = Path(results_dir) / "summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    """Prints a concise terminal summary from saved benchmark artifacts."""

    summary = load_summary()
    lines = [
        "SentinelOps benchmark summary",
        f"Total runs: {summary.get('total_runs', 0)}",
        f"Success rate: {float(summary.get('overall_success_rate', 0.0)) * 100:.1f}%",
        (
            "Top-1 accuracy: -"
            if summary.get("root_cause_top1_accuracy") is None
            else f"Top-1 accuracy: {float(summary.get('root_cause_top1_accuracy', 0.0)) * 100:.1f}%"
        ),
        f"Fallback rate: {float(summary.get('grouping_fallback_rate', 0.0)) * 100:.1f}%",
        f"Mean latency: {float(summary.get('mean_latency_seconds', 0.0)):.2f}s",
        f"P95 latency: {float(summary.get('p95_latency_seconds', 0.0)):.2f}s",
    ]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
