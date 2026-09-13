"""Application Configuration Module using Pydantic Settings."""

from functools import lru_cache
from typing import List, Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core Application Settings
    APP_NAME: str = "SAP CDS Intelligence & Automation Platform"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    APP_HOST: str = "127.0.0.1"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # CORS Settings
    CORS_ORIGINS: Union[str, List[str]] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # Database Settings
    # Default to sqlite+aiosqlite for zero-config local development when Postgres is not running
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./platform_dev.db",
        description="Async connection string for database",
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # SAP Environment Metadata (Config only - no direct connection in Milestone 1)
    SAP_CONNECTOR_ENABLED: bool = False
    SAP_CONNECTOR_TYPE: str = "stub"
    SAP_SYSTEM_ID: str = "DEV"
    SAP_CLIENT: str = "100"
    SAP_S4HANA_RELEASE: str = "2023"
    SAP_S4CORE_RELEASE: str = "108 SP03"
    SAP_BASIS_RELEASE: str = "758 SP03"

    # Agent Orchestration Settings
    AGENT_MAX_ITERATIONS: int = 10
    AGENT_TIMEOUT_SECONDS: int = 60


@lru_cache
def get_settings() -> Settings:
    """Returns cached application settings."""
    return Settings()
