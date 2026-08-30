"""Database-backed checks for ``run_security_seed`` (Phase 1B).

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest). Uses an
in-process fake provider - no HTTP, no committed SEC data.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from quantscope.data.providers.base import RawSecurityRecord
from quantscope.data.security_seed import run_security_seed
from quantscope.db.models import DataIngestionRun, Security


class _StaticProvider:
    source_name = "test_static"

    def __init__(self, records: list[RawSecurityRecord]) -> None:
        self._records = records

    def fetch_securities(self) -> list[RawSecurityRecord]:
        return list(self._records)


def _raw(ticker: str, name: str, cik: str | None, exchange: str | None) -> RawSecurityRecord:
    return RawSecurityRecord(ticker=ticker, name=name, cik=cik, exchange=exchange)


_CLEAN = [
    _raw("AAPL", "Apple Inc.", "320193", "Nasdaq"),
    _raw("SPY", "SPDR S&P 500 ETF TRUST", "884394", "NYSE Arca"),
    _raw("JPM", "JPMORGAN CHASE & CO", "19617", "NYSE"),
]
_ONE_BAD = [*_CLEAN, _raw("NOEXCH", "No Exchange Co", "1000001", None)]


@pytest.fixture
def seed_session(connection: Connection) -> Iterator[Session]:
    """Mirrors the app's SessionLocal (expire_on_commit=False) on the test txn."""
    sess = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield sess
    finally:
        sess.close()


def _ticker_ids(session: Session) -> dict[str, int]:
    return dict(session.execute(select(Security.ticker, Security.id)).all())  # type: ignore[arg-type]


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# --------------------------------------------------------------------------- #
def test_seed_persists_normalized_universe(seed_session: Session) -> None:
    report = run_security_seed(seed_session, _StaticProvider(_ONE_BAD))

    assert report.inserted == 3
    assert report.rejected == 1
    assert report.status == "partial"

    rows = {s.ticker: s for s in seed_session.scalars(select(Security))}
    assert set(rows) == {"AAPL", "SPY", "JPM"}
    assert rows["AAPL"].exchange == "XNAS"
    assert rows["AAPL"].cik == "0000320193"
    assert rows["AAPL"].asset_type is None
    assert rows["SPY"].exchange == "ARCX"
    assert rows["SPY"].asset_type == "etf"
    assert rows["JPM"].exchange == "XNYS"

    run = seed_session.scalars(select(DataIngestionRun)).one()
    assert (run.source, run.entity, run.status) == ("test_static", "securities", "partial")
    assert run.rows_written == 3
    assert run.finished_at is not None
    assert run.id == report.run_id


def test_seed_excludes_otc_securities(seed_session: Session) -> None:
    records = [
        _raw("AAPL", "Apple Inc.", "320193", "Nasdaq"),
        _raw("PINK", "Pink Sheet Holdings", "111111", "OTC"),
        _raw("GREY", "Grey Market Co", "222222", "OTC"),
    ]
    report = run_security_seed(seed_session, _StaticProvider(records))

    assert {s.ticker for s in seed_session.scalars(select(Security))} == {"AAPL"}
    assert report.inserted == 1
    assert report.rejected == 2
    assert report.reason_counts == {"unsupported_exchange_v1": 2}
    assert report.status == "partial"


def test_seed_is_idempotent(seed_session: Session) -> None:
    first = run_security_seed(seed_session, _StaticProvider(_CLEAN))
    ids_after_first = _ticker_ids(seed_session)

    second = run_security_seed(seed_session, _StaticProvider(_CLEAN))
    ids_after_second = _ticker_ids(seed_session)

    assert first.inserted == 3
    assert second.inserted == 0 and second.updated == 0
    assert second.unchanged == 3
    assert ids_after_first == ids_after_second
    assert _count(seed_session, Security) == 3

    runs = seed_session.scalars(select(DataIngestionRun).order_by(DataIngestionRun.id)).all()
    assert [r.rows_written for r in runs] == [3, 0]
    assert [r.status for r in runs] == ["success", "success"]


def test_seed_updates_changed_row_in_place(seed_session: Session) -> None:
    run_security_seed(seed_session, _StaticProvider([_raw("AAPL", "Old Name", "320193", "Nasdaq")]))
    original = seed_session.scalars(select(Security).where(Security.ticker == "AAPL")).one()
    original_id, original_created = original.id, original.created_at

    report = run_security_seed(
        seed_session,
        _StaticProvider([_raw("AAPL", "Apple Inc.", "320193", "NYSE")]),
    )
    seed_session.expire_all()
    updated = seed_session.scalars(select(Security).where(Security.ticker == "AAPL")).one()

    assert report.updated == 1 and report.inserted == 0
    assert updated.id == original_id
    assert updated.created_at == original_created
    assert updated.name == "Apple Inc."
    assert updated.exchange == "XNYS"
    assert _count(seed_session, Security) == 1


def test_seed_never_deletes_or_deactivates_missing_securities(seed_session: Session) -> None:
    run_security_seed(
        seed_session,
        _StaticProvider(
            [
                _raw("A", "A Co", "1", "NYSE"),
                _raw("B", "B Co", "2", "NYSE"),
                _raw("C", "C Co", "3", "NYSE"),
            ]
        ),
    )
    run_security_seed(
        seed_session,
        _StaticProvider([_raw("A", "A Co", "1", "NYSE"), _raw("B", "B Co", "2", "NYSE")]),
    )

    gone = seed_session.scalars(select(Security).where(Security.ticker == "C")).one()
    assert gone.is_active is True
    assert gone.delisted_date is None
    assert _count(seed_session, Security) == 3


def test_seed_skips_malformed_records_with_explicit_reasons(
    seed_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    records = [
        _raw("GOOD", "Good Co", "1", "NYSE"),
        _raw("BADCIK", "Bad Cik Co", "999999999999", "NYSE"),
        _raw("NOEX", "No Exchange Co", "2", None),
        _raw("GOOD", "Duplicate Good", "1", "NYSE"),
        _raw("", "Blank Ticker Co", "3", "NYSE"),
    ]
    with caplog.at_level(logging.WARNING, logger="quantscope.data.security_seed"):
        report = run_security_seed(seed_session, _StaticProvider(records))

    assert {s.ticker for s in seed_session.scalars(select(Security))} == {"GOOD"}
    assert report.status == "partial"
    assert report.reason_counts == {
        "invalid_cik": 1,
        "unmapped_or_missing_exchange": 1,
        "duplicate_ticker_in_snapshot": 1,
        "invalid_or_missing_ticker": 1,
    }
    reasons = [
        r.reason  # type: ignore[attr-defined]
        for r in caplog.records
        if r.msg == "security_seed.rejected"
    ]
    assert any(x.startswith("invalid_cik") for x in reasons)
    assert any(x.startswith("unmapped_or_missing_exchange") for x in reasons)


def test_dry_run_writes_nothing(seed_session: Session) -> None:
    report = run_security_seed(seed_session, _StaticProvider(_ONE_BAD), dry_run=True)
    assert report.run_id is None
    assert report.normalized == 3
    assert _count(seed_session, Security) == 0
    assert _count(seed_session, DataIngestionRun) == 0
