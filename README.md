# SentinelOps AI
Explainable AI system for enterprise incident triage, root-cause ranking, and response optimization.

SentinelOps AI is a backend-first incident triage system that ingests telemetry, groups related signals, ranks likely root causes, and retrieves grounded remediation guidance from runbooks. It is designed for high-pressure operational workflows where responders need faster prioritization without losing traceability. The pipeline combines deterministic methods (preprocessing, graph scoring, rule-based fallbacks) with LLM-assisted components only where semantic interpretation is necessary. Every stage writes structured outputs that can be inspected later, and every recommended action is gated by explicit human approval. The system is built to degrade safely: if an AI component fails, deterministic fallback paths keep the incident pipeline running.

## Why This Exists

Dashboards surface data, but they still leave humans to manually infer causality and action under time pressure. SentinelOps reduces decision uncertainty by ranking probable causes, retrieving evidence-backed runbook steps, and preserving human control through an approval gate and full audit history.

## Architecture

SentinelOps is implemented as a four-module pipeline. Module 1 preprocesses and groups noisy telemetry into incident clusters. Module 2 applies dependency-graph propagation and historical similarity to rank likely root causes. Module 3 retrieves runbook chunks with vector search and synthesizes grounded remediation guidance. Module 4 enforces human-in-the-loop approval and records immutable decision events for auditability.

```
Synthetic Telemetry
	  │
	  ▼
┌─────────────────────┐
│  Module 1           │
│  Signal Intelligence│  ← filter + deduplicate + LLM telemetry grouping
│  (Gemma 3 27B)      │    fallback: rule-based clustering
└─────────┬───────────┘
		  │ GroupingOutput
		  ▼
┌─────────────────────┐
│  Module 2           │
│  Root Cause Ranker  │  ← service dependency graph (NetworkX)
│  (Graph + pgvector) │    upstream blame propagation
└─────────┬───────────┘    semantic similarity to past incidents
		  │ RootCauseReport
		  ▼
┌─────────────────────┐
│  Module 3           │
│  Runbook Retriever  │  ← pgvector chunk retrieval (all-MiniLM-L6-v2)
│  (RAG + Gemma 27B)  │    grounded synthesis — no invented actions
└─────────┬───────────┘
		  │ RunbookRecommendation
		  ▼
┌─────────────────────┐
│  Module 4           │
│  Human Approval     │  ← confidence gate (auto-escalate < 0.4)
│  + Audit Layer      │    approve / reject / escalate
└─────────────────────┘    immutable audit trail
```

The key design principle is that every AI-dependent stage has a deterministic fallback and every recommendation remains advisory until a human explicitly approves it. This keeps the system operational during model/API instability while preserving accountability at decision time.

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI + Python 3.12 | async, typed, production-standard |
| Database | PostgreSQL (NeonDB) | reliable, serverless, pgvector built-in |
| Vector search | pgvector | semantic retrieval without extra infra |
| Embeddings | all-MiniLM-L6-v2 | local, fast, no API dependency |
| LLM | Gemma 3 27B (Gemini API) | open model, structured output, 128k context |
| Graph | NetworkX | service dependency + blame propagation |
| Migrations | Alembic | schema versioned, reproducible |
| Dashboard | Streamlit | rapid operator UI |
| Testing | pytest + pytest-asyncio | 30 tests, all passing |

## AI Component Justification

**LLM telemetry grouping:** Related incident evidence often arrives across differently worded logs and service symptoms; semantic grouping catches relationships that strict keyword or regex rules miss. This is where language understanding provides direct operational value.

**pgvector similarity search:** Prior incidents provide weak but useful prior probability for root-cause ranking, especially when current telemetry is noisy. Vector similarity enables that retrieval over incident history with low infrastructure overhead.

**Graph-based blame propagation:** Service dependencies encode causal structure explicitly, so graph propagation is a stronger mechanism for upstream blame than free-form generation. It provides deterministic, inspectable scoring behavior.

**RAG over runbooks:** Runbooks are unstructured and too large for naive prompting, so retrieval narrows context to relevant chunks before synthesis. This constrains the model to grounded, source-linked remediation guidance.

Where deterministic methods suffice (graph scoring, deduplication, severity classification), no LLM is used.

## Evaluation Results

| Metric | Result |
|---|---|
| Root Cause Top-1 Accuracy | 100% (20/20) |
| LLM Grouping Success Rate | 95% (19/20) |
| Runbook Grounding Rate | 100% (20/20) |
| Correct Source Citation Rate | 100% (20/20) |
| Mean Pipeline Latency | 17.0s |
| P95 Pipeline Latency | 19.4s |
| Failed Runs | 0/20 |

Root-cause ranking remained stable even when grouping took fallback paths in earlier runs, which indicates Module 2 is robust to variation in grouping source. The single fallback run in the final 20-run benchmark (run 16) was a transient API timeout, and the top-ranked cause was still correct. Runbook confidence remained deterministic (~0.66) because this benchmark exercises one fixed synthetic scenario that repeatedly retrieves the same runbook chunks; confidence spread would increase with multiple scenario families.

Initial LLM grouping success rate was 25% before prompt engineering improvements (few-shot examples, stricter schema injection, temperature 0.0, multi-strategy JSON extraction). After optimization: 95%.

## Running Locally

```bash
# Clone and setup
git clone <repo>
cd sentinelops
uv sync
uv sync --extra dev

# Configure environment
cp .env.example .env
# Fill in GEMINI_API_KEY and DATABASE_URL in .env

# Run database migrations
uv run alembic upgrade head

# Start backend
uv run uvicorn sentinelops.main:app --reload --port 8000

# Start dashboard (separate terminal)
streamlit run dashboard/app.py

# Run tests
uv run pytest tests/ -v

# Run evaluation harness
uv run python eval/run_eval.py --runs-per-scenario 4 --delay-seconds 0.5
```

## Running with Docker

```bash
# From repo root
cd sentinelops

# Create env file once and fill in GEMINI_API_KEY + DATABASE_URL
cp .env.example .env

# Build images
docker compose build

# Run migrations (one-off)
docker compose --profile tools run --rm migrate

# Start backend + dashboard
docker compose up
```

Endpoints:

- Backend API: `http://localhost:8000`
- Dashboard: `http://localhost:8501`

Useful commands:

```bash
# Stop services
docker compose down

# Re-run migrations later
docker compose --profile tools run --rm migrate

# Tail logs
docker compose logs -f backend
docker compose logs -f dashboard
```

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | /api/v1/ingest | Ingest logs + alerts, run full pipeline |
| GET | /api/v1/incidents | List all incidents |
| GET | /api/v1/incidents/{id} | Full incident detail |
| GET | /api/v1/incidents/{id}/root-cause | Root cause report |
| GET | /api/v1/incidents/{id}/runbook | Runbook recommendation |
| GET | /api/v1/incidents/{id}/audit-trail | Full decision history |
| GET | /api/v1/approvals/pending | Operator work queue |
| POST | /api/v1/approvals/{id}/approve | Approve recommendation |
| POST | /api/v1/approvals/{id}/reject | Reject with reason |
| POST | /api/v1/approvals/{id}/escalate | Escalate to senior |
| POST | /api/v1/admin/index-runbooks | Index runbook documents |
| GET | /health | Readiness summary |
| GET | /health/detailed | Detailed DB, breaker, and control diagnostics |

## What This Doesn't Do (Yet)

The committed benchmark artifacts currently emphasize one dominant synthetic failure pattern (DB latency cascade), so broad cross-scenario generalization is not yet quantified from the checked-in results alone. End-to-end latency is still dominated by sequential external LLM calls, even though the system now enforces per-stage timeouts, circuit breakers, policy controls, and spike diagnostics. The dependency graph is currently static and code-defined rather than discovered from live topology or service mesh telemetry. Model behavior is prompt-driven only; there is no fine-tuning or policy optimization yet, so grouping quality still depends on external API reliability and quota constraints. The repository now includes a multi-scenario simulation catalog, detailed health endpoints, and a benchmark page in Streamlit so broader evaluation can be rerun and inspected locally.

## Project Structure

```
sentinelops/
├── AGENT.md
├── README.md
├── pyproject.toml
├── .env.example
├── alembic/
│   └── versions/
├── sentinelops/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app entry point
│   ├── config.py                 # Settings via pydantic-settings
│   ├── database.py               # Async SQLAlchemy engine + session
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── log_entry.py
│   │   ├── alert.py
│   │   └── incident.py
│   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── log_entry.py
│   │   ├── alert.py
│   │   └── incident.py
│   ├── routers/                  # FastAPI route handlers (thin layer only)
│   │   ├── __init__.py
│   │   ├── ingest.py
│   │   └── incidents.py
│   ├── services/                 # All business logic lives here
│   │   ├── __init__.py
│   │   ├── preprocessor.py       # Filter, deduplicate, structure logs
│   │   ├── llm_client.py         # Isolated Gemini API wrapper
│   │   ├── grouper.py            # Orchestrates preprocessing + LLM grouping
│   │   ├── graph_engine.py       # Service dependency graph + root cause ranking
│   │   └── runbook_retriever.py  # RAG over remediation docs
│   ├── simulation/               # Synthetic data generation
│   │   ├── __init__.py
│   │   └── generator.py
│   └── utils/
│       ├── __init__.py
│       └── fallbacks.py          # Rule-based fallbacks when LLM fails
├── eval/
│   ├── run_eval.py              # Multi-scenario benchmark harness
│   ├── metrics.py               # Result aggregation helpers
│   └── results/
├── dashboard/
│   ├── app.py                   # Streamlit operator dashboard
│   └── pages/                   # scenario lab, incidents, audit, evaluation
└── tests/
	├── __init__.py
	├── test_preprocessor.py
	├── test_grouper.py
	└── test_graph_engine.py
```

## License

MIT
