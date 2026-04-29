"""Application settings loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the admin service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Security
    jwt_secret: str = Field(default="change-me", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 1 day
    cookie_name: str = "voices_session"

    # Database
    database_url: str = Field(
        default="sqlite:////data/voices.db", alias="DATABASE_URL"
    )

    # Redis
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # Downstream services
    fuseki_url: str = Field(default="http://fuseki:3030/voices", alias="FUSEKI_URL")
    meilisearch_url: str = Field(
        default="http://meilisearch:7700", alias="MEILISEARCH_URL"
    )
    meilisearch_key: str = Field(default="", alias="MEILISEARCH_KEY")

    # Behavior
    require_auth: bool = Field(default=True, alias="REQUIRE_AUTH")

    # Seed
    admin_email: str = Field(default="admin@example.com", alias="ADMIN_EMAIL")
    admin_password: str = Field(default="changeme", alias="ADMIN_PASSWORD")

    # Public URL (for redirects)
    public_base_url: str = Field(
        default="https://localhost:8443", alias="PUBLIC_BASE_URL"
    )

    # Rate limiting
    rate_limit_per_minute: int = 60

    # Data paths
    output_dir: str = "/output"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
