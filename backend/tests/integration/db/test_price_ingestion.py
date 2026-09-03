"""Database-backed checks for Phase 1D price ingestion.

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest). Uses an
in-process fake ``DailyPriceProvider`` - no HTTP, no live Tiingo token, no
committed vendor data.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import Connection, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from quantscope.data import ingest as ingest_mod
from quantscope.data.ingest import (
    PriceIngestReport,
    SecurityNotFoundError,
    run_price_ingestion,
)
from quantscope.data.providers.base import (
    PriceProviderRateLimitedError,
    RawPriceBar,
)
from quantscope.db.models import DataIngestionRun, PriceBar, Security
from quantscope.db.repositories.prices import PriceUpsertCounts

_START = datetime.date(2020, 1, 1)
_END = datetime.date(2020, 1, 31)


# --------------------------------------------------------------------------- #
# Fakes / helpers
# --------------------------------------------------------------------------- #
class _FakeProvider:
    """Returns a fixed bar list, or raises, and records how it was called."""

    def __init__(
        self,
        bars: list[RawPriceBar],
        *,
        source: str = "tiingo",
        raises: Exception | None = None,
    ) -> None:
        self.source_name = source
        self._bars = bars
        self._raises = raises
        self.calls: list[tuple[str, datetime.date, datetime.date]] = []

    def fetch_daily_history(
        self, ticker: str, *, start: datetime.date, end: datetime.date
    ) -> list[RawPriceBar]:
        self.calls.append((ticker, start, end))
        if self._raises is not None:
            raise self._raises
        return list(self._bars)


def _bar(
    day: str,
    close: float,
    adj: float | None = None,
    *,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    volume: int | None = None,
) -> RawPriceBar:
    def _s(v: float | int | None) -> str | None:
        return None if v is None else str(v)

    return RawPriceBar(
        trade_date=day,
        open=_s(open_),
        high=_s(high),
        low=_s(low),
        close=_s(close),
        adj_close=_s(close if adj is None else adj),
        volume=_s(volume),
    )


_THREE_GOOD = [
    _bar("2020-01-02", 10.0, 9.0, high=10.5, low=9.8, volume=1_000_000),
    _bar("2020-01-03", 10.5, 9.4, high=10.8, low=10.1, volume=1_200_000),
    _bar("2020-01-06", 10.8, 9.7, high=11.0, low=10.4, volume=900_000),
]


@pytest.fixture
def ingest_session(connection: Connection) -> Iterator[Session]:
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


def _seed(session: Session, *tickers: str) -> dict[str, int]:
    ids: dict[str, int] = {}
    for ticker in tickers:
        sec = Security(
            ticker=ticker,
            name=f"{ticker} Inc.",
            exchange="XNAS",
            asset_type="common_stock",
        )
        session.add(sec)
        session.flush()
        ids[ticker] = sec.id
    session.commit()
    return ids


def _price_rows(session: Session, security_id: int, source: str | None = None) -> list[PriceBar]:
    stmt = select(PriceBar).where(PriceBar.security_id == security_id)
    if source is not None:
        stmt = stmt.where(PriceBar.source == source)
    return list(session.scalars(stmt.order_by(PriceBar.trade_date, PriceBar.source)))


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _run(
    session: Session,
    ticker: str,
    provider: _FakeProvider,
    *,
    start: datetime.date = _START,
    end: datetime.date = _END,
    dry_run: bool = False,
) -> PriceIngestReport:
    return run_price_ingestion(session, provider, ticker, start=start, end=end, dry_run=dry_run)


# --------------------------------------------------------------------------- #
# First insert / success accounting
# --------------------------------------------------------------------------- #
def test_first_ingest_inserts_all_valid_bars(ingest_session: Session) -> None:
    sid = _seed(ingest_session, "NVDA")["NVDA"]
    provider = _FakeProvider(_THREE_GOOD)

    report = _run(ingest_session, "NVDA", provider)

    assert (report.inserted, report.updated, report.unchanged) == (3, 0, 0)
    assert report.rows_written == 3
    assert report.persisted == 3
    assert report.dropped == 0
    assert report.status == "success"

    rows = _price_rows(ingest_session, sid)
    assert [r.trade_date for r in rows] == [
        datetime.date(2020, 1, 2),
        datetime.date(2020, 1, 3),
        datetime.date(2020, 1, 6),
    ]
    first = rows[0]
    assert first.source == "tiingo"
    assert first.close == Decimal("10.000000")
    assert first.adj_close == Decimal("9.000000")
    assert first.volume == 1_000_000
    assert first.ingested_at is not None


def test_successful_run_records_source_range_rows_and_status(ingest_session: Session) -> None:
    _seed(ingest_session, "NVDA")
    provider = _FakeProvider(_THREE_GOOD)

    report = _run(ingest_session, "NVDA", provider, start=_START, end=_END)

    run = ingest_session.scalars(select(DataIngestionRun)).one()
    assert (run.source, run.entity, run.target_ref) == ("tiingo", "prices", "NVDA")
    assert (run.range_start, run.range_end) == (_START, _END)
    assert run.rows_written == 3
    assert run.status == "success"
    assert run.error is None
    assert run.started_at is not None
    assert run.finished_at is not None
    assert run.id == report.run_id


def test_provider_receives_exact_requested_range(ingest_session: Session) -> None:
    _seed(ingest_session, "NVDA")
    provider = _FakeProvider(_THREE_GOOD)
    start, end = datetime.date(2018, 6, 1), datetime.date(2019, 6, 1)

    _run(ingest_session, "NVDA", provider, start=start, end=end)

    assert provider.calls == [("NVDA", start, end)]


def test_start_after_end_is_rejected_before_any_run_row(ingest_session: Session) -> None:
    _seed(ingest_session, "NVDA")
    provider = _FakeProvider(_THREE_GOOD)

    with pytest.raises(ValueError, match="after end"):
        _run(
            ingest_session,
            "NVDA",
            provider,
            start=datetime.date(2021, 1, 1),
            end=datetime.date(2020, 1, 1),
        )

    assert _count(ingest_session, DataIngestionRun) == 0
    assert provider.calls == []


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
def test_identical_reingest_writes_nothing_and_keeps_row_count(ingest_session: Session) -> None:
    sid = _seed(ingest_session, "NVDA")["NVDA"]

    first = _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD))
    ingested_at_after_first = [r.ingested_at for r in _price_rows(ingest_session, sid)]

    second = _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD))
    ingested_at_after_second = [r.ingested_at for r in _price_rows(ingest_session, sid)]

    assert first.inserted == 3
    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 3)
    assert second.rows_written == 0
    assert second.status == "success"
    assert _count(ingest_session, PriceBar) == 3
    # unchanged rows are not rewritten
    assert ingested_at_after_first == ingested_at_after_second

    runs = ingest_session.scalars(select(DataIngestionRun).order_by(DataIngestionRun.id)).all()
    assert [r.rows_written for r in runs] == [3, 0]
    assert [r.status for r in runs] == ["success", "success"]


def test_changed_bar_updates_in_place(ingest_session: Session) -> None:
    sid = _seed(ingest_session, "NVDA")["NVDA"]
    _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD))

    revised = [
        _THREE_GOOD[0],
        _bar("2020-01-03", 10.5, 9.4, high=10.8, low=10.1, volume=1_234_567),  # volume changed
        _bar("2020-01-06", 11.9, 10.9, high=12.0, low=11.4, volume=900_000),  # prices changed
    ]
    report = _run(ingest_session, "NVDA", _FakeProvider(revised))

    assert (report.inserted, report.updated, report.unchanged) == (0, 2, 1)
    assert report.rows_written == 2
    assert report.status == "success"
    assert _count(ingest_session, PriceBar) == 3

    rows = {r.trade_date: r for r in _price_rows(ingest_session, sid)}
    assert rows[datetime.date(2020, 1, 3)].volume == 1_234_567
    assert rows[datetime.date(2020, 1, 6)].close == Decimal("11.900000")
    assert rows[datetime.date(2020, 1, 6)].adj_close == Decimal("10.900000")


# --------------------------------------------------------------------------- #
# Composite key: (security_id, trade_date, source)
# --------------------------------------------------------------------------- #
def test_two_sources_for_same_security_and_date_coexist(ingest_session: Session) -> None:
    sid = _seed(ingest_session, "NVDA")["NVDA"]

    _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD, source="tiingo"))
    report = _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD, source="stooq"))

    assert report.inserted == 3  # not seen as a conflict - different source
    assert _count(ingest_session, PriceBar) == 6
    assert {r.source for r in _price_rows(ingest_session, sid)} == {"tiingo", "stooq"}
    assert len(_price_rows(ingest_session, sid, source="tiingo")) == 3
    assert len(_price_rows(ingest_session, sid, source="stooq")) == 3

    # re-running the stooq side is still idempotent against its own rows only
    again = _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD, source="stooq"))
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 3)
    assert _count(ingest_session, PriceBar) == 6


def test_ingestion_is_scoped_to_the_resolved_security(ingest_session: Session) -> None:
    ids = _seed(ingest_session, "NVDA", "AMD")

    _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD))
    _run(ingest_session, "AMD", _FakeProvider(_THREE_GOOD[:2]))

    assert len(_price_rows(ingest_session, ids["NVDA"])) == 3
    assert len(_price_rows(ingest_session, ids["AMD"])) == 2
    assert {r.security_id for r in _price_rows(ingest_session, ids["AMD"])} == {ids["AMD"]}


# --------------------------------------------------------------------------- #
# Validation boundary: invalid bars never persist
# --------------------------------------------------------------------------- #
def test_invalid_bars_are_dropped_and_never_persisted(ingest_session: Session) -> None:
    sid = _seed(ingest_session, "NVDA")["NVDA"]
    bars = [
        _THREE_GOOD[0],
        _bar("2020-01-03", 10.5, high=1.0, low=9.0),  # high < low -> Pandera reject
        _bar("2020-01-06", -3.0),  # non-positive close -> Pandera reject
        _bar("bad-date", 12.0),  # unparseable trade_date -> normalisation drop
    ]
    report = _run(ingest_session, "NVDA", _FakeProvider(bars))

    assert report.fetched == 4
    assert report.persisted == 1
    assert report.dropped == 3
    assert report.status == "partial"
    assert report.reason_counts  # structured reasons preserved
    assert set(report.reason_counts) <= {
        "impossible_high_low",
        "non_positive_price",
        "invalid_trade_date",
    }

    rows = _price_rows(ingest_session, sid)
    assert [r.trade_date for r in rows] == [datetime.date(2020, 1, 2)]

    run = ingest_session.scalars(select(DataIngestionRun)).one()
    assert run.status == "partial"
    assert run.rows_written == 1


def test_all_bars_invalid_yields_partial_run_with_zero_rows(ingest_session: Session) -> None:
    sid = _seed(ingest_session, "NVDA")["NVDA"]
    bars = [_bar("2020-01-02", -1.0), _bar("2020-01-03", 0.0)]

    report = _run(ingest_session, "NVDA", _FakeProvider(bars))

    assert report.status == "partial"
    assert report.persisted == 0
    assert report.rows_written == 0
    assert _price_rows(ingest_session, sid) == []
    run = ingest_session.scalars(select(DataIngestionRun)).one()
    assert (run.status, run.rows_written) == ("partial", 0)


# --------------------------------------------------------------------------- #
# Failure paths
# --------------------------------------------------------------------------- #
def test_unknown_ticker_fails_without_creating_a_security(ingest_session: Session) -> None:
    _seed(ingest_session, "NVDA")
    provider = _FakeProvider(_THREE_GOOD)

    with pytest.raises(SecurityNotFoundError):
        _run(ingest_session, "ZZZZ", provider)

    assert {s.ticker for s in ingest_session.scalars(select(Security))} == {"NVDA"}
    assert _count(ingest_session, PriceBar) == 0
    assert provider.calls == []  # resolve happens before fetch

    run = ingest_session.scalars(select(DataIngestionRun)).one()
    assert (run.source, run.entity, run.target_ref, run.status) == (
        "tiingo",
        "prices",
        "ZZZZ",
        "failed",
    )
    assert run.error is not None
    assert run.finished_at is not None
    assert run.rows_written == 0


def test_provider_failure_records_failed_run_and_persists_nothing(ingest_session: Session) -> None:
    sid = _seed(ingest_session, "NVDA")["NVDA"]
    provider = _FakeProvider([], raises=PriceProviderRateLimitedError("tiingo: HTTP 429"))

    with pytest.raises(PriceProviderRateLimitedError):
        _run(ingest_session, "NVDA", provider)

    assert _price_rows(ingest_session, sid) == []
    run = ingest_session.scalars(select(DataIngestionRun)).one()
    assert run.status == "failed"
    assert "429" in (run.error or "")
    assert run.rows_written == 0
    assert run.finished_at is not None


def test_db_failure_during_persist_rolls_back_writes_and_finalises_run_failed(
    ingest_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """running row committed -> price writes issued -> DB failure -> rollback ->
    run persisted as failed (not left running), with finished_at + error set,
    and zero price rows accidentally committed.
    """
    sid = _seed(ingest_session, "NVDA")["NVDA"]
    real_upsert = ingest_mod.upsert_price_bars

    def upsert_then_db_failure(
        session: Session, *, security_id: int, source: str, frame: pd.DataFrame
    ) -> PriceUpsertCounts:
        counts = real_upsert(
            session, security_id=security_id, source=source, frame=frame
        )  # real INSERTs into the open txn
        assert counts.written == 3
        # rows are visible inside the transaction, before the failure
        assert session.scalar(select(func.count()).select_from(PriceBar)) == 3
        raise OperationalError(
            "UPDATE data_ingestion_run ...", {}, Exception("simulated DB failure")
        )

    monkeypatch.setattr(ingest_mod, "upsert_price_bars", upsert_then_db_failure)

    with pytest.raises(OperationalError):
        _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD))

    ingest_session.expire_all()
    assert _price_rows(ingest_session, sid) == []  # rolled back - nothing committed
    assert _count(ingest_session, PriceBar) == 0

    run = ingest_session.scalars(select(DataIngestionRun)).one()
    assert run.status == "failed"  # not "running"
    assert run.finished_at is not None
    assert run.error is not None and "simulated DB failure" in run.error
    assert run.rows_written == 0


def test_failed_run_after_partial_history_still_leaves_no_rows(ingest_session: Session) -> None:
    """A provider failure on the second ticker must not affect the first."""
    ids = _seed(ingest_session, "NVDA", "AMD")
    _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD))

    with pytest.raises(PriceProviderRateLimitedError):
        _run(
            ingest_session,
            "AMD",
            _FakeProvider([], raises=PriceProviderRateLimitedError("boom")),
        )

    assert len(_price_rows(ingest_session, ids["NVDA"])) == 3
    assert _price_rows(ingest_session, ids["AMD"]) == []
    runs = ingest_session.scalars(select(DataIngestionRun).order_by(DataIngestionRun.id)).all()
    assert [r.status for r in runs] == ["success", "failed"]


# --------------------------------------------------------------------------- #
# Dry run
# --------------------------------------------------------------------------- #
def test_dry_run_writes_no_rows_and_no_run_record(ingest_session: Session) -> None:
    _seed(ingest_session, "NVDA")

    report = _run(ingest_session, "NVDA", _FakeProvider(_THREE_GOOD), dry_run=True)

    assert report.run_id is None
    assert report.persisted == 3
    assert report.status == "success"
    assert _count(ingest_session, PriceBar) == 0
    assert _count(ingest_session, DataIngestionRun) == 0
