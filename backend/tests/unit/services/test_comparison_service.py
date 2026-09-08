"""Focused unit tests for the comparison service (no live database).

These cover the *plumbing* only - series assembly from ORM rows, ticker
resolution / thin-history collection (faked via monkeypatch, not a real
session), and dataclass -> schema mapping, including the NaT/NaN -> null
boundary. The statistical correctness of the panel itself is covered by the
Phase 3A quant engine unit tests and is not re-tested here.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import exchange_calendars as xcals
import pandas as pd
import pytest

from quantscope.db.models import PriceBar, Security
from quantscope.quant import ComparisonPanel
from quantscope.services import comparison as svc


def _bar(day: str, adj_close: str, close: str = "999.0") -> PriceBar:
    return PriceBar(
        security_id=1,
        trade_date=datetime.date.fromisoformat(day),
        source="tiingo",
        close=Decimal(close),
        adj_close=Decimal(adj_close),
    )


def _xnys_dates(start: str, n: int) -> pd.DatetimeIndex:
    """``n`` genuine, gap-free XNYS sessions from ``start`` - unlike
    ``pd.bdate_range``, which includes US market holidays (QS-01). The real
    service now excludes any return spanning a missing session, so these
    fixtures must be calendar-continuous to keep their exact observation
    counts meaningful."""
    cal = xcals.get_calendar("XNYS")
    first = cal.date_to_session(start, direction="next")
    return pd.DatetimeIndex(cal.sessions_window(first, n))


def _bars(n: int, *, start: str = "2023-01-02", base: float = 100.0) -> list[PriceBar]:
    pattern = [0.01, -0.008, 0.006, -0.011, 0.009, 0.004, -0.013, 0.012]
    dates = _xnys_dates(start, n)
    prices = [base]
    for i in range(1, n):
        prices.append(round(prices[-1] * (1 + pattern[(i - 1) % len(pattern)]), 6))
    return [_bar(str(d.date()), str(p)) for d, p in zip(dates, prices, strict=True)]


def test_adjusted_close_series_uses_adj_close_not_raw_close() -> None:
    bars = [_bar("2024-01-02", "95.20", close="100.10"), _bar("2024-01-03", "96.00", close="101.0")]
    series = svc._adjusted_close_series(bars)
    assert isinstance(series.index, pd.DatetimeIndex)
    assert list(series) == [95.20, 96.00]
    assert series.dtype == "float64"


def test_compute_comparison_raises_for_unknown_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_lookup(session: object, ticker: str) -> Security | None:
        return (
            Security(id=1, ticker="AAPL", name="Apple", exchange="XNAS")
            if ticker == "AAPL"
            else None
        )

    monkeypatch.setattr(svc, "get_security_by_ticker", _fake_lookup)
    with pytest.raises(svc.UnknownTickerError) as excinfo:
        svc.compute_comparison(
            object(),  # type: ignore[arg-type]
            tickers=["AAPL", "ZZZZ"],
            source="tiingo",
            start=None,
            end=None,
        )
    assert excinfo.value.ticker == "ZZZZ"


def test_compute_comparison_unavailable_lists_every_thin_ticker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    securities = {
        "AAPL": Security(id=1, ticker="AAPL", name="Apple", exchange="XNAS"),
        "MSFT": Security(id=2, ticker="MSFT", name="Microsoft", exchange="XNAS"),
        "NVDA": Security(id=3, ticker="NVDA", name="NVIDIA", exchange="XNAS"),
    }
    bars_by_ticker = {"AAPL": _bars(80), "MSFT": [], "NVDA": [_bar("2023-01-02", "10.0")]}

    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, t: securities[t])
    monkeypatch.setattr(
        svc,
        "get_all_price_bars",
        lambda session, *, security_id, source, start, end: (
            bars_by_ticker[next(t for t, s in securities.items() if s.id == security_id)]
        ),
    )

    response = svc.compute_comparison(
        object(),  # type: ignore[arg-type]
        tickers=["AAPL", "MSFT", "NVDA"],
        source="tiingo",
        start=None,
        end=None,
    )
    assert response.status == "unavailable"
    assert response.reason == "missing_price_history"
    assert response.unavailable_tickers == ["MSFT", "NVDA"]
    assert response.normalized_performance is None
    assert response.correlation is None


def test_compute_comparison_insufficient_when_one_tickers_returns_are_all_gapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RA-03: TWOGAP has exactly 2 price bars (>= 2, so not "thin" by the
    # bar-count check above), and its one possible adjacency spans a missing
    # XNYS session (2024-01-02 Tue -> 2024-01-04 Thu, 01-03 Wed missing) - an
    # empty gap-filtered return series despite persisted price history
    # genuinely existing. This must be `insufficient_observations`,
    # `observations_used == 0`, never `unavailable`/`missing_price_history`
    # (which would misrepresent history that does exist), and never a crash
    # from feeding an empty series into `compare_securities`.
    securities = {
        "AAPL": Security(id=1, ticker="AAPL", name="Apple", exchange="XNAS"),
        "TWOGAP": Security(id=2, ticker="TWOGAP", name="Two Bar Gap Co.", exchange="XNAS"),
    }
    bars_by_ticker = {
        "AAPL": _bars(80),
        "TWOGAP": [_bar("2024-01-02", "100.0"), _bar("2024-01-04", "101.0")],
    }

    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, t: securities[t])
    monkeypatch.setattr(
        svc,
        "get_all_price_bars",
        lambda session, *, security_id, source, start, end: (
            bars_by_ticker[next(t for t, s in securities.items() if s.id == security_id)]
        ),
    )

    response = svc.compute_comparison(
        object(),  # type: ignore[arg-type]
        tickers=["AAPL", "TWOGAP"],
        source="tiingo",
        start=None,
        end=None,
    )
    assert response.status == "insufficient_observations"
    assert response.observations_used == 0
    assert response.required == 60
    assert response.unavailable_tickers is None
    assert response.reason is None
    assert response.normalized_performance is None
    assert response.correlation is None


def test_compute_comparison_insufficient_when_aligned_panel_is_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    securities = {
        "AAPL": Security(id=1, ticker="AAPL", name="Apple", exchange="XNAS"),
        "MSFT": Security(id=2, ticker="MSFT", name="Microsoft", exchange="XNAS"),
    }
    bars = {"AAPL": _bars(10), "MSFT": _bars(10)}  # 9 aligned returns each, well under the 60 gate

    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, t: securities[t])
    monkeypatch.setattr(
        svc,
        "get_all_price_bars",
        lambda session, *, security_id, source, start, end: (
            bars[next(t for t, s in securities.items() if s.id == security_id)]
        ),
    )

    response = svc.compute_comparison(
        object(),  # type: ignore[arg-type]
        tickers=["AAPL", "MSFT"],
        source="tiingo",
        start=None,
        end=None,
    )
    assert response.status == "insufficient_observations"
    assert response.required == 60
    assert response.observations_used == 9
    assert response.aligned_start is None  # no panel bounds when suppressed
    assert response.normalized_performance is None


def test_compute_comparison_ok_maps_the_panel_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    securities = {
        "AAPL": Security(id=1, ticker="AAPL", name="Apple", exchange="XNAS"),
        "MSFT": Security(id=2, ticker="MSFT", name="Microsoft", exchange="XNAS"),
    }
    bars = {"AAPL": _bars(65, base=100.0), "MSFT": _bars(65, base=50.0)}

    monkeypatch.setattr(svc, "get_security_by_ticker", lambda session, t: securities[t])
    monkeypatch.setattr(
        svc,
        "get_all_price_bars",
        lambda session, *, security_id, source, start, end: (
            bars[next(t for t, s in securities.items() if s.id == security_id)]
        ),
    )

    response = svc.compute_comparison(
        object(),  # type: ignore[arg-type]
        tickers=["AAPL", "MSFT"],
        source="tiingo",
        start=None,
        end=None,
    )
    assert response.status == "ok"
    assert response.tickers == ["AAPL", "MSFT"]  # request order preserved
    assert response.observations_used == 64
    assert response.aligned_start is not None and response.aligned_end is not None
    assert response.reason is None
    assert response.unavailable_tickers is None

    norm = response.normalized_performance
    assert norm is not None
    assert len(norm.dates) == 65  # observations_used + 1 anchor
    assert norm.dates[0] is None
    assert norm.series["AAPL"][0] == pytest.approx(100.0)
    assert norm.series["MSFT"][0] == pytest.approx(100.0)

    corr = response.correlation
    assert corr is not None
    assert corr.tickers == ["AAPL", "MSFT"]
    assert corr.matrix[0][0] == pytest.approx(1.0)
    assert corr.matrix[0][1] == corr.matrix[1][0]


def test_ok_response_maps_nat_anchor_and_nan_correlation_to_null() -> None:
    dates = pd.DatetimeIndex([pd.NaT, pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")])
    normalized = pd.DataFrame(
        {"AAPL": [100.0, 101.0, 99.0], "FLAT": [100.0, 100.0, 100.0]}, index=dates
    )
    returns = pd.DataFrame(
        {"AAPL": [0.01, -0.0198], "FLAT": [0.0, 0.0]},
        index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"]),
    )
    correlation = pd.DataFrame(
        {"AAPL": [1.0, float("nan")], "FLAT": [float("nan"), float("nan")]},
        index=["AAPL", "FLAT"],
    )
    panel = ComparisonPanel(
        tickers=("AAPL", "FLAT"),
        observations_used=2,
        aligned_start=pd.Timestamp("2024-01-02"),
        aligned_end=pd.Timestamp("2024-01-03"),
        normalized_performance=normalized,
        returns=returns,
        correlation=correlation,
        zero_variance_tickers=("FLAT",),
    )

    response = svc._ok_response(panel, source="tiingo", start=None, end=None)
    assert response.normalized_performance is not None
    assert response.normalized_performance.dates[0] is None
    assert response.normalized_performance.dates[1] == datetime.date(2024, 1, 2)

    assert response.correlation is not None
    assert response.correlation.matrix[0][0] == pytest.approx(1.0)
    assert response.correlation.matrix[0][1] is None
    assert response.correlation.matrix[1][1] is None
    assert response.zero_variance_tickers == ["FLAT"]
