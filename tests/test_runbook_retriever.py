import pytest

from sentinelops.schemas.root_cause import RootCauseCandidate, RootCauseReport
from sentinelops.services.runbook_retriever import build_retrieval_query, get_runbook_recommendation


def _report() -> RootCauseReport:
    """Builds deterministic root-cause report fixture for runbook retriever tests."""

    return RootCauseReport(
        incident_id="test-incident",
        candidates=[
            RootCauseCandidate(
                service="db-primary",
                graph_score=1.0,
                similarity_score=0.0,
                combined_score=0.7,
                rank=1,
                evidence=["graph"],
                similar_incident_ids=[],
            )
        ],
        top_cause="db-primary",
        confidence_score=0.7,
        graph_path=["db-primary", "payment-service", "api-gateway"],
        analysis_method="graph_only",
    )


def test_build_retrieval_query_non_empty() -> None:
    """Verifies retrieval query builder emits usable context text for vector similarity lookup."""

    query = build_retrieval_query(_report())
    assert isinstance(query, str)
    assert query.strip()


@pytest.mark.asyncio
async def test_empty_chunk_store_returns_grounded_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies recommendation call returns explicit non-grounded response when no chunks are indexed."""

    async def _empty_chunks(**kwargs):
        """Forces empty retrieval result for deterministic empty-index coverage."""

        return []

    monkeypatch.setattr("sentinelops.services.runbook_retriever.retrieve_runbook_chunks", _empty_chunks)
    recommendation = await get_runbook_recommendation(_report(), db=None)
    assert recommendation.grounded is False
    assert recommendation.steps == []
    assert recommendation.confidence_score == 0.0


@pytest.mark.asyncio
async def test_synthesis_not_called_when_chunks_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies synthesis step is skipped entirely when retrieval returns no supporting chunks."""

    async def _empty_chunks(**kwargs):
        """Forces empty retrieval so synthesis must not execute."""

        return []

    async def _should_not_call(**kwargs):
        """Fails test if synthesis path is entered despite empty retrieval."""

        raise AssertionError("synthesize_recommendation should not be called")

    monkeypatch.setattr("sentinelops.services.runbook_retriever.retrieve_runbook_chunks", _empty_chunks)
    monkeypatch.setattr("sentinelops.services.runbook_retriever.synthesize_recommendation", _should_not_call)
    recommendation = await get_runbook_recommendation(_report(), db=None)
    assert recommendation.grounded is False