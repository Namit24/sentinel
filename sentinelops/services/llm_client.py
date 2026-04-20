import asyncio
import json
import logging
import re
from time import perf_counter

from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from sentinelops.config import settings
from sentinelops.models.prompt_run import PromptRun
from sentinelops.schemas.incident import GroupingOutput
from sentinelops.services.llm_guard import LLMCircuitOpen, get_breaker

logger = logging.getLogger(__name__)
PROMPT_VERSION = "v2"
GROUPING_MODEL_NAME = "gemma-4-31b-it"

GROUPING_SYSTEM_PROMPT = """You are an enterprise incident triage system.
Your only job is to group related error events into incident clusters.

CRITICAL RULES — follow all of them exactly:
1. Return ONLY a valid JSON object. Nothing else.
2. Do NOT include any text before or after the JSON.
3. Do NOT use markdown code fences (no ```json).
4. Do NOT explain your reasoning.
5. Do NOT add comments inside the JSON.
6. Every string value must use double quotes.
7. confidence_score must be a float between 0.0 and 1.0.

The JSON object you return must match this exact structure:
{
    "groups": [
        {
            "group_id": "incident-1",
            "likely_cause": "short description of root cause",
            "affected_services": ["service-a", "service-b"],
            "supporting_events": [
                {"service": "service-a", "error_type": "timeout", "count": 5},
                {"service": "service-b", "error_type": "latency", "count": 3}
            ],
            "confidence_score": 0.85
        }
    ]
}

Grouping rules:
- Events from the same failure cascade belong in one group
- Unrelated errors from different services are separate groups
- If all events are related, return one group
- supporting_events should list the most significant events only (max 5 per group)
"""

FEW_SHOT_EXAMPLE = """EXAMPLE INPUT:
[
    {"timestamp": "2024-01-01T10:00:00", "service": "db-primary", "error_type": "latency", "message": "Query timeout exceeded 5000ms", "count": 12},
    {"timestamp": "2024-01-01T10:01:00", "service": "payment-service", "error_type": "timeout", "message": "Upstream db-primary not responding", "count": 8},
    {"timestamp": "2024-01-01T10:02:00", "service": "api-gateway", "error_type": "timeout", "message": "Payment service returning 503", "count": 15}
]

EXAMPLE OUTPUT:
{"groups":[{"group_id":"incident-1","likely_cause":"db-primary latency spike causing cascade","affected_services":["db-primary","payment-service","api-gateway"],"supporting_events":[{"service":"db-primary","error_type":"latency","count":12},{"service":"payment-service","error_type":"timeout","count":8},{"service":"api-gateway","error_type":"timeout","count":15}],"confidence_score":0.92}]}

NOW PROCESS THIS INPUT:
"""


class LLMFallbackRequired(Exception):
    """Signals that upstream orchestration should switch to deterministic rule-based grouping."""


class GeminiClient:
    """Encapsulates all Gemini interactions so model behavior can be changed without API rewrites."""

    def __init__(self) -> None:
        """Initializes the Gemini SDK client with central settings-managed credentials."""

        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def _compact_events(self, structured_events: list[dict]) -> list[dict]:
        """Compresses events to a small high-signal subset to reduce token pressure on free-tier quotas."""

        ranked = sorted(
            structured_events,
            key=lambda event: float(event.get("count", 0)),
            reverse=True,
        )
        compact: list[dict] = []
        seen_signatures: set[tuple[str, str, str]] = set()
        for event in ranked:
            service = str(event.get("service", "unknown"))
            error_type = str(event.get("error_type", "unknown"))
            message = str(event.get("message", ""))
            signature = (service, error_type, message[:80])
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            compact.append(
                {
                    "timestamp": event.get("timestamp"),
                    "service": service,
                    "error_type": error_type,
                    "message": message[:120],
                    "count": int(event.get("count", 1)),
                }
            )
            if len(compact) >= 20:
                break
        return compact

    def _build_user_prompt(self, structured_events: list[dict]) -> str:
        """Constructs a few-shot guided prompt to reduce ambiguity and increase JSON-compliant grouping output."""

        compact_events = self._compact_events(structured_events)
        return GROUPING_SYSTEM_PROMPT + "\n\n" + FEW_SHOT_EXAMPLE + json.dumps(compact_events, indent=2)

    def _extract_json(self, text: str) -> dict:
        """Extracts a JSON object from model output using progressively tolerant parsing strategies."""

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        cleaned = re.sub(r"```json\s*|\s*```", "", text).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        raise LLMFallbackRequired(f"Could not extract valid JSON from response: {text[:200]}")

    def _generate(self, prompt: str) -> str:
        """Calls Gemini synchronously so async wrappers can centralize retry and parse behavior."""

        def _call_json_mode() -> str:
            response = self.client.models.generate_content(
                model=GROUPING_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    max_output_tokens=2048,
                ),
            )
            return response.text or ""

        def _call_plain_mode() -> str:
            response = self.client.models.generate_content(
                model=GROUPING_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=2048,
                ),
            )
            return response.text or ""

        try:
            return _call_json_mode()
        except Exception as exc:
            message = str(exc)
            if "JSON mode is not enabled" in message:
                logger.warning(
                    "Gemini JSON mode unavailable for grouping model; retrying without response_mime_type"
                )
                try:
                    return _call_plain_mode()
                except Exception as retry_exc:
                    raise LLMFallbackRequired(str(retry_exc)) from retry_exc
            raise LLMFallbackRequired(message) from exc

    def _parse_grouping_output(self, payload: str) -> GroupingOutput:
        """Validates model JSON against strict schema so API consumers never receive raw model text."""

        parsed = self._extract_json(payload)
        groups = parsed.get("groups")
        if groups is None and parsed.get("group_id"):
            groups = [parsed]
        if not isinstance(groups, list):
            raise LLMFallbackRequired("Response JSON did not include a valid groups array")

        confidence_values = [
            float(group.get("confidence_score", 0.0))
            for group in groups
            if isinstance(group, dict)
        ]
        mean_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0

        normalized = {
            "result": groups,
            "confidence_score": float(min(max(mean_confidence, 0.0), 1.0)),
            "evidence": [
                f"Grouped {len(groups)} incident cluster(s) from preprocessed telemetry with Gemini."
            ],
            "fallback_used": False,
            "fallback_reason": None,
        }
        return GroupingOutput.model_validate(normalized)

    async def _log_prompt_run(
        self,
        *,
        db: AsyncSession,
        input_token_estimate: int,
        output_token_estimate: int,
        latency_ms: float,
        confidence_score: float,
        fallback_used: bool,
        fallback_reason: str | None,
        success: bool,
    ) -> None:
        """Persists one prompt run using a nested transaction so logging failures never break grouping."""

        try:
            async with db.begin_nested():
                db.add(
                    PromptRun(
                        incident_id=None,
                        prompt_version=PROMPT_VERSION,
                        model_name=GROUPING_MODEL_NAME,
                        input_token_estimate=input_token_estimate,
                        output_token_estimate=output_token_estimate,
                        latency_ms=latency_ms,
                        confidence_score=confidence_score,
                        fallback_used=fallback_used,
                        fallback_reason=fallback_reason,
                        success=success,
                    )
                )
        except Exception:
            logger.warning("Failed to record prompt run telemetry", exc_info=True)

    async def group_incidents(self, structured_events: list[dict], db: AsyncSession) -> GroupingOutput:
        """Groups structured events with one retry-on-malformed policy before requiring fallback mode."""

        prompt = self._build_user_prompt(structured_events)
        input_token_estimate = len(prompt) // 4
        started = perf_counter()
        breaker = get_breaker("grouping")

        try:
            breaker.ensure_available()
            first = await asyncio.wait_for(
                asyncio.to_thread(self._generate, prompt),
                timeout=settings.GROUPING_TIMEOUT_SECONDS,
            )
            output = self._parse_grouping_output(first)
            await self._log_prompt_run(
                db=db,
                input_token_estimate=input_token_estimate,
                output_token_estimate=len(first) // 4,
                latency_ms=(perf_counter() - started) * 1000.0,
                confidence_score=output.confidence_score,
                fallback_used=False,
                fallback_reason=None,
                success=True,
            )
            breaker.record_success()
            return output
        except LLMCircuitOpen as exc:
            await self._log_prompt_run(
                db=db,
                input_token_estimate=input_token_estimate,
                output_token_estimate=0,
                latency_ms=(perf_counter() - started) * 1000.0,
                confidence_score=0.0,
                fallback_used=True,
                fallback_reason=str(exc),
                success=False,
            )
            raise LLMFallbackRequired(str(exc)) from exc
        except Exception as exc:
            await self._log_prompt_run(
                db=db,
                input_token_estimate=input_token_estimate,
                output_token_estimate=0,
                latency_ms=(perf_counter() - started) * 1000.0,
                confidence_score=0.0,
                fallback_used=True,
                fallback_reason=str(exc),
                success=False,
            )
            breaker.record_failure(str(exc))
            logger.exception("Gemini grouping call or parsing failed")
            raise LLMFallbackRequired(str(exc)) from exc
