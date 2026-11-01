"""Application settings, read from the environment or a local .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from complianceops.rag.embeddings import MINILM


class Settings(BaseSettings):
    """Runtime configuration. Variables use the ``COMPLIANCEOPS_`` prefix."""

    model_config = SettingsConfigDict(env_prefix="COMPLIANCEOPS_", env_file=".env", extra="ignore")

    max_upload_bytes: int = 50 * 1024 * 1024
    qdrant_url: str = "http://localhost:6333"
    embedding_model: str = MINILM


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()
