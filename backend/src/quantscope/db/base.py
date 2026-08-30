"""Declarative base for all ORM models.

Alembic's ``env.py`` imports :data:`Base.metadata` as its autogenerate target.
Model modules subclass :class:`Base`; importing ``quantscope.db.models`` is what
registers their tables on the metadata.

A deterministic naming convention is applied so that hand-written migrations and
Alembic autogenerate agree on constraint and index names.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
