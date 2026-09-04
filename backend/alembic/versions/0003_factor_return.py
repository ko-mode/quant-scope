"""factor_return: daily Fama-French factors + RF

Adds the ``factor_return`` table for the Kenneth R. French daily research
factors (Mkt-RF, SMB, HML) and the risk-free rate (RF), following ADR 0009
(``frequency`` in the primary key so monthly / FF5 / momentum are addable as
data) and ADR 0013 (RF is the Ken French daily series, ``factor_name = 'rf'``).

Stored ``value`` is a **decimal daily return** - the ingestion layer converts the
source's percent to decimal (``/100``) before persistence. No foreign key to
``security``: factors are market-wide series.

The ``abs(value) < 0.5`` percent-vs-decimal sanity check lives in the ingestion
/ Pandera validation layer, not as a database CHECK: the DB enforces structural
integrity, the validation layer owns the heuristic (ADR 0009 addendum).

Constraint names are unqualified; the ``Base.metadata`` naming convention
prefixes them to match autogenerate.

Revision ID: 0003_factor_return
Revises: 0002_asset_type_nullable
Create Date: 2026-09-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_factor_return"
down_revision: str | None = "0002_asset_type_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FACTOR_VALUE = sa.Numeric(precision=18, scale=6)


def upgrade() -> None:
    op.create_table(
        "factor_return",
        sa.Column("factor_name", sa.String(length=16), nullable=False),
        sa.Column("frequency", sa.String(length=8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("value", _FACTOR_VALUE, nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "factor_name IN ('mkt_rf', 'smb', 'hml', 'rf')",
            name="factor_name_allowed",
        ),
        sa.CheckConstraint("frequency = 'daily'", name="frequency_allowed"),
        sa.CheckConstraint("char_length(source) > 0", name="source_not_blank"),
        sa.PrimaryKeyConstraint("factor_name", "frequency", "trade_date", "source"),
    )


def downgrade() -> None:
    op.drop_table("factor_return")
