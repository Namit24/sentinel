# AGENT.md — SentinelOps AI

> Instructions for GPT-5.3 Codex (and any AI coding agent) working on this codebase.
> Read this file fully before writing or modifying any code.

---

## What this project is

SentinelOps AI is an **explainable enterprise incident triage system**.

It ingests synthetic microservice telemetry (logs, alerts, metrics), groups related signals,
ranks likely root causes using a service dependency graph, and retrieves grounded remediation
steps from runbooks — with human approval before any action is taken.

This is a backend-first Python project with a Streamlit operator dashboard for simulation, review, approvals, and evaluation.

---

## Non-negotiable principles

These apply to every file you touch:

1. **No business logic in route handlers.** Routes call services. Services contain logic.
2. **Every function needs a docstring.** Explain what it does AND why it exists.
3. **Pre-processing is always separate from LLM calls.** Never send raw data to the model.
4. **LLM calls are isolated in service classes.** They must be swappable without touching other code.
5. **If the LLM is unavailable or returns malformed output, fall back gracefully.** Never crash the pipeline.
6. **Confidence scores are mandatory on any model output.** Never return a recommendation without one.
7. **Human approval is required before any remediation action.** The system recommends; humans decide.

---

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| Package manager | uv |
| Web framework | FastAPI |
| Database | PostgreSQL + pgvector |
| ORM | SQLAlchemy (async) |
| Migrations | Alembic |
| LLM | Gemma 4 31B via Google Gemini API (AI Studio key) |
| LLM SDK | `google-genai` (official Google Gen AI Python SDK) |
| Embeddings | sentence-transformers (local) |
| Graph | NetworkX |
| Validation | Pydantic v2 |
| Testing | pytest + pytest-asyncio |
| Env management | python-dotenv + pydantic-settings |

---

## Project structure

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
└── tests/
    ├── __init__.py
    ├── test_preprocessor.py
    ├── test_grouper.py
    └── test_graph_engine.py
```

---

## Module build order

Build in this sequence. Do not skip ahead.

```
Module 1 → Telemetry ingestion + log grouping
Module 2 → Root cause ranking (dependency graph)
Module 3 → Runbook retrieval (RAG)
Module 4 → Human approval + audit layer
```

---

## LLM usage rules

- **Model:** `gemma-3-27b-it` via Google Gemini API (AI Studio)
- **SDK:** use `google-genai` — specifically `google.genai.Client` with `GEMINI_API_KEY`
- **Always** instruct the model to return valid JSON only — no preamble, no markdown fences
- **Always** validate and parse the response — if malformed, retry once, then use rule-based fallback
- **Never** send raw logs to the model — pre-process first (filter → deduplicate → structure)
- **Hard limit:** max 80 entries per LLM call
- **Always** include a `confidence_score` field (0.0–1.0) in every model output schema
- **Use** `response_mime_type="application/json"` in generation config for structured outputs
- **Temperature:** 0.2 for structured tasks, 0.0 for classification

---

## Gemini API client pattern

Always initialize the client like this — never inline the key:

```python
from google import genai
from google.genai import types
from sentinelops.config import settings

client = genai.Client(api_key=settings.GEMINI_API_KEY)

response = client.models.generate_content(
    model="gemma-4-31b-it",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.2,
        max_output_tokens=2048,
    ),
)
```

---

## Environment variables

Never hardcode secrets. Use `.env` loaded via `python-dotenv`, validated via `pydantic-settings`.

Required variables:

```
GEMINI_API_KEY=
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/sentinelops
ENVIRONMENT=development
LOG_LEVEL=INFO
GROUPING_TIMEOUT_SECONDS=8
RUNBOOK_SYNTHESIS_TIMEOUT_SECONDS=8
LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD=3
LLM_CIRCUIT_BREAKER_RESET_SECONDS=120
POLICY_ALLOW_CONFIDENCE_THRESHOLD=0.85
POLICY_REVIEW_CONFIDENCE_THRESHOLD=0.60
POLICY_BLOCK_ON_UNGROUNDED_RUNBOOK=true
```

---

## Output format rules

All LLM-generated outputs must conform to this envelope:

```json
{
  "result": [...],
  "confidence_score": 0.0,
  "evidence": [...],
  "fallback_used": false,
  "fallback_reason": null
}
```

If a fallback was used, set `fallback_used: true` and populate `fallback_reason`.

---

## What not to do

- Do not use `requests` — use `httpx` for any non-Gemini HTTP calls (async)
- Do not put logic in `__init__.py` files
- Do not use `print()` — use Python `logging`
- Do not catch bare `Exception` without logging the error first
- Do not return raw LLM text to the API consumer — always parse and validate first
- Do not add RL, graph ML, or Kafka until explicitly instructed
- Do not use the old `google-generativeai` SDK — use `google-genai` only
