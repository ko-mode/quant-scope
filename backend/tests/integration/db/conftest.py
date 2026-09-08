"""Fixtures for database-backed schema tests.

These run only when ``QUANTSCOPE_TEST_DATABASE_URL`` points at a **disposable**
PostgreSQL database (CI provisions one; locally, point it at a scratch database).
Without it the whole module is skipped.

The schema is built once per session by running the Alembic migration against an
injected connection, and each test runs inside a transaction that is rolled back.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("QUANTSCOPE_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "QUANTSCOPE_TEST_DATABASE_URL is not set; needs a disposable PostgreSQL database"
        )
    return url


@pytest.fixture(scope="session")
def alembic_config() -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session")
def migrated_engine(database_url: str, alembic_config: Config) -> Iterator[Engine]:
    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        alembic_config.attributes["connection"] = connection
        command.downgrade(alembic_config, "base")  # clean slate if a prior run crashed
        command.upgrade(alembic_config, "head")
        connection.commit()
    try:
        yield engine
    finally:
        with engine.connect() as connection:
            alembic_config.attributes["connection"] = connection
            command.downgrade(alembic_config, "base")
            connection.commit()
        engine.dispose()


@pytest.fixture
def connection(migrated_engine: Engine) -> Iterator[Connection]:
    conn = migrated_engine.connect()
    transaction = conn.begin()
    try:
        yield conn
    finally:
        transaction.rollback()
        conn.close()


@pytest.fixture
def session(connection: Connection) -> Iterator[Session]:
    sess = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture
def configured_stooq_provider() -> Iterator[None]:
    """Simulate a deployment with ``QUANTSCOPE_PRICE_PROVIDER=stooq`` (RA-02).

    ``get_settings()`` is process-cached (``functools.lru_cache``), so the env
    var alone is not enough once it has already been read once in this test
    session - the cache must be cleared for the new value to take effect, and
    cleared again afterwards so later tests see the real environment.
    """
    from quantscope.config import get_settings

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QUANTSCOPE_PRICE_PROVIDER", "stooq")
        get_settings.cache_clear()
        try:
            yield
        finally:
            get_settings.cache_clear()


@pytest.fixture
def api_client(connection: Connection) -> Iterator[TestClient]:
    """A FastAPI TestClient whose ``get_session`` dependency rides the test's
    rolled-back transaction, so API reads see rows the test inserted and nothing
    the API touches is committed for real.
    """
    from quantscope.db.session import get_session
    from quantscope.main import create_app

    app = create_app()

    def _session_override() -> Iterator[Session]:
        sess = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield sess
        finally:
            sess.close()

    app.dependency_overrides[get_session] = _session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
