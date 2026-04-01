from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central config loaded from environment variables.
    Pydantic-settings validates types and raises early if required vars are missing.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    GEMINI_API_KEY: str
    DATABASE_URL: str
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"


settings = Settings()