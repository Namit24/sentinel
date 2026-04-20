from datetime import UTC, datetime
from uuid import uuid4

from sentinelops.schemas.incident import GroupingOutput, IncidentGroup
from sentinelops.schemas.root_cause import RootCauseCandidate, RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation
from sentinelops.services.policy_engine import build_policy_decision


def _grouping_output(*, fallback_used: bool = False) -> GroupingOutput:
    """Builds deterministic grouping output so policy tests exercise explicit control triggers."""

    return GroupingOutput(
        result=[
            IncidentGroup(
                group_id="incident-1",
                likely_cause="db-primary latency",
                affected_services=["db-primary", "payment-service"],
                supporting_events=[
                    {
                        "timestamp": datetime(2026, 4, 1, tzinfo=UTC).isoformat(),
                        "service": "db-primary",
                        "error_type": "latency",
                        "count": 12,
                    }
                ],
                confidence_score=0.8,
            )
        ],
        confidence_score=0.8,
        evidence=["Synthetic telemetry"],
        fallback_used=fallback_used,
        fallback_reason="timeout" if fallback_used else None,
    )


def _report(*, confidence_score: float = 0.9, analysis_method: str = "graph+vector") -> RootCauseReport:
    """Builds a root-cause report with configurable confidence and analysis method."""

    return RootCauseReport(
        incident_id=str(uuid4()),
        candidates=[
            RootCauseCandidate(
                service="db-primary",
                graph_score=1.0,
                similarity_score=0.6,
                combined_score=0.88,
                rank=1,
                evidence=["Graph and similarity support"],
                similar_incident_ids=[],
            )
        ],
        top_cause="db-primary",
        confidence_score=confidence_score,
        graph_path=["db-primary", "payment-service"],
        analysis_method=analysis_method,
    )


def _runbook(*, grounded: bool = True, confidence_score: float = 0.8) -> RunbookRecommendation:
    """Builds a runbook payload with configurable grounding and retrieval confidence."""

    return RunbookRecommendation(
        incident_id=str(uuid4()),
        top_cause="db-primary",
        steps=["Throttle traffic", "Inspect lock contention"],
        source_chunks=["db_latency_1"],
        source_files=["db_latency.md", "payment_timeout.md"] if grounded else [],
        confidence_score=confidence_score,
        grounded=grounded,
        raw_synthesis="Grounded runbook recommendation.",
    )


def test_policy_blocks_ungrounded_runbook() -> None:
    """Verifies ungrounded guidance is blocked for regulated workflows."""

    decision = build_policy_decision(
        grouping_output=_grouping_output(),
        report=_report(),
        runbook=_runbook(grounded=False, confidence_score=0.0),
    )

    assert decision.policy_status == "BLOCKED"
    assert decision.risk_level == "CRITICAL"
    assert "UNGROUNDED_RUNBOOK" in decision.control_flags


def test_policy_escalates_on_grouping_fallback() -> None:
    """Verifies deterministic fallback during intake raises reviewer tier and risk level."""

    decision = build_policy_decision(
        grouping_output=_grouping_output(fallback_used=True),
        report=_report(confidence_score=0.72),
        runbook=_runbook(),
    )

    assert decision.policy_status == "ESCALATE_REQUIRED"
    assert decision.risk_level == "HIGH"
    assert decision.reviewer_tier == "senior-operator"
    assert "GROUPING_FALLBACK" in decision.control_flags


def test_policy_restricts_graph_only_analysis() -> None:
    """Verifies graph-only rankings do not pass as normal low-risk recommendations."""

    decision = build_policy_decision(
        grouping_output=_grouping_output(),
        report=_report(confidence_score=0.82, analysis_method="graph_only"),
        runbook=_runbook(),
    )

    assert decision.policy_status == "RESTRICTED_REVIEW"
    assert decision.risk_level == "MEDIUM"
    assert "GRAPH_ONLY_RANKING" in decision.control_flags
