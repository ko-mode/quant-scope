"""FastAPI application factory.

``GET /health`` is a liveness probe. Phase 1E adds the read-only securities and
price-history routes under ``/securities``, served at the root like ``/health``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quantscope import __version__
from quantscope.api.routers import health, securities
from quantscope.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="QuantScope API",
        version=__version__,
        summary="Quantitative equity research platform",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allow_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(securities.router)

    return app


app = create_app()
