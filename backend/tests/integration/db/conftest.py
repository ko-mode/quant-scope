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
