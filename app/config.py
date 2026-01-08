"""Application configuration pulled from environment variables via pydantic."""
import os
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from utils.logging_utils import get_tagged_logger
logger = get_tagged_logger(__name__, tag="forecast_service")


class Settings(BaseSettings):
    """Environment-driven configuration for the ai-cycling-agent service."""
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore")

    forecast_source: str = "open_meteo"  # options: open_meteo, postgres
    forecast_database_url: str = "sqlite:///./test.db"
    api_key: str | None = None
    api_key_redis_url: str | None = None
    api_key_redis_set: str = "api_keys"
    session_redis_url: str | None = None
    session_ttl_seconds: int = 3600
    conditions_ttl_seconds: int = 900
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "phi4-mini"
    forecast_days: int = 7
    forecast_hours: int = 12
    max_user_message_chars: int = 4000
    ollama_options: dict = Field(
        default_factory=lambda: {
            "temperature": float(os.getenv("AGENT_OLLAMA_TEMPERATURE", 0.2)),
            "top_p": float(os.getenv("AGENT_OLLAMA_TOP_P", 0.9)),
            "repeat_penalty": float(os.getenv("AGENT_OLLAMA_REPEAT_PENALTY", 1.1)),
        }
    )

    @field_validator("ollama_base_url", mode="after")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        """Normalize base URLs to avoid double slashes."""
        return str(v).rstrip("/")


settings = Settings()


if __name__ == "__main__":
    import json
    logger.setLevel("DEBUG")
    logger.debug(f"Loaded settings: {settings.model_dump_json(indent=4)}")
