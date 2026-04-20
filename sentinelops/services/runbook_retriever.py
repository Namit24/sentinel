import asyncio
import logging

from google import genai
from google.genai import types

from sentinelops.config import settings
from sentinelops.schemas.root_cause import RootCauseReport
from sentinelops.schemas.runbook import RunbookRecommendation
from sentinelops.services.llm_guard import LLMCircuitOpen, get_breaker
from sentinelops.services.vector_store import retrieve_runbook_chunks

logger = logging.getLogger(__name__)


def build_retrieval_query(report: RootCauseReport) -> str:
    """Builds retrieval query text from ranked-cause context so vector search targets relevant SOPs."""

    affected = sorted({service for c in report.candidates[:5] for service in [c.service]})
    services = ", ".join(affected)
    path = " -> ".join(report.graph_path)
    return f"Remediation steps for {report.top_cause} failure. Affected services: {services}. Propagation path: {path}."


async def synthesize_recommendation(report: RootCauseReport, chunks: list[dict]) -> str:
    """Synthesizes cited remediation steps constrained strictly to retrieved runbook excerpts."""

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    services = ", ".join({candidate.service for candidate in report.candidates[:5]})
    path = " -> ".join(report.graph_path)

    excerpts = []
    for index, chunk in enumerate(chunks, start=1):
        excerpts.append(
            f"[chunk {index} source: {chunk['chunk_id']}]\n{chunk['text']}"
        )
    excerpts_blob = "\n\n".join(excerpts)

    user_prompt = (
        "You are a runbook synthesis assistant.\n"
        "Rules:\n"
        "- Only use information present in provided runbook excerpts.\n"
        "- If information is insufficient, say so explicitly.\n"
        "- Do not invent commands, flags, or procedures not in excerpts.\n"
        "- Return a numbered step list.\n"
        "- After each step include citation [source: <chunk_id>].\n\n"
        "Incident context:\n"
        f"- Top cause: {report.top_cause}\n"
        f"- Affected services: {services}\n"
        f"- Confidence: {report.confidence_score}\n"
        f"- Propagation path: {path}\n\n"
        "Relevant runbook excerpts:\n"
        f"{excerpts_blob}\n\n"
        "Based only on the excerpts above, provide step-by-step remediation."
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemma-4-31b-it",
        contents=user_prompt,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=1024,
        ),
    )
    return response.text or ""


def _parse_steps_with_citations(raw_text: str, fallback_chunk: str) -> list[str]:
    """Parses numbered remediation steps and enforces citation suffixes for every output step."""

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    steps: list[str] = []
    for line in lines:
        if line[0].isdigit() or line.startswith("-"):
            if "[source:" not in line:
                line = f"{line} [source: {fallback_chunk}]"
            steps.append(line)
    if steps:
        return steps
    if not raw_text.strip():
        return [f"1. Insufficient runbook evidence found. [source: {fallback_chunk}]"]
    normalized = raw_text.strip()
    if "[source:" not in normalized:
        normalized = f"{normalized} [source: {fallback_chunk}]"
    return [f"1. {normalized}" if not normalized[:1].isdigit() else normalized]


async def get_runbook_recommendation(report: RootCauseReport, db) -> RunbookRecommendation:
    """Retrieves relevant runbook chunks and returns grounded remediation guidance with citations."""

    query = build_retrieval_query(report)
    chunks = await retrieve_runbook_chunks(query_text=query, db=db, top_k=5)

    if not chunks:
        return RunbookRecommendation(
            incident_id=report.incident_id,
            top_cause=report.top_cause,
            steps=[],
            source_chunks=[],
            source_files=[],
            confidence_score=0.0,
            grounded=False,
            raw_synthesis="Runbook index is empty. Run /admin/index-runbooks first.",
        )

    try:
        breaker = get_breaker("runbook_synthesis")
        breaker.ensure_available()
        raw = await asyncio.wait_for(
            synthesize_recommendation(report=report, chunks=chunks),
            timeout=settings.RUNBOOK_SYNTHESIS_TIMEOUT_SECONDS,
        )
        breaker.record_success()
    except LLMCircuitOpen:
        logger.warning("Runbook synthesis breaker open; using excerpt-grounded fallback")
        fallback_lines = [
            f"{idx}. Review section '{chunk['section_title']}' in {chunk['source_file']} [source: {chunk['chunk_id']}]"
            for idx, chunk in enumerate(chunks, start=1)
        ]
        raw = "\n".join(fallback_lines)
    except Exception:
        get_breaker("runbook_synthesis").record_failure("synthesis_failed")
        logger.exception("Runbook synthesis failed; returning excerpt-grounded fallback recommendation")
        fallback_lines = [
            f"{idx}. Review section '{chunk['section_title']}' in {chunk['source_file']} [source: {chunk['chunk_id']}]"
            for idx, chunk in enumerate(chunks, start=1)
        ]
        raw = "\n".join(fallback_lines)

    source_chunks = [chunk["chunk_id"] for chunk in chunks]
    source_files = sorted({chunk["source_file"] for chunk in chunks})
    avg_similarity = sum(float(chunk["similarity_score"]) for chunk in chunks) / max(len(chunks), 1)
    steps = _parse_steps_with_citations(raw, fallback_chunk=source_chunks[0])
    return RunbookRecommendation(
        incident_id=report.incident_id,
        top_cause=report.top_cause,
        steps=steps,
        source_chunks=source_chunks,
        source_files=source_files,
        confidence_score=max(0.0, min(1.0, avg_similarity)),
        grounded=avg_similarity > 0.0,
        raw_synthesis=raw,
    )
