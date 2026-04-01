import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.schemas.incident import GroupingOutput
from sentinelops.schemas.root_cause import RootCauseCandidate, RootCauseReport
from sentinelops.services.graph_engine import (
    GRAPH,
    extract_propagation_path,
    propagate_blame,
    score_anomalous_nodes,
)
from sentinelops.services.vector_store import (
    embed_incident,
    find_similar_incidents,
    incident_text_from_parts,
)

logger = logging.getLogger(__name__)


def _affected_services_from_grouping(grouping_output: GroupingOutput) -> list[str]:
    """Extracts stable affected-service set from grouping output so graph scoring uses deduplicated nodes."""

    services = {
        service.strip()
        for group in grouping_output.result
        for service in group.affected_services
        if isinstance(service, str) and service.strip()
    }
    return sorted(services)


async def rank_root_causes(
    incident_id: str,
    grouping_output: GroupingOutput,
    db: AsyncSession,
) -> RootCauseReport:
    """Ranks root-cause candidates by combining dependency propagation with vector similarity evidence."""

    affected_services = _affected_services_from_grouping(grouping_output)
    anomaly_scores = score_anomalous_nodes(affected_services, GRAPH)
    blame_scores = propagate_blame(anomaly_scores, GRAPH)
    graph_path = extract_propagation_path(blame_scores, GRAPH)

    analysis_method = "graph+vector"
    similarity_boost: dict[str, float] = {service: 0.0 for service in GRAPH.nodes}
    similar_ids_by_service: dict[str, list[str]] = {service: [] for service in GRAPH.nodes}

    text = incident_text_from_parts(affected_services=affected_services, top_cause_service=None)
    query_embedding = embed_incident(text)
    current_uuid = UUID(incident_id)
    try:
        similar_incidents = await find_similar_incidents(
            embedding=query_embedding,
            db=db,
            top_k=3,
            current_incident_id=current_uuid,
        )
        if not similar_incidents:
            analysis_method = "graph_only"
        else:
            total = len(similar_incidents)
            for incident in similar_incidents:
                if not incident.top_cause_service:
                    continue
                service = incident.top_cause_service
                if service not in similarity_boost:
                    continue
                similarity_boost[service] += 1.0 / total
                similar_ids_by_service[service].append(str(incident.id))
    except Exception:
        logger.exception("Similarity retrieval failed; continuing with graph-only ranking")
        analysis_method = "graph_only"

    ranked = []
    for service, graph_score in blame_scores.items():
        similarity_score = max(0.0, min(1.0, similarity_boost.get(service, 0.0)))
        combined = (0.7 * graph_score) + (0.3 * similarity_score)
        ranked.append((service, graph_score, similarity_score, combined))

    ranked.sort(key=lambda row: row[3], reverse=True)

    candidates: list[RootCauseCandidate] = []
    for index, (service, graph_score, similarity_score, combined_score) in enumerate(ranked, start=1):
        evidence = [
            f"Graph propagation score={graph_score:.3f}",
            f"Similarity support score={similarity_score:.3f}",
        ]
        if service in graph_path:
            evidence.append("Service appears on highest-likelihood propagation path")
        if similar_ids_by_service.get(service):
            evidence.append("Matched top cause in similar historical incident(s)")

        candidates.append(
            RootCauseCandidate(
                service=service,
                graph_score=round(graph_score, 6),
                similarity_score=round(similarity_score, 6),
                combined_score=round(max(0.0, min(1.0, combined_score)), 6),
                rank=index,
                evidence=evidence,
                similar_incident_ids=similar_ids_by_service.get(service, []),
            )
        )

    if not candidates:
        return RootCauseReport(
            incident_id=incident_id,
            candidates=[],
            top_cause="unknown",
            confidence_score=0.0,
            graph_path=[],
            analysis_method="graph_only",
        )

    top = candidates[0]
    return RootCauseReport(
        incident_id=incident_id,
        candidates=candidates,
        top_cause=top.service,
        confidence_score=top.combined_score,
        graph_path=graph_path or [top.service],
        analysis_method=analysis_method,
    )