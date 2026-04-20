import os
from typing import Any

import httpx

BASE_URL = os.getenv("SENTINELOPS_API_URL", "http://localhost:8000").rstrip("/")


def _request(method: str, path: str, json_body: dict[str, Any] | None = None) -> Any:
    """Executes one HTTP request to the SentinelOps API and normalizes transport and API errors."""

    url = f"{BASE_URL}{path}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.request(method=method, url=url, json=json_body)
        response.raise_for_status()
        return response.json()
    except httpx.ConnectError as exc:
        raise RuntimeError(f"SentinelOps API is unreachable at {BASE_URL}. Start FastAPI and retry.") from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        try:
            payload = exc.response.json()
            detail = payload.get("detail", detail)
        except ValueError:
            pass
        raise RuntimeError(f"API request failed ({exc.response.status_code}): {detail}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"API request failed: {exc}") from exc


def check_health() -> dict:
    """Fetches FastAPI health so the dashboard can display connectivity and environment status."""

    return _request("GET", "/health")


def check_health_detailed() -> dict:
    """Fetches detailed FastAPI readiness so the dashboard can render breaker and runbook diagnostics."""

    return _request("GET", "/health/detailed")


def run_ingest(logs: list, alerts: list) -> dict:
    """Triggers ingestion for one telemetry bundle and returns the enriched incident payload."""

    return _request("POST", "/api/v1/ingest", {"logs": logs, "alerts": alerts})


def get_incidents() -> list:
    """Returns all incidents for operator list views and drill-down selection controls."""

    return _request("GET", "/api/v1/incidents")


def get_incident(incident_id: str) -> dict:
    """Returns one incident document so UI pages can render full per-incident context."""

    return _request("GET", f"/api/v1/incidents/{incident_id}")


def get_root_cause(incident_id: str) -> dict:
    """Returns persisted root-cause ranking details for an incident analysis panel."""

    return _request("GET", f"/api/v1/incidents/{incident_id}/root-cause")


def get_runbook(incident_id: str) -> dict:
    """Returns runbook recommendation output for operator review before approvals."""

    return _request("GET", f"/api/v1/incidents/{incident_id}/runbook")


def get_audit_trail(incident_id: str) -> list:
    """Returns immutable chronological audit events for incident decision-history rendering."""

    return _request("GET", f"/api/v1/incidents/{incident_id}/audit-trail")


def get_pending_approvals() -> list:
    """Returns pending approval requests forming the human operator work queue."""

    return _request("GET", "/api/v1/approvals/pending")


def index_runbooks() -> dict:
    """Indexes runbooks, preferring the versioned admin route while retaining compatibility with legacy path."""

    try:
        return _request("POST", "/api/v1/admin/index-runbooks")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
        return _request("POST", "/admin/index-runbooks")


def get_approval(approval_id: str) -> dict:
    """Returns one approval request record for direct status inspection and troubleshooting."""

    return _request("GET", f"/api/v1/approvals/{approval_id}")


def approve(approval_id: str, reviewed_by: str) -> dict:
    """Submits human approval for a pending request and returns the updated approval state."""

    return _request(
        "POST",
        f"/api/v1/approvals/{approval_id}/approve",
        {"reviewed_by": reviewed_by, "reason": None},
    )


def reject(approval_id: str, reviewed_by: str, reason: str) -> dict:
    """Submits human rejection with reason so the backend logs audit-complete rejection context."""

    return _request(
        "POST",
        f"/api/v1/approvals/{approval_id}/reject",
        {"reviewed_by": reviewed_by, "reason": reason},
    )


def escalate(approval_id: str, reviewed_by: str, reason: str) -> dict:
    """Escalates a pending request with explicit rationale for additional incident-command review."""

    return _request(
        "POST",
        f"/api/v1/approvals/{approval_id}/escalate",
        {"reviewed_by": reviewed_by, "reason": reason},
    )


def get_prompt_health() -> dict:
    """Returns prompt run health aggregates for the MLOps dashboard page."""

    return _request("GET", "/api/v1/metrics/prompt-health")


def get_confidence_trend() -> list:
    """Returns prompt confidence time-series points for MLOps trend visualization."""

    return _request("GET", "/api/v1/metrics/confidence-trend")


def get_drift_stats() -> dict:
    """Returns telemetry distribution drift statistics for MLOps monitoring."""

    return _request("GET", "/api/v1/metrics/drift")
