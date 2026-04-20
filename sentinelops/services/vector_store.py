import hashlib
import logging
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.models.incident import Incident
from sentinelops.models.runbook_chunk import RunbookChunk
from sentinelops.services.runbook_chunker import load_all_runbooks

logger = logging.getLogger(__name__)

_RUNBOOK_DIR = str(Path(__file__).resolve().parents[1] / "simulation" / "runbooks")

try:
    _model = SentenceTransformer("all-MiniLM-L6-v2")
except Exception:
    logger.exception("SentenceTransformer model load failed; using deterministic embedding fallback")
    _model = None


def _incident_group_summaries(group_data: dict | None) -> tuple[list[str], list[str]]:
    """Extracts likely-cause phrases and error types from grouped telemetry for richer embeddings."""

    if not isinstance(group_data, dict):
        return [], []

    likely_causes: list[str] = []
    error_types: list[str] = []
    for group in group_data.get("result") or []:
        if isinstance(group, dict):
            cause = group.get("likely_cause")
            if isinstance(cause, str) and cause.strip():
                likely_causes.append(cause.strip())
            for event in group.get("supporting_events") or []:
                if isinstance(event, dict):
                    error_type = event.get("error_type")
                    if isinstance(error_type, str) and error_type.strip():
                        error_types.append(error_type.strip())
    return likely_causes, sorted(set(error_types))


def incident_to_text(incident) -> str:
    """
    Convert incident data to a plain text summary for embedding.
    Captures affected services and likely causes without raw log noise.
    """

    services = ", ".join(incident.affected_services or [])
    cause = incident.top_cause_service or "unknown"
    group_data = getattr(incident, "group_data", None)
    likely_causes, error_types = _incident_group_summaries(group_data if isinstance(group_data, dict) else None)
    cause_text = "; ".join(likely_causes[:3]) if likely_causes else "none"
    error_text = ", ".join(error_types[:6]) if error_types else "none"
    return (
        f"Services affected: {services}. "
        f"Grouped causes: {cause_text}. "
        f"Observed error types: {error_text}. "
        f"Top cause: {cause}."
    )


def incident_text_from_parts(
    affected_services: list[str],
    top_cause_service: str | None,
    group_data: dict | None = None,
) -> str:
    """Builds an embed-ready summary before root-cause ranking exists for the incident record."""

    proxy = SimpleNamespace(
        affected_services=affected_services,
        top_cause_service=top_cause_service,
        group_data=group_data,
    )
    return incident_to_text(proxy)


def embed_incident(text: str) -> list[float]:
    """Encodes incident summary text into a 384-dim vector for pgvector cosine similarity search."""

    if _model is not None:
        encoded = _model.encode(text, normalize_embeddings=True)
        return encoded.tolist()

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    seed = [((byte / 255.0) * 2.0) - 1.0 for byte in digest]
    repeated = (seed * ((384 // len(seed)) + 1))[:384]
    return repeated


async def find_similar_incidents(
    embedding: list[float],
    db: AsyncSession,
    top_k: int = 3,
    current_incident_id: UUID | None = None,
) -> list[Incident]:
    """Finds nearest historical incidents by cosine distance while excluding the current incident."""

    stmt = select(Incident).where(Incident.embedding.isnot(None))
    if current_incident_id is not None:
        stmt = stmt.where(Incident.id != current_incident_id)
    stmt = stmt.order_by(Incident.embedding.cosine_distance(embedding)).limit(top_k)
    result = await db.scalars(stmt)
    return result.all()


async def index_runbooks(db: AsyncSession) -> int:
    """Embeds and upserts all runbook chunks so retrieval remains idempotent across repeated indexing runs."""

    chunks = load_all_runbooks(_RUNBOOK_DIR)
    indexed = 0
    for index, chunk in enumerate(chunks, start=1):
        embedding = embed_incident(chunk["text"])
        stmt = insert(RunbookChunk).values(
            chunk_id=chunk["chunk_id"],
            source_file=chunk["source_file"],
            section_title=chunk["section_title"],
            text=chunk["text"],
            token_estimate=chunk["token_estimate"],
            embedding=embedding,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=[RunbookChunk.chunk_id])
        result = await db.execute(stmt)
        if result.rowcount and result.rowcount > 0:
            indexed += 1
        if index % 10 == 0:
            logger.info("Runbook indexing progress: %d/%d", index, len(chunks))
    await db.commit()
    return indexed


async def retrieve_runbook_chunks(
    query_text: str, db: AsyncSession, top_k: int = 5
) -> list[dict]:
    """Retrieves top-k runbook chunks by cosine similarity and returns normalized scoring metadata."""

    embedding = embed_incident(query_text)
    lower_query = query_text.lower()
    source_boost = {
        "db_latency.md": 0.0,
        "payment_timeout.md": 0.0,
        "api_gateway_503.md": 0.0,
        "cache_stampede.md": 0.0,
        "auth_outage.md": 0.0,
    }
    if "db-primary" in lower_query or "db primary" in lower_query:
        source_boost["db_latency.md"] += 0.2
    if "payment-service" in lower_query or "payment service" in lower_query:
        source_boost["payment_timeout.md"] += 0.15
    if "api-gateway" in lower_query or "gateway" in lower_query:
        source_boost["api_gateway_503.md"] += 0.12
    if "cache-service" in lower_query or "cache" in lower_query:
        source_boost["cache_stampede.md"] += 0.1
    if "auth-service" in lower_query or "auth" in lower_query:
        source_boost["auth_outage.md"] += 0.1

    stmt = (
        select(
            RunbookChunk,
            RunbookChunk.embedding.cosine_distance(embedding).label("distance"),
        )
        .order_by(RunbookChunk.embedding.cosine_distance(embedding))
        .limit(max(top_k, 500))
    )
    rows = (await db.execute(stmt)).all()
    rescored: list[dict] = []
    for chunk, distance in rows:
        similarity = 1.0 - float(distance)
        boosted = max(0.0, min(1.0, similarity + source_boost.get(chunk.source_file, 0.0)))
        rescored.append(
            {
                "chunk_id": chunk.chunk_id,
                "source_file": chunk.source_file,
                "section_title": chunk.section_title,
                "text": chunk.text,
                "similarity_score": boosted,
            }
        )
    rescored.sort(key=lambda item: item["similarity_score"], reverse=True)
    selected = rescored[:top_k]

    if ("db-primary" in lower_query or "db primary" in lower_query) and not any(
        item["source_file"] == "db_latency.md" for item in selected
    ):
        fallback = next((item for item in rescored if item["source_file"] == "db_latency.md"), None)
        if fallback is not None:
            if len(selected) < top_k:
                selected.append(fallback)
            else:
                selected[-1] = fallback

    return selected
