import logging
from collections import Counter, defaultdict

from sentinelops.schemas.incident import GroupingOutput, IncidentGroup

logger = logging.getLogger(__name__)


def rule_based_grouping(structured_events: list[dict]) -> GroupingOutput:
    """Provides a guaranteed grouping result when the LLM path is unavailable or malformed."""

    try:
        grouped_by_service: dict[str, list[dict]] = defaultdict(list)
        for event in structured_events:
            service = str(event.get("service", "unknown-service"))
            grouped_by_service[service].append(event)

        result: list[IncidentGroup] = []
        for index, (service, events) in enumerate(grouped_by_service.items(), start=1):
            error_counts = Counter(str(event.get("error_type", "unknown")) for event in events)
            likely_cause = error_counts.most_common(1)[0][0] if error_counts else "unknown"
            result.append(
                IncidentGroup(
                    group_id=f"fallback-{index}",
                    likely_cause=likely_cause,
                    affected_services=[service],
                    supporting_events=events,
                    confidence_score=0.3,
                )
            )

        evidence = [f"Rule grouping for service={service}" for service in grouped_by_service.keys()]
        return GroupingOutput(
            result=result,
            confidence_score=0.3,
            evidence=evidence,
            fallback_used=True,
            fallback_reason="LLM unavailable or returned malformed output",
        )
    except Exception:
        logger.exception("Rule-based fallback encountered an unexpected error; returning minimal safe output")
        return GroupingOutput(
            result=[],
            confidence_score=0.3,
            evidence=["Emergency fallback path"],
            fallback_used=True,
            fallback_reason="LLM unavailable or returned malformed output",
        )