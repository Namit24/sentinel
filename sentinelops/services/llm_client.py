import asyncio
import json
import logging

from google import genai
from google.genai import types

from sentinelops.config import settings
from sentinelops.schemas.incident import GroupingOutput

logger = logging.getLogger(__name__)

_OUTPUT_SCHEMA = {
    "result": [
        {
            "group_id": "string",
            "likely_cause": "string",
            "affected_services": ["string"],
            "supporting_events": [{"timestamp": "string", "service": "string"}],
            "confidence_score": 0.0,
        }
    ],
    "confidence_score": 0.0,
    "evidence": ["string"],
    "fallback_used": False,
    "fallback_reason": None,
}


class LLMFallbackRequired(Exception):
    """Signals that upstream orchestration should switch to deterministic rule-based grouping."""


class GeminiClient:
    """Encapsulates all Gemini interactions so model behavior can be changed without API rewrites."""

    def __init__(self) -> None:
        """Initializes the Gemini SDK client with central settings-managed credentials."""

        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def _build_system_prompt(self, strict: bool) -> str:
        """Builds schema-constrained instructions that force machine-parseable JSON-only output."""

        base = (
            "You are an incident-grouping engine. Respond ONLY with valid JSON and no extra text. "
            "No markdown, no preamble, no explanation. Output must match this exact schema: "
            f"{json.dumps(_OUTPUT_SCHEMA)}"
        )
        if strict:
            return (
                base
                + " If output cannot be produced, still return valid schema with empty result and confidence_score 0.0."
            )
        return base

    def _generate(self, prompt: str, strict: bool) -> str:
        """Calls Gemini synchronously so async wrappers can centralize retry and parse behavior."""

        response = self.client.models.generate_content(
            model="gemma-3-27b-it",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=2048,
                system_instruction=self._build_system_prompt(strict=strict),
            ),
        )
        return response.text or ""

    def _parse_grouping_output(self, payload: str) -> GroupingOutput:
        """Validates model JSON against strict schema so API consumers never receive raw model text."""

        return GroupingOutput.model_validate_json(payload)

    async def group_incidents(self, structured_events: list[dict]) -> GroupingOutput:
        """Groups structured events with one retry-on-malformed policy before requiring fallback mode."""

        prompt = (
            "Group these structured telemetry events into incident clusters and provide evidence. "
            "Structured events JSON: "
            f"{json.dumps(structured_events)}"
        )

        try:
            first = await asyncio.wait_for(
                asyncio.to_thread(self._generate, prompt, False), timeout=12.0
            )
        except Exception as exc:
            logger.exception("Gemini API call failed on first attempt")
            raise LLMFallbackRequired(str(exc)) from exc

        try:
            return self._parse_grouping_output(first)
        except Exception:
            logger.warning("Gemini returned malformed JSON; retrying with strict prompt")

        retry_prompt = (
            "Return STRICT JSON matching the provided schema. Do not include markdown or text. "
            "Events: "
            f"{json.dumps(structured_events)}"
        )
        try:
            second = await asyncio.wait_for(
                asyncio.to_thread(self._generate, retry_prompt, True), timeout=12.0
            )
            return self._parse_grouping_output(second)
        except Exception as exc:
            logger.exception("Gemini failed to return valid JSON after retry")
            raise LLMFallbackRequired("Malformed or unavailable LLM response") from exc