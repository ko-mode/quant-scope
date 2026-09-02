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
    price_provider: str = "tiingo"  # V1 live provider (ADR 0022)
    default_benchmark_ticker: str = "SPY"

    # SEC EDGAR. SEC's access policy requires a User-Agent identifying the caller
    # with contact info; override this before running against the live service.
    sec_user_agent: str = "QuantScope/0.1 (set QUANTSCOPE_SEC_USER_AGENT)"
    sec_company_tickers_url: str = "https://www.sec.gov/files/company_tickers_exchange.json"

    # Tiingo - V1 live daily-price provider (ADR 0022). The token is required for
    # any live fetch; it must never be committed. Free token: https://www.tiingo.com
    tiingo_api_token: str = ""
    tiingo_base_url: str = "https://api.tiingo.com"

    # Stooq daily price CSV endpoint. Retained as a second DailyPriceProvider
    # implementation / offline parser; its live endpoint is anti-bot gated (ADR 0022).
    stooq_base_url: str = "https://stooq.com/q/d/l/"

    # CORS origins allowed to call the API (the Next.js dev server by default).
    cors_allow_origins: tuple[str, ...] = ("http://localhost:3000",)

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
