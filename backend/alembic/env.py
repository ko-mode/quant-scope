"""Alembic migration environment.

The SQLAlchemy URL comes from ``quantscope.config`` for command-line use. Tests
inject a live connection via ``config.attributes["connection"]`` so migrations
run against a disposable database without touching process settings.
``target_metadata`` is the ORM declarative base's metadata; importing
``quantscope.db.models`` registers every table on it.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from quantscope.config import get_settings
from quantscope.db import models as _models  # noqa: F401  (registers tables on Base.metadata)
from quantscope.db.base import Base

config = context.config

# Only (re)configure logging for standalone CLI use. When a connection is
# injected (tests, programmatic callers) leave the caller's logging alone -
# fileConfig() would otherwise tear down handlers such as pytest's caplog.
if config.config_file_name is not None and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    injected_connection = config.attributes.get("connection", None)
    if injected_connection is not None:
        context.configure(
            connection=injected_connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
