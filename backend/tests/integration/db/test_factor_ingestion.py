"""Database-backed checks for Phase 2B.1 factor ingestion.

Skipped unless ``QUANTSCOPE_TEST_DATABASE_URL`` is set (see conftest). Uses an
in-process fake ``DailyFactorProvider`` - no HTTP, no live Kenneth French fetch.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from quantscope.data.factor_ingest import run_factor_ingestion
from quantscope.data.providers.base import RawFactorReturn
from quantscope.db.models import DataIngestionRun, FactorReturn
from quantscope.db.repositories.factors import get_factor_panel, get_factor_series


class _FakeFactorProvider:
    def __init__(self, records: list[RawFactorReturn], *, source: str = "kenneth_french") -> None:
        self.source_name = source
        self._records = records
        self.calls = 0

    def fetch_daily_factors(self) -> list[RawFactorReturn]:
        self.calls += 1
        return self._records


def _rec(date: str, name: str, value: str) -> RawFactorReturn:
    return RawFactorReturn(trade_date=date, factor_name=name, value=value)


def _two_days() -> list[RawFactorReturn]:
    return [
        _rec("20240102", "mkt_rf", "0.10"),
        _rec("20240102", "smb", "-0.20"),
        _rec("20240102", "hml", "0.30"),
        _rec("20240102", "rf", "0.010"),
        _rec("20240103", "mkt_rf", "-0.05"),
        _rec("20240103", "smb", "0.15"),
        _rec("20240103", "hml", "-0.10"),
        _rec("20240103", "rf", "0.010"),
    ]


def test_all_four_factors_persisted_as_decimal_returns(session: Session) -> None:
    provider = _FakeFactorProvider(_two_days())
    report = run_factor_ingestion(session, provider)

    assert report.status == "success"
    assert report.inserted == 8
    assert report.rows_written == 8

    rf = get_factor_series(session, factor_name="rf", source="kenneth_french", start=None, end=None)
    assert [r.trade_date for r in rf] == [datetime.date(2024, 1, 2), datetime.date(2024, 1, 3)]
    assert [float(r.value) for r in rf] == [0.00010, 0.00010]

    mkt_rf = get_factor_series(
        session, factor_name="mkt_rf", source="kenneth_french", start=None, end=None
    )
    assert float(mkt_rf[0].value) == 0.0010
    assert float(mkt_rf[1].value) == -0.0005


def test_data_ingestion_run_recorded(session: Session) -> None:
    provider = _FakeFactorProvider(_two_days())
    report = run_factor_ingestion(session, provider)

    run = session.get(DataIngestionRun, report.run_id)
    assert run is not None
    assert run.entity == "factors"
    assert run.source == "kenneth_french"
    assert run.target_ref == "ff3_daily"
    assert run.status == "success"
    assert run.rows_written == 8
    assert run.range_start == datetime.date(2024, 1, 2)
    assert run.range_end == datetime.date(2024, 1, 3)
    assert run.finished_at is not None


def test_idempotent_rerun_writes_nothing_new(session: Session) -> None:
    provider = _FakeFactorProvider(_two_days())
    run_factor_ingestion(session, provider)
    before = {
        (row.factor_name, row.trade_date): row.ingested_at
        for row in session.scalars(select(FactorReturn)).all()
    }

    second = run_factor_ingestion(session, _FakeFactorProvider(_two_days()))

    assert second.inserted == 0
    assert second.updated == 0
    assert second.unchanged == 8
    after = {
        (row.factor_name, row.trade_date): row.ingested_at
        for row in session.scalars(select(FactorReturn)).all()
    }
    assert len(after) == 8
    # unchanged rows keep their original ingested_at (no spurious write)
    assert before == after


def test_changed_value_updates_and_bumps_ingested_at(session: Session) -> None:
    run_factor_ingestion(session, _FakeFactorProvider(_two_days()))
    before_ts = session.scalar(
        select(FactorReturn.ingested_at).where(
            FactorReturn.factor_name == "rf",
            FactorReturn.trade_date == datetime.date(2024, 1, 2),
        )
    )

    changed = [
        _rec("20240102", "mkt_rf", "0.10"),
        _rec("20240102", "smb", "-0.20"),
        _rec("20240102", "hml", "0.30"),
        _rec("20240102", "rf", "0.020"),  # changed from 0.010
        _rec("20240103", "mkt_rf", "-0.05"),
        _rec("20240103", "smb", "0.15"),
        _rec("20240103", "hml", "-0.10"),
        _rec("20240103", "rf", "0.010"),
    ]
    report = run_factor_ingestion(session, _FakeFactorProvider(changed))

    assert report.updated == 1
    assert report.unchanged == 7
    assert report.inserted == 0

    row = session.execute(
        select(FactorReturn).where(
            FactorReturn.factor_name == "rf",
            FactorReturn.trade_date == datetime.date(2024, 1, 2),
        )
    ).scalar_one()
    assert float(row.value) == 0.00020
    assert before_ts is not None
    assert row.ingested_at >= before_ts


def test_start_end_trims_the_persisted_window(session: Session) -> None:
    report = run_factor_ingestion(
        session,
        _FakeFactorProvider(_two_days()),
        start=datetime.date(2024, 1, 3),
        end=datetime.date(2024, 1, 3),
    )
    assert report.inserted == 4  # only the second day's 4 factors
    assert report.range_start == datetime.date(2024, 1, 3)
    assert report.range_end == datetime.date(2024, 1, 3)


def test_dry_run_writes_nothing_and_records_no_run(session: Session) -> None:
    provider = _FakeFactorProvider(_two_days())
    report = run_factor_ingestion(session, provider, dry_run=True)

    assert report.run_id is None
    assert report.normalized == 8
    assert session.scalar(select(FactorReturn).limit(1)) is None
    assert session.scalar(select(DataIngestionRun).limit(1)) is None


def test_a_second_source_does_not_merge_with_kenneth_french(session: Session) -> None:
    run_factor_ingestion(session, _FakeFactorProvider(_two_days(), source="kenneth_french"))
    run_factor_ingestion(session, _FakeFactorProvider(_two_days(), source="other_source"))

    kf = get_factor_series(session, factor_name="rf", source="kenneth_french", start=None, end=None)
    other = get_factor_series(
        session, factor_name="rf", source="other_source", start=None, end=None
    )
    assert len(kf) == 2
    assert len(other) == 2
    assert session.scalar(select(FactorReturn)) is not None


def test_get_factor_series_is_ascending_and_date_bounded(session: Session) -> None:
    run_factor_ingestion(session, _FakeFactorProvider(_two_days()))
    rows = get_factor_series(
        session,
        factor_name="rf",
        source="kenneth_french",
        start=datetime.date(2024, 1, 3),
        end=datetime.date(2024, 1, 3),
    )
    assert [r.trade_date for r in rows] == [datetime.date(2024, 1, 3)]


def test_get_factor_panel_returns_all_requested_factors(session: Session) -> None:
    run_factor_ingestion(session, _FakeFactorProvider(_two_days()))
    rows = get_factor_panel(session, source="kenneth_french", start=None, end=None)
    names = {r.factor_name for r in rows}
    assert names == {"mkt_rf", "smb", "hml", "rf"}
    assert len(rows) == 8


def test_upsert_uses_exact_decimal_not_float_drift(session: Session) -> None:
    run_factor_ingestion(session, _FakeFactorProvider([_rec("20240102", "rf", "0.009")]))
    row = session.execute(
        select(FactorReturn).where(FactorReturn.trade_date == datetime.date(2024, 1, 2))
    ).scalar_one()
    assert row.value == Decimal("0.000090")
