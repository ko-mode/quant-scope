"""security.asset_type becomes nullable

The Phase 1B seed source (SEC ``company_tickers_exchange.json``) carries no
asset-type field. Rather than guess, ``asset_type`` is left NULL where it cannot
be determined from a reliable source (ADR 0021). This migration makes the column
nullable and relaxes its CHECK to permit NULL.

Constraint names are passed unqualified; the naming convention on
``Base.metadata`` prefixes them to ``ck_security_asset_type_allowed``.

Downgrade re-imposes NOT NULL; it fails if any row has ``asset_type IS NULL``
(expected - the information cannot be reconstructed).

Revision ID: 0002_asset_type_nullable
Revises: 0001_initial_schema
Create Date: 2026-08-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_asset_type_nullable"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED = "asset_type IN ('common_stock', 'etf', 'index')"
_ALLOWED_OR_NULL = "asset_type IS NULL OR asset_type IN ('common_stock', 'etf', 'index')"


def upgrade() -> None:
    op.drop_constraint("asset_type_allowed", "security", type_="check")
    op.alter_column(
        "security",
        "asset_type",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    op.create_check_constraint("asset_type_allowed", "security", _ALLOWED_OR_NULL)


def downgrade() -> None:
    op.drop_constraint("asset_type_allowed", "security", type_="check")
    op.alter_column(
        "security",
        "asset_type",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.create_check_constraint("asset_type_allowed", "security", _ALLOWED)
