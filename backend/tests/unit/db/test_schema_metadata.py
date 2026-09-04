"""Schema assertions that need no database - they inspect ``Base.metadata``.

These lock the model definitions to the approved Phase 1A schema
(docs/architecture.md section 7; ADRs 0004, 0006, 0011, 0012). The migration is
exercised against a real PostgreSQL in tests/integration/db/.
"""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, Numeric

import quantscope.db.models  # noqa: F401  (registers tables on Base.metadata)
from quantscope.db.base import Base

metadata = Base.metadata


def _check_names(table_name: str) -> set[str]:
    table = metadata.tables[table_name]
    return {
        c.name
        for c in table.constraints
        if isinstance(c, CheckConstraint) and isinstance(c.name, str)
    }


def test_expected_tables_registered() -> None:
    assert set(metadata.tables) == {
        "security",
        "price_bar",
        "data_ingestion_run",
        "factor_return",
    }


# --------------------------------------------------------------------------- #
# security
# --------------------------------------------------------------------------- #
def test_security_columns_and_nullability() -> None:
    cols = metadata.tables["security"].c
    expected_not_null = {
        "id",
        "ticker",
        "name",
        "exchange",
        "currency",
        "is_active",
        "created_at",
        "updated_at",
    }
    expected_nullable = {
        "cik",
        "asset_type",  # nullable since migration 0002 (ADR 0021)
        "first_trade_date",
        "last_trade_date",
        "delisted_date",
    }
    assert set(cols.keys()) == expected_not_null | expected_nullable
    assert {c.name for c in cols if not c.nullable} == expected_not_null


def test_security_primary_key_is_surrogate_id() -> None:
    assert list(metadata.tables["security"].primary_key.columns.keys()) == ["id"]


def test_security_ticker_is_unique() -> None:
    assert metadata.tables["security"].c.ticker.unique is True


def test_security_server_defaults_present() -> None:
    cols = metadata.tables["security"].c
    assert cols.currency.server_default is not None
    assert cols.is_active.server_default is not None
    assert cols.created_at.server_default is not None
    assert cols.updated_at.server_default is not None


def test_security_trgm_indexes() -> None:
    by_name = {str(ix.name): ix for ix in metadata.tables["security"].indexes}
    for name, column in (
        ("ix_security_ticker_trgm", "ticker"),
        ("ix_security_name_trgm", "name"),
    ):
        assert name in by_name, name
        ix = by_name[name]
        assert ix.dialect_kwargs.get("postgresql_using") == "gin"
        assert ix.dialect_kwargs.get("postgresql_ops") == {column: "gin_trgm_ops"}
        assert [c.name for c in ix.columns] == [column]


def test_security_check_constraints_present() -> None:
    assert _check_names("security") == {
        "ck_security_asset_type_allowed",
        "ck_security_currency_usd_only",
        "ck_security_ticker_not_blank",
        "ck_security_cik_10_digits",
        "ck_security_delisted_implies_inactive",
    }


# --------------------------------------------------------------------------- #
# price_bar
# --------------------------------------------------------------------------- #
def test_price_bar_composite_primary_key() -> None:
    assert list(metadata.tables["price_bar"].primary_key.columns.keys()) == [
        "security_id",
        "trade_date",
        "source",
    ]


def test_price_bar_nullability() -> None:
    cols = metadata.tables["price_bar"].c
    assert cols.close.nullable is False
    assert cols.adj_close.nullable is False
    assert cols.ingested_at.nullable is False
    for optional in ("open", "high", "low", "volume"):
        assert cols[optional].nullable is True, optional


def test_price_bar_foreign_key_restricts_security_deletion() -> None:
    fks = list(metadata.tables["price_bar"].foreign_key_constraints)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column_keys == ["security_id"]
    assert fk.elements[0].target_fullname == "security.id"
    assert fk.ondelete == "RESTRICT"


def test_price_bar_price_columns_are_numeric_18_6() -> None:
    cols = metadata.tables["price_bar"].c
    for name in ("open", "high", "low", "close", "adj_close"):
        col_type = cols[name].type
        assert isinstance(col_type, Numeric)
        assert (col_type.precision, col_type.scale) == (18, 6)


def test_price_bar_check_constraints_present() -> None:
    assert _check_names("price_bar") == {
        "ck_price_bar_close_positive",
        "ck_price_bar_adj_close_positive",
        "ck_price_bar_open_positive",
        "ck_price_bar_high_positive",
        "ck_price_bar_low_positive",
        "ck_price_bar_high_ge_low",
        "ck_price_bar_volume_non_negative",
        "ck_price_bar_source_not_blank",
    }


# --------------------------------------------------------------------------- #
# data_ingestion_run
# --------------------------------------------------------------------------- #
def test_data_ingestion_run_columns_and_nullability() -> None:
    cols = metadata.tables["data_ingestion_run"].c
    not_null = {"id", "source", "entity", "rows_written", "status", "started_at"}
    nullable = {"target_ref", "range_start", "range_end", "error", "finished_at"}
    assert set(cols.keys()) == not_null | nullable
    assert {c.name for c in cols if not c.nullable} == not_null


def test_data_ingestion_run_index() -> None:
    by_name = {str(ix.name): ix for ix in metadata.tables["data_ingestion_run"].indexes}
    assert "ix_data_ingestion_run_entity_started_at" in by_name
    assert [c.name for c in by_name["ix_data_ingestion_run_entity_started_at"].columns] == [
        "entity",
        "started_at",
    ]


def test_data_ingestion_run_check_constraints_present() -> None:
    assert _check_names("data_ingestion_run") == {
        "ck_data_ingestion_run_entity_allowed",
        "ck_data_ingestion_run_status_allowed",
        "ck_data_ingestion_run_rows_written_non_negative",
        "ck_data_ingestion_run_range_start_le_end",
        "ck_data_ingestion_run_finished_after_started",
    }


@pytest.mark.parametrize(
    ("table", "pk_name"),
    [
        ("security", "pk_security"),
        ("price_bar", "pk_price_bar"),
        ("data_ingestion_run", "pk_data_ingestion_run"),
        ("factor_return", "pk_factor_return"),
    ],
)
def test_naming_convention_applied_to_primary_keys(table: str, pk_name: str) -> None:
    assert metadata.tables[table].primary_key.name == pk_name


# --------------------------------------------------------------------------- #
# factor_return (Phase 2B.1, ADR 0009)
# --------------------------------------------------------------------------- #
def test_factor_return_composite_primary_key() -> None:
    assert list(metadata.tables["factor_return"].primary_key.columns.keys()) == [
        "factor_name",
        "frequency",
        "trade_date",
        "source",
    ]


def test_factor_return_columns_and_nullability() -> None:
    cols = metadata.tables["factor_return"].c
    expected = {"factor_name", "frequency", "trade_date", "source", "value", "ingested_at"}
    assert set(cols.keys()) == expected
    assert {c.name for c in cols if not c.nullable} == expected  # nothing nullable


def test_factor_return_value_is_numeric_18_6() -> None:
    col_type = metadata.tables["factor_return"].c.value.type
    assert isinstance(col_type, Numeric)
    assert (col_type.precision, col_type.scale) == (18, 6)


def test_factor_return_has_no_foreign_keys() -> None:
    # Factors are market-wide series, not securities (no FK to `security`).
    assert list(metadata.tables["factor_return"].foreign_key_constraints) == []


def test_factor_return_check_constraints_present() -> None:
    assert _check_names("factor_return") == {
        "ck_factor_return_factor_name_allowed",
        "ck_factor_return_frequency_allowed",
        "ck_factor_return_source_not_blank",
    }
