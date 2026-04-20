import logging
from collections import defaultdict
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


def _direct_evidence_scores(grouping_output: GroupingOutput) -> dict[str, float]:
    """Scores services by direct textual and event evidence so shared dependencies do not dominate ranking."""

    scores: dict[str, float] = {node: 0.0 for node in GRAPH.nodes}

    for group in grouping_output.result:
        group_services = [service for service in group.affected_services if service in scores]
        likely_text = group.likely_cause.lower()
        group_weight = max(0.2, float(group.confidence_score))

        if len(group_services) == 1:
            scores[group_services[0]] += 1.4 * group_weight

        for service in group_services:
            if service.lower() in likely_text:
                scores[service] += 1.6 * group_weight

        per_service_event_counts: dict[str, float] = defaultdict(float)
        for event in group.supporting_events:
            if not isinstance(event, dict):
                continue
            service = str(event.get("service", "")).strip()
            if service not in scores:
                continue
            count = float(event.get("count", 1) or 1)
            per_service_event_counts[service] += max(1.0, min(count, 12.0))

        for service, count in per_service_event_counts.items():
            scores[service] += 0.22 * count * group_weight

    maximum = max(scores.values()) if scores else 0.0
    if maximum <= 0.0:
        return {service: 0.0 for service in GRAPH.nodes}
    return {service: round(value / maximum, 6) for service, value in scores.items()}


def _similarity_gate(service: str, direct_scores: dict[str, float]) -> bool:
    """Restricts historical similarity boosts to services that already have strong direct incident evidence."""

    max_direct = max(direct_scores.values()) if direct_scores else 0.0
    if max_direct <= 0.0:
        return False
    service_direct = direct_scores.get(service, 0.0)
    return service_direct >= max(0.25, max_direct * 0.60)


def _calibrated_confidence(
    candidates: list[RootCauseCandidate],
    analysis_method: str,
) -> float:
    """Produces conservative confidence so graph-only rankings do not look more certain than they are."""

    if not candidates:
        return 0.0

    top_score = candidates[0].combined_score
    second_score = candidates[1].combined_score if len(candidates) > 1 else 0.0
    margin = max(0.0, min(1.0, top_score - second_score))
    margin_factor = 0.70 + (0.30 * margin)
    method_factor = 0.85 if analysis_method == "graph_only" else 1.0
    return round(max(0.0, min(1.0, top_score * margin_factor * method_factor)), 6)


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
    direct_scores = _direct_evidence_scores(grouping_output)

    analysis_method = "graph+vector"
    similarity_boost: dict[str, float] = {service: 0.0 for service in GRAPH.nodes}
    similar_ids_by_service: dict[str, list[str]] = {service: [] for service in GRAPH.nodes}

    text = incident_text_from_parts(
        affected_services=affected_services,
        top_cause_service=None,
        group_data=grouping_output.model_dump(),
    )
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
                if not _similarity_gate(service, direct_scores):
                    continue
                similarity_boost[service] += 1.0 / total
                similar_ids_by_service[service].append(str(incident.id))
    except Exception:
        logger.exception("Similarity retrieval failed; continuing with graph-only ranking")
        analysis_method = "graph_only"

    ranked = []
    for service, graph_score in blame_scores.items():
        direct_score = max(0.0, min(1.0, direct_scores.get(service, 0.0)))
        similarity_score = max(0.0, min(1.0, similarity_boost.get(service, 0.0)))
        combined = (0.55 * graph_score) + (0.30 * direct_score) + (0.15 * similarity_score)
        ranked.append((service, graph_score, direct_score, similarity_score, combined))

    ranked.sort(key=lambda row: row[4], reverse=True)

    candidates: list[RootCauseCandidate] = []
    for index, (service, graph_score, direct_score, similarity_score, combined_score) in enumerate(
        ranked, start=1
    ):
        evidence = [
            f"Graph propagation score={graph_score:.3f}",
            f"Direct incident evidence score={direct_score:.3f}",
            f"Similarity support score={similarity_score:.3f}",
        ]
        if service in graph_path:
            evidence.append("Service appears on highest-likelihood propagation path")
        if direct_score >= 0.6:
            evidence.append("Service is strongly supported by grouped cause text or supporting events")
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
        confidence_score=_calibrated_confidence(candidates, analysis_method),
        graph_path=graph_path or [top.service],
        analysis_method=analysis_method,
    )
