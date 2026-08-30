"""Liveness probe.

Intentionally does not touch the database: it reports only that the API process
is up. A readiness check that verifies the database connection will be added
alongside the first migration in Phase 1.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from quantscope import __version__

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="quantscope-api", version=__version__)
