from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from sentinelops.schemas.incident import GroupingOutput, IncidentGroup
from sentinelops.services.root_cause_ranker import rank_root_causes


def _grouping_output() -> GroupingOutput:
    """Builds deterministic grouped telemetry for root-cause ranker unit tests."""

    return GroupingOutput(
        result=[
            IncidentGroup(
                group_id="g1",
                likely_cause="db timeout",
                affected_services=["api-gateway", "payment-service", "db-primary"],
                supporting_events=[
                    {
                        "timestamp": datetime(2026, 4, 1, tzinfo=UTC).isoformat(),
                        "service": "payment-service",
                        "message": "Timeout waiting for db-primary",
                    }
                ],
                confidence_score=0.8,
            )
        ],
        confidence_score=0.8,
        evidence=["Synthetic test evidence"],
        fallback_used=False,
        fallback_reason=None,
    )


@pytest.mark.asyncio
async def test_ranker_graph_only_when_no_past_incidents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies ranker degrades gracefully when no vector matches are available."""

    async def _no_similar(**kwargs):
        """Returns empty historical set to force graph-only mode."""

        return []

    monkeypatch.setattr("sentinelops.services.root_cause_ranker.find_similar_incidents", _no_similar)
    report = await rank_root_causes(str(uuid4()), _grouping_output(), db=None)
    assert report.analysis_method == "graph_only"
    assert report.top_cause


@pytest.mark.asyncio
async def test_combined_scores_stay_in_unit_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies weighted rank scoring remains bounded for API confidence consistency."""

    async def _no_similar(**kwargs):
        """Keeps similarity branch deterministic for bounded-score assertions."""

        return []

    monkeypatch.setattr("sentinelops.services.root_cause_ranker.find_similar_incidents", _no_similar)
    report = await rank_root_causes(str(uuid4()), _grouping_output(), db=None)
    assert all(0.0 <= candidate.combined_score <= 1.0 for candidate in report.candidates)


@pytest.mark.asyncio
async def test_candidates_ranked_in_ascending_rank_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies rank labels are contiguous and ordered with highest score at rank one."""

    async def _no_similar(**kwargs):
        """Avoids external dependence so ordering is fully graph-determined."""

        return []

    monkeypatch.setattr("sentinelops.services.root_cause_ranker.find_similar_incidents", _no_similar)
    report = await rank_root_causes(str(uuid4()), _grouping_output(), db=None)
    ranks = [candidate.rank for candidate in report.candidates]
    assert ranks == sorted(ranks)
    assert ranks[0] == 1


@pytest.mark.asyncio
async def test_similarity_cannot_override_strong_auth_service_direct_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies historical DB-heavy incidents do not override direct auth-service incident evidence."""

    grouping = GroupingOutput(
        result=[
            IncidentGroup(
                group_id="auth-1",
                likely_cause="auth-service outage causing gateway login failures",
                affected_services=["auth-service", "api-gateway"],
                supporting_events=[
                    {"service": "auth-service", "error_type": "timeout", "count": 8},
                    {"service": "api-gateway", "error_type": "timeout", "count": 2},
                ],
                confidence_score=0.9,
            )
        ],
        confidence_score=0.9,
        evidence=["Synthetic auth outage evidence"],
        fallback_used=False,
        fallback_reason=None,
    )

    async def _biased_history(**kwargs):
        """Returns DB-primary-heavy history to ensure similarity is gated by direct evidence."""

        return [
            SimpleNamespace(id=uuid4(), top_cause_service="db-primary"),
            SimpleNamespace(id=uuid4(), top_cause_service="db-primary"),
            SimpleNamespace(id=uuid4(), top_cause_service="db-primary"),
        ]

    monkeypatch.setattr("sentinelops.services.root_cause_ranker.find_similar_incidents", _biased_history)
    report = await rank_root_causes(str(uuid4()), grouping, db=None)
    assert report.top_cause == "auth-service"


@pytest.mark.asyncio
async def test_cache_service_direct_evidence_beats_shared_dependency_bias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies cache-service can outrank db-primary when supporting-event volume points to a cache stampede."""

    grouping = GroupingOutput(
        result=[
            IncidentGroup(
                group_id="cache-1",
                likely_cause="cache-service performance degradation",
                affected_services=["cache-service"],
                supporting_events=[
                    {"service": "cache-service", "error_type": "unknown", "count": 12},
                ],
                confidence_score=0.88,
            ),
            IncidentGroup(
                group_id="cache-2",
                likely_cause="payment-service timeout due to cache fallback load",
                affected_services=["payment-service", "db-primary"],
                supporting_events=[
                    {"service": "payment-service", "error_type": "timeout", "count": 3},
                    {"service": "db-primary", "error_type": "latency", "count": 1},
                ],
                confidence_score=0.72,
            ),
        ],
        confidence_score=0.84,
        evidence=["Synthetic cache stampede evidence"],
        fallback_used=False,
        fallback_reason=None,
    )

    async def _biased_history(**kwargs):
        """Returns DB-primary-heavy history so the test captures structural-bias mitigation."""

        return [
            SimpleNamespace(id=uuid4(), top_cause_service="db-primary"),
            SimpleNamespace(id=uuid4(), top_cause_service="db-primary"),
        ]

    monkeypatch.setattr("sentinelops.services.root_cause_ranker.find_similar_incidents", _biased_history)
    report = await rank_root_causes(str(uuid4()), grouping, db=None)
    assert report.top_cause == "cache-service"
