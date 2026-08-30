"""initial schema: security, price_bar, data_ingestion_run

Creates the ``pg_trgm`` extension and the three Phase 1A tables, following
docs/architecture.md section 7 and ADRs 0004, 0006, 0011, 0012.

Constraint and index names are left unqualified here; the naming convention on
``Base.metadata`` (see ``quantscope.db.base``) prefixes them, so the names in the
database match what Alembic autogenerate expects from the models.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRICE = sa.Numeric(precision=18, scale=6)


def upgrade() -> None:
    # Required for the trigram (GIN) indexes on security.ticker / security.name.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "security",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cik", sa.String(length=10), nullable=True),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column(
            "currency",
            sa.String(length=3),
            server_default=sa.text("'USD'"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("first_trade_date", sa.Date(), nullable=True),
        sa.Column("last_trade_date", sa.Date(), nullable=True),
        sa.Column("delisted_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "asset_type IN ('common_stock', 'etf', 'index')",
            name="asset_type_allowed",
        ),
        sa.CheckConstraint("currency = 'USD'", name="currency_usd_only"),
        sa.CheckConstraint("char_length(ticker) > 0", name="ticker_not_blank"),
        sa.CheckConstraint(
            "cik IS NULL OR cik ~ '^[0-9]{10}$'", name="cik_10_digits"
        ),
        sa.CheckConstraint(
            "delisted_date IS NULL OR is_active = false",
            name="delisted_implies_inactive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker"),
    )
    op.create_index(
        "ix_security_ticker_trgm",
        "security",
        ["ticker"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"ticker": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_security_name_trgm",
        "security",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )

    op.create_table(
        "price_bar",
        sa.Column("security_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("open", _PRICE, nullable=True),
        sa.Column("high", _PRICE, nullable=True),
        sa.Column("low", _PRICE, nullable=True),
        sa.Column("close", _PRICE, nullable=False),
        sa.Column("adj_close", _PRICE, nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("close > 0", name="close_positive"),
        sa.CheckConstraint("adj_close > 0", name="adj_close_positive"),
        sa.CheckConstraint("open IS NULL OR open > 0", name="open_positive"),
        sa.CheckConstraint("high IS NULL OR high > 0", name="high_positive"),
        sa.CheckConstraint("low IS NULL OR low > 0", name="low_positive"),
        sa.CheckConstraint(
            "high IS NULL OR low IS NULL OR high >= low", name="high_ge_low"
        ),
        sa.CheckConstraint(
            "volume IS NULL OR volume >= 0", name="volume_non_negative"
        ),
        sa.CheckConstraint("char_length(source) > 0", name="source_not_blank"),
        sa.ForeignKeyConstraint(
            ["security_id"], ["security.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("security_id", "trade_date", "source"),
    )

    op.create_table(
        "data_ingestion_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("entity", sa.String(length=16), nullable=False),
        sa.Column("target_ref", sa.String(length=128), nullable=True),
        sa.Column("range_start", sa.Date(), nullable=True),
        sa.Column("range_end", sa.Date(), nullable=True),
        sa.Column(
            "rows_written",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "entity IN ('securities', 'prices', 'factors', 'fundamentals')",
            name="entity_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'partial')",
            name="status_allowed",
        ),
        sa.CheckConstraint("rows_written >= 0", name="rows_written_non_negative"),
        sa.CheckConstraint(
            "range_start IS NULL OR range_end IS NULL OR range_start <= range_end",
            name="range_start_le_end",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_ingestion_run_entity_started_at",
        "data_ingestion_run",
        ["entity", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_data_ingestion_run_entity_started_at", table_name="data_ingestion_run"
    )
    op.drop_table("data_ingestion_run")
    op.drop_table("price_bar")
    op.drop_index("ix_security_name_trgm", table_name="security")
    op.drop_index("ix_security_ticker_trgm", table_name="security")
    op.drop_table("security")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
