import asyncio
import json
import logging
import re
from google import genai
from google.genai import types
from sentinelops.config import settings
from sentinelops.schemas.incident import GroupingOutput

logger = logging.getLogger(__name__)

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

        try:
            response = self.client.models.generate_content(
                model="gemma-3-27b-it",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=2048,
                ),
            )
        except Exception as exc:
            raise LLMFallbackRequired(str(exc)) from exc

        return response.text or ""

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

    async def group_incidents(self, structured_events: list[dict]) -> GroupingOutput:
        """Groups structured events with one retry-on-malformed policy before requiring fallback mode."""

        prompt = self._build_user_prompt(structured_events)

        try:
            first = await asyncio.wait_for(
                asyncio.to_thread(self._generate, prompt), timeout=30.0
            )
            return self._parse_grouping_output(first)
        except Exception as exc:
            logger.exception("Gemini grouping call or parsing failed")
            raise LLMFallbackRequired(str(exc)) from exc