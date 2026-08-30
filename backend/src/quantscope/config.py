"""Application configuration.

All settings are read from the environment (prefix ``QUANTSCOPE_``) with
development-friendly defaults so the app and Alembic can start without a
``.env`` file. ``get_settings`` is cached so settings are read once per process.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="QUANTSCOPE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"

    # SQLAlchemy 2.0 URL. psycopg (v3) driver.
    database_url: str = "postgresql+psycopg://quantscope:quantscope@localhost:5432/quantscope"

    # Market-data configuration (consumed from Phase 1 onward).
    price_provider: str = "stooq"
    default_benchmark_ticker: str = "SPY"

    # CORS origins allowed to call the API (the Next.js dev server by default).
    cors_allow_origins: tuple[str, ...] = ("http://localhost:3000",)

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
