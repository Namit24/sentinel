# SentinelOps Operator Dashboard

## Run locally

```bash
# Terminal 1 — start FastAPI
cd sentinelops
uv run uvicorn sentinelops.main:app --reload --port 8000

# Terminal 2 — start Streamlit
cd dashboard
streamlit run app.py
```

Dashboard URL: `http://localhost:8501`

If FastAPI is running on a different host/port:

```bash
export SENTINELOPS_API_URL=http://localhost:8000
```
