## Evaluation

Run the benchmark harness against a live backend:

```bash
# Terminal 1 — start backend
uv run uvicorn sentinelops.main:app --port 8000

# Terminal 2 — run eval
cd eval
pip install -r requirements.txt
python run_eval.py --runs 20
```

Results are saved to `eval/results/`:
- `raw_results.json` — per-run data
- `summary.json` — aggregated metrics
- `accuracy_summary.png`
- `confidence_distributions.png`
- `latency_breakdown.png`
- `root_cause_ranking.png`
- `run_timeline.png`