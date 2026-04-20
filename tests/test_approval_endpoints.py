import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from sentinelops.database import engine
from sentinelops.main import app
from sentinelops.schemas.incident import GroupingOutput, IncidentGroup
from sentinelops.schemas.root_cause import RootCauseCandidate, RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation


def _ingest_payload() -> dict:
    """Builds deterministic ingest payload used across approval endpoint workflow tests."""

    now = datetime.now(UTC).isoformat()
    return {
        "logs": [
            {
                "timestamp": now,
                "service_name": "api-gateway",
                "log_level": "ERROR",
                "message": "Database timeout from payment call",
                "trace_id": f"trace-{uuid4()}",
            }
        ],
        "alerts": [
            {
                "alert_id": f"alert-{uuid4()}",
                "service_name": "db-primary",
                "severity": "CRITICAL",
                "description": "Primary DB high latency",
                "timestamp": now,
                "status": "OPEN",
            }
        ],
    }


def _grouping_output() -> GroupingOutput:
    """Returns predictable grouping output so endpoint tests are independent from external model calls."""

    return GroupingOutput(
        result=[
            IncidentGroup(
                group_id="g1",
                likely_cause="db latency",
                affected_services=["db-primary", "api-gateway"],
                supporting_events=[{"service": "db-primary", "message": "latency spike"}],
                confidence_score=0.82,
            )
        ],
        confidence_score=0.82,
        evidence=["synthetic evidence"],
        fallback_used=False,
        fallback_reason=None,
    )


def _root_cause_report(incident_id: str) -> RootCauseReport:
    """Returns predictable root-cause output to exercise approval creation and status transitions."""

    return RootCauseReport(
        incident_id=incident_id,
        candidates=[
            RootCauseCandidate(
                service="db-primary",
                graph_score=0.95,
                similarity_score=0.85,
                combined_score=0.9,
                rank=1,
                evidence=["db-primary appears in critical trace"],
                similar_incident_ids=[],
            )
        ],
        top_cause="db-primary",
        confidence_score=0.9,
        graph_path=["db-primary", "api-gateway"],
        analysis_method="graph+vector",
    )


def _runbook_recommendation(incident_id: str) -> RunbookRecommendation:
    """Returns grounded runbook data so ingest response can include full enriched recommendation context."""

    return RunbookRecommendation(
        incident_id=incident_id,
        top_cause="db-primary",
        steps=["Throttle non-critical load", "Inspect active query backlog"],
        source_chunks=["db_latency_1"],
        source_files=["db_latency.md"],
        confidence_score=0.88,
        grounded=True,
        raw_synthesis="Grounded recommendation",
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Creates API client with deterministic ingest dependencies for stable approval endpoint tests."""

    async def _mock_group_telemetry(logs, db):
        """Supplies deterministic grouping output independent of external LLM execution."""

        return _grouping_output()

    async def _mock_rank_root_causes(incident_id, grouping_output, db):
        """Supplies deterministic root-cause ranking used to create predictable approval requests."""

        return _root_cause_report(incident_id)

    async def _mock_get_runbook_recommendation(report, db):
        """Supplies deterministic runbook recommendation to avoid external synthesis calls in tests."""

        return _runbook_recommendation(report.incident_id)

    def _mock_embed_incident(text):
        """Supplies fixed-size embedding vector so ORM vector writes remain valid during ingest."""

        return [0.0] * 384

    monkeypatch.setattr("sentinelops.services.incident_service.group_telemetry", _mock_group_telemetry)
    monkeypatch.setattr("sentinelops.services.incident_service.rank_root_causes", _mock_rank_root_causes)
    monkeypatch.setattr(
        "sentinelops.services.incident_service.get_runbook_recommendation",
        _mock_get_runbook_recommendation,
    )
    monkeypatch.setattr("sentinelops.services.incident_service.embed_incident", _mock_embed_incident)

    asyncio.run(engine.dispose())
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


def test_get_pending_returns_only_pending_requests(client: TestClient) -> None:
    """Verifies pending queue endpoint only lists requests still awaiting human decision."""

    ingest_response = client.post("/api/v1/ingest", json=_ingest_payload())
    assert ingest_response.status_code == 200
    approval_id = ingest_response.json()["approval_request"]["id"]

    approve_response = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewed_by": "operator-a", "reason": "Safe to proceed"},
    )
    assert approve_response.status_code == 200

    pending_response = client.get("/api/v1/approvals/pending")
    assert pending_response.status_code == 200
    pending_ids = {row["id"] for row in pending_response.json()}
    assert approval_id not in pending_ids


def test_full_approval_flow_updates_status_to_approved(client: TestClient) -> None:
    """Verifies end-to-end ingest to approve flow transitions request from pending to approved state."""

    ingest_response = client.post("/api/v1/ingest", json=_ingest_payload())
    assert ingest_response.status_code == 200
    approval_request = ingest_response.json()["approval_request"]
    assert approval_request["status"] == "PENDING"

    pending_response = client.get("/api/v1/approvals/pending")
    assert pending_response.status_code == 200
    pending_ids = {row["id"] for row in pending_response.json()}
    assert approval_request["id"] in pending_ids

    approve_response = client.post(
        f"/api/v1/approvals/{approval_request['id']}/approve",
        json={"reviewed_by": "operator-b", "reason": "Looks valid"},
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "APPROVED"


def test_rejection_flow_sets_rejected_with_reason(client: TestClient) -> None:
    """Verifies reject endpoint accepts reason and transitions approval request into rejected state."""

    ingest_response = client.post("/api/v1/ingest", json=_ingest_payload())
    assert ingest_response.status_code == 200
    approval_id = ingest_response.json()["approval_request"]["id"]

    reject_response = client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        json={"reviewed_by": "operator-c", "reason": "Need additional validation"},
    )
    assert reject_response.status_code == 200
    assert reject_response.json()["status"] == "REJECTED"


def test_approving_already_approved_request_returns_400(client: TestClient) -> None:
    """Verifies second approval attempt on same request returns HTTP 400 for double-approval prevention."""

    ingest_response = client.post("/api/v1/ingest", json=_ingest_payload())
    assert ingest_response.status_code == 200
    approval_id = ingest_response.json()["approval_request"]["id"]

    first_approve = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewed_by": "operator-d", "reason": "Approved"},
    )
    assert first_approve.status_code == 200

    second_approve = client.post(
        f"/api/v1/approvals/{approval_id}/approve",
        json={"reviewed_by": "operator-e", "reason": "Approved again"},
    )
    assert second_approve.status_code == 400
