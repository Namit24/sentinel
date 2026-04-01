import hashlib
import logging
from types import SimpleNamespace
from uuid import UUID

from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.models.incident import Incident

logger = logging.getLogger(__name__)

try:
    _model = SentenceTransformer("all-MiniLM-L6-v2")
except Exception:
    logger.exception("SentenceTransformer model load failed; using deterministic embedding fallback")
    _model = None


def incident_to_text(incident) -> str:
    """
    Convert incident data to a plain text summary for embedding.
    Captures affected services and likely causes without raw log noise.
    """

    services = ", ".join(incident.affected_services or [])
    cause = incident.top_cause_service or "unknown"
    return f"Services affected: {services}. Top cause: {cause}."


def incident_text_from_parts(affected_services: list[str], top_cause_service: str | None) -> str:
    """Builds an embed-ready summary before root-cause ranking exists for the incident record."""

    proxy = SimpleNamespace(affected_services=affected_services, top_cause_service=top_cause_service)
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