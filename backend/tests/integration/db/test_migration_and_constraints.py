"""Database-backed checks for migrations 0001-0003 and the model constraints.

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quantscope.db.base import Base
from quantscope.db.models import DataIngestionRun, FactorReturn, PriceBar, Security

_EPOCH = datetime.date(2024, 1, 2)


def _security(**overrides: object) -> Security:
    values: dict[str, object] = {
        "ticker": "TEST",
        "name": "Test Corporation",
        "exchange": "XNAS",
        "asset_type": "common_stock",
    }
    values.update(overrides)
    return Security(**values)


def _persisted_security(session: Session, **overrides: object) -> Security:
    sec = _security(**overrides)
    session.add(sec)
    session.flush()
    return sec


# --------------------------------------------------------------------------- #
# migration structure
# --------------------------------------------------------------------------- #
def test_pg_trgm_extension_created(connection: Connection) -> None:
    installed = connection.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'")
    ).scalar_one_or_none()
    assert installed == "pg_trgm"


def test_expected_tables_exist(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    assert {"security", "price_bar", "data_ingestion_run", "factor_return"} <= tables


def test_migration_matches_models(connection: Connection) -> None:
    """Equivalent to ``alembic check``: no drift between models and the DB."""
    ctx = MigrationContext.configure(
        connection, opts={"compare_type": True, "target_metadata": Base.metadata}
    )
    assert compare_metadata(ctx, Base.metadata) == []


def test_trgm_indexes_are_gin(connection: Connection) -> None:
    rows = connection.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'security' AND indexname LIKE '%trgm'"
        )
    ).all()
    defs: dict[str, str] = {row[0]: row[1] for row in rows}
    assert "USING gin" in defs["ix_security_ticker_trgm"]
    assert "gin_trgm_ops" in defs["ix_security_ticker_trgm"]
    assert "gin_trgm_ops" in defs["ix_security_name_trgm"]


# --------------------------------------------------------------------------- #
# security constraints
# --------------------------------------------------------------------------- #
def test_security_defaults_applied(session: Session) -> None:
    sec = _persisted_security(session)
    session.refresh(sec)
    assert sec.id is not None
    assert sec.currency == "USD"
    assert sec.is_active is True
    assert sec.created_at is not None and sec.updated_at is not None


def test_security_ticker_unique(session: Session) -> None:
    session.add(_security(ticker="DUP"))
    session.flush()
    session.add(_security(ticker="DUP", name="Another"))
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_type": "bond"},
        {"currency": "EUR"},
        {"cik": "123"},
        {"cik": "12345678AB"},
        {"ticker": ""},
        {"delisted_date": datetime.date(2020, 1, 1), "is_active": True},
    ],
)
def test_security_check_constraints_reject(session: Session, overrides: dict[str, object]) -> None:
    session.add(_security(**overrides))
    with pytest.raises(IntegrityError):
        session.flush()


def test_security_delisted_with_inactive_is_allowed(session: Session) -> None:
    session.add(_security(ticker="DEAD", delisted_date=datetime.date(2020, 1, 1), is_active=False))
    session.flush()  # no error


def test_security_cik_ten_digits_allowed(session: Session) -> None:
    session.add(_security(ticker="NV", cik="0001045810"))
    session.flush()


def test_security_asset_type_may_be_null(session: Session) -> None:
    sec = _security(ticker="UNK", asset_type=None)
    session.add(sec)
    session.flush()
    session.refresh(sec)
    assert sec.asset_type is None


# --------------------------------------------------------------------------- #
# price_bar constraints
# --------------------------------------------------------------------------- #
def test_price_bar_insert_and_optional_columns(session: Session) -> None:
    sec = _persisted_security(session)
    session.add(
        PriceBar(
            security_id=sec.id,
            trade_date=_EPOCH,
            source="stooq",
            close=Decimal("100.0"),
            adj_close=Decimal("100.0"),
        )
    )
    session.flush()
    bar = session.get(PriceBar, {"security_id": sec.id, "trade_date": _EPOCH, "source": "stooq"})
    assert bar is not None
    assert bar.open is None and bar.high is None and bar.low is None and bar.volume is None
    assert bar.ingested_at is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"close": None},
        {"adj_close": None},
        {"close": Decimal("0")},
        {"close": Decimal("-1")},
        {"adj_close": Decimal("0")},
        {"open": Decimal("0")},
        {"high": Decimal("1"), "low": Decimal("2")},
        {"volume": -5},
        {"source": ""},
    ],
)
def test_price_bar_check_constraints_reject(session: Session, overrides: dict[str, object]) -> None:
    sec = _persisted_security(session)
    values: dict[str, object] = {
        "security_id": sec.id,
        "trade_date": _EPOCH,
        "source": "stooq",
        "close": Decimal("10"),
        "adj_close": Decimal("10"),
    }
    values.update(overrides)
    session.add(PriceBar(**values))
    with pytest.raises(IntegrityError):
        session.flush()


def test_price_bar_primary_key_is_composite(session: Session) -> None:
    sec = _persisted_security(session)
    common = {
        "security_id": sec.id,
        "trade_date": _EPOCH,
        "close": Decimal("1"),
        "adj_close": Decimal("1"),
    }
    session.add(PriceBar(source="stooq", **common))
    session.add(PriceBar(source="tiingo", **common))  # different source -> allowed
    session.flush()
    session.add(PriceBar(source="stooq", **common))  # duplicate triple -> rejected
    with pytest.raises(IntegrityError):
        session.flush()


def test_price_bar_requires_existing_security(session: Session) -> None:
    session.add(
        PriceBar(
            security_id=987654321,
            trade_date=_EPOCH,
            source="stooq",
            close=Decimal("1"),
            adj_close=Decimal("1"),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_security_with_price_bars_is_rejected(session: Session) -> None:
    sec = _persisted_security(session)
    session.add(
        PriceBar(
            security_id=sec.id,
            trade_date=_EPOCH,
            source="stooq",
            close=Decimal("1"),
            adj_close=Decimal("1"),
        )
    )
    session.flush()

    with pytest.raises(IntegrityError), session.begin_nested():
        session.delete(sec)
        session.flush()

    # ON DELETE RESTRICT: the security and its price bar are untouched.
    assert session.get(Security, sec.id) is not None
    assert session.scalar(select(func.count()).select_from(PriceBar)) == 1


def test_deleting_security_without_price_bars_is_allowed(session: Session) -> None:
    sec = _persisted_security(session, ticker="GONE")
    session.delete(sec)
    session.flush()
    assert session.get(Security, sec.id) is None


# --------------------------------------------------------------------------- #
# data_ingestion_run constraints
# --------------------------------------------------------------------------- #
def test_ingestion_run_defaults(session: Session) -> None:
    run = DataIngestionRun(source="stooq", entity="prices", status="running")
    session.add(run)
    session.flush()
    session.refresh(run)
    assert run.id is not None
    assert run.rows_written == 0
    assert run.started_at is not None
    assert run.finished_at is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"entity": "bogus"},
        {"status": "weird"},
        {"rows_written": -1},
        {
            "started_at": datetime.datetime(2024, 1, 2, tzinfo=datetime.UTC),
            "finished_at": datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
        },
        {"range_start": datetime.date(2024, 2, 1), "range_end": datetime.date(2024, 1, 1)},
    ],
)
def test_ingestion_run_check_constraints_reject(
    session: Session, overrides: dict[str, object]
) -> None:
    values: dict[str, object] = {"source": "stooq", "entity": "prices", "status": "success"}
    values.update(overrides)
    session.add(DataIngestionRun(**values))
    with pytest.raises(IntegrityError):
        session.flush()


# --------------------------------------------------------------------------- #
# factor_return constraints (Phase 2B.1, ADR 0009)
# --------------------------------------------------------------------------- #
def test_factor_return_insert_defaults(session: Session) -> None:
    row = FactorReturn(
        factor_name="rf",
        frequency="daily",
        trade_date=_EPOCH,
        source="kenneth_french",
        value=Decimal("0.000090"),
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    assert row.ingested_at is not None


def test_factor_return_no_foreign_key_to_security(session: Session) -> None:
    # Factors are market-wide series, not securities - no security_id column at all.
    assert not hasattr(FactorReturn, "security_id")


@pytest.mark.parametrize(
    "overrides",
    [
        {"factor_name": "momentum"},  # not one of mkt_rf/smb/hml/rf
        {"frequency": "monthly"},  # V1 is daily-only
        {"source": ""},
        {"value": None},
        {"trade_date": None},
    ],
)
def test_factor_return_check_constraints_reject(
    session: Session, overrides: dict[str, object]
) -> None:
    values: dict[str, object] = {
        "factor_name": "rf",
        "frequency": "daily",
        "trade_date": _EPOCH,
        "source": "kenneth_french",
        "value": Decimal("0.0001"),
    }
    values.update(overrides)
    session.add(FactorReturn(**values))
    with pytest.raises(IntegrityError):
        session.flush()


def test_factor_return_value_has_no_range_check_at_the_db_layer(session: Session) -> None:
    # The abs(value) < 0.5 percent-vs-decimal tripwire is an ingestion / Pandera
    # heuristic (quantscope.data.factors), not a database constraint - the DB
    # only enforces structural integrity (ADR 0009 addendum).
    session.add(
        FactorReturn(
            factor_name="mkt_rf",
            frequency="daily",
            trade_date=_EPOCH,
            source="kenneth_french",
            value=Decimal("12.5"),
        )
    )
    session.flush()  # does not raise


def test_factor_return_primary_key_is_composite(session: Session) -> None:
    common = {"trade_date": _EPOCH, "value": Decimal("0.0001")}
    session.add(
        FactorReturn(factor_name="rf", frequency="daily", source="kenneth_french", **common)
    )
    session.add(
        FactorReturn(factor_name="mkt_rf", frequency="daily", source="kenneth_french", **common)
    )
    session.add(FactorReturn(factor_name="rf", frequency="daily", source="other_source", **common))
    session.flush()
    session.add(
        FactorReturn(factor_name="rf", frequency="daily", source="kenneth_french", **common)
    )  # exact duplicate key -> rejected
    with pytest.raises(IntegrityError):
        session.flush()
