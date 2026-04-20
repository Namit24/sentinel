from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """
    Central config loaded from environment variables.
    Pydantic-settings validates types and raises early if required vars are missing.
    """

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
    )

    GEMINI_API_KEY: str
    DATABASE_URL: str
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    GROUPING_MODEL: str = "gemma-3-27b-it"
    RUNBOOK_SYNTHESIS_MODEL: str = "gemma-3-27b-it"
    GROUPING_TIMEOUT_SECONDS: float = 25.0
    RUNBOOK_SYNTHESIS_TIMEOUT_SECONDS: float = 15.0
    GROUPING_MAX_EVENTS: int = 12
    GROUPING_MESSAGE_CHAR_LIMIT: int = 72
    LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = 3
    LLM_CIRCUIT_BREAKER_RESET_SECONDS: int = 120
    POLICY_ALLOW_CONFIDENCE_THRESHOLD: float = 0.85
    POLICY_REVIEW_CONFIDENCE_THRESHOLD: float = 0.60
    POLICY_BLOCK_ON_UNGROUNDED_RUNBOOK: bool = True


settings = Settings()
