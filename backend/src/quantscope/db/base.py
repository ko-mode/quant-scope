"""Declarative base for all ORM models.

Alembic's ``env.py`` imports :data:`Base.metadata` as its autogenerate target.
Model modules (added in Phase 1) will subclass :class:`Base`; importing them in
``quantscope.db.models`` is what registers their tables on the metadata.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
