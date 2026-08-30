"""Engine and session factory.

Synchronous SQLAlchemy is deliberate: the workload is low-concurrency research
queries, and a sync engine keeps the analytics call path simple to reason about
and test. Revisit only if profiling shows a real need.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from quantscope.config import get_settings

engine = create_engine(
    get_settings().database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a transactional session scope."""
    with SessionLocal() as session:
        yield session
