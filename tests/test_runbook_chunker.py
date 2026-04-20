from pathlib import Path

from sentinelops.services.runbook_chunker import chunk_runbook


def test_chunking_produces_at_least_three_chunks_per_file() -> None:
    """Verifies heading-based chunking yields enough retrieval granularity for each synthetic runbook."""

    runbook_dir = Path("sentinelops/simulation/runbooks")
    for file in runbook_dir.glob("*.md"):
        chunks = chunk_runbook(str(file))
        assert len(chunks) >= 3


def test_no_chunk_exceeds_400_tokens() -> None:
    """Verifies chunk refinement keeps token estimates under model-friendly retrieval threshold."""

    runbook_dir = Path("sentinelops/simulation/runbooks")
    for file in runbook_dir.glob("*.md"):
        chunks = chunk_runbook(str(file))
        assert all(chunk["token_estimate"] <= 400 for chunk in chunks)


def test_each_chunk_has_required_fields() -> None:
    """Verifies emitted chunk objects include all metadata fields required by indexing pipeline."""

    file = Path("sentinelops/simulation/runbooks/db_latency.md")
    chunks = chunk_runbook(str(file))
    required = {"chunk_id", "source_file", "section_title", "text", "token_estimate"}
    assert chunks
    assert all(required.issubset(set(chunk.keys())) for chunk in chunks)