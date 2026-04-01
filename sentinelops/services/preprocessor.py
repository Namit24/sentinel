import logging
from collections import Counter, defaultdict
from datetime import datetime

from sentinelops.schemas.log_entry import RawLogEntryCreate

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"CRITICAL": 4, "ERROR": 3, "WARN": 2, "WARNING": 2, "INFO": 1, "DEBUG": 0}


def _normalize_level(level: str) -> str:
    """Normalizes log level casing so filtering and sorting remain deterministic across sources."""

    return level.strip().upper()


def _infer_error_type(message: str) -> str:
    """Maps free-text log messages into stable categories to reduce prompt entropy for the LLM."""

    lowered = message.lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "latency" in lowered or "slow" in lowered:
        return "latency"
    if "connection" in lowered or "refused" in lowered or "reset" in lowered:
        return "connection"
    if "crash" in lowered or "panic" in lowered or "segfault" in lowered:
        return "crash"
    return "unknown"


def filter_logs(logs: list[RawLogEntryCreate]) -> list[RawLogEntryCreate]:
    """Drops low-signal logs while preserving INFO from unstable services to keep context coverage."""

    if not logs:
        logger.info("Filtered logs: 0 dropped out of 0 total")
        return []

    per_service_total: dict[str, int] = defaultdict(int)
    per_service_errors: dict[str, int] = defaultdict(int)

    for log in logs:
        level = _normalize_level(log.log_level)
        per_service_total[log.service_name] += 1
        if level == "ERROR":
            per_service_errors[log.service_name] += 1

    unstable_services = {
        service
        for service, total in per_service_total.items()
        if total > 0 and (per_service_errors[service] / total) > 0.10
    }

    filtered: list[RawLogEntryCreate] = []
    for log in logs:
        level = _normalize_level(log.log_level)
        if level in {"ERROR", "WARN", "WARNING", "CRITICAL"}:
            filtered.append(log)
            continue
        if level == "INFO" and log.service_name in unstable_services:
            filtered.append(log)

    dropped = len(logs) - len(filtered)
    logger.info("Filtered logs: %s dropped out of %s total", dropped, len(logs))
    return filtered


def deduplicate_logs(logs: list[RawLogEntryCreate]) -> list[dict]:
    """Compresses repeated service errors into 60-second buckets to preserve signal with lower token cost."""

    grouped: dict[tuple[str, str, int], dict] = {}
    ordered = sorted(logs, key=lambda item: item.timestamp)

    for log in ordered:
        bucket = int(log.timestamp.timestamp()) // 60
        key = (log.service_name, log.message, bucket)
        if key not in grouped:
            grouped[key] = {
                "timestamp": log.timestamp,
                "service": log.service_name,
                "log_level": _normalize_level(log.log_level),
                "message": log.message,
                "count": 1,
                "trace_id": log.trace_id,
            }
            continue

        grouped[key]["count"] += 1
        if grouped[key]["trace_id"] is None and log.trace_id is not None:
            grouped[key]["trace_id"] = log.trace_id

    return list(grouped.values())


def structure_for_llm(deduplicated: list[dict]) -> list[dict]:
    """Transforms deduplicated events into compact, typed payloads bounded by model input limits."""

    structured = [
        {
            "timestamp": item["timestamp"].isoformat()
            if isinstance(item["timestamp"], datetime)
            else str(item["timestamp"]),
            "service": item["service"],
            "error_type": _infer_error_type(item["message"]),
            "message": item["message"],
            "count": int(item["count"]),
            "log_level": item.get("log_level", "WARN"),
        }
        for item in deduplicated
    ]

    if len(structured) <= 80:
        return [
            {
                "timestamp": entry["timestamp"],
                "service": entry["service"],
                "error_type": entry["error_type"],
                "message": entry["message"],
                "count": entry["count"],
            }
            for entry in structured
        ]

    structured.sort(
        key=lambda entry: (
            _SEVERITY_RANK.get(_normalize_level(entry["log_level"]), 0),
            entry["count"],
            entry["timestamp"],
        ),
        reverse=True,
    )
    top = structured[:80]
    return [
        {
            "timestamp": entry["timestamp"],
            "service": entry["service"],
            "error_type": entry["error_type"],
            "message": entry["message"],
            "count": entry["count"],
        }
        for entry in top
    ]


def preprocess(logs: list[RawLogEntryCreate]) -> list[dict]:
    """Runs the full deterministic log-preparation pipeline before any model invocation."""

    filtered = filter_logs(logs)
    deduplicated = deduplicate_logs(filtered)
    return structure_for_llm(deduplicated)