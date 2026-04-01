import logging

from sentinelops.schemas.incident import GroupingOutput
from sentinelops.schemas.log_entry import RawLogEntryCreate
from sentinelops.services.llm_client import GeminiClient, LLMFallbackRequired
from sentinelops.services.preprocessor import preprocess
from sentinelops.utils.fallbacks import rule_based_grouping

logger = logging.getLogger(__name__)


async def group_telemetry(logs: list[RawLogEntryCreate]) -> GroupingOutput:
    """Coordinates deterministic preprocessing and resilient grouping so ingestion always returns safely."""

    structured = preprocess(logs)
    if not structured:
        return GroupingOutput(
            result=[],
            confidence_score=0.0,
            evidence=[],
            fallback_used=False,
            fallback_reason=None,
        )

    try:
        return await GeminiClient().group_incidents(structured)
    except LLMFallbackRequired as exc:
        logger.warning("LLM fallback triggered: %s", exc)
        return rule_based_grouping(structured)