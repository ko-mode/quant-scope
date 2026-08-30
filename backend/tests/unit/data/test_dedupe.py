"""Snapshot-level de-duplication and reason accounting in ``normalize_records``."""

from __future__ import annotations

from quantscope.data.providers.base import RawSecurityRecord
from quantscope.data.reference import normalize_records


def _raw(ticker: str, name: str, cik: str, exchange: str = "Nasdaq") -> RawSecurityRecord:
    return RawSecurityRecord(ticker=ticker, name=name, cik=cik, exchange=exchange)


def test_duplicate_ticker_keeps_first_and_rejects_rest() -> None:
    outcome = normalize_records(
        [
            _raw("NVDA", "NVIDIA CORP", "1045810"),
            _raw("NVDA", "NVIDIA (dup)", "1045810"),
        ]
    )
    assert [s.name for s in outcome.securities] == ["NVIDIA CORP"]
    assert len(outcome.rejected) == 1
    assert outcome.rejected[0].reason.startswith("duplicate_ticker_in_snapshot:NVDA")


def test_same_cik_different_tickers_all_kept() -> None:
    outcome = normalize_records(
        [
            _raw("GOOGL", "Alphabet Inc. Class A", "1652044"),
            _raw("GOOG", "Alphabet Inc. Class C", "1652044"),
        ]
    )
    assert sorted(s.ticker for s in outcome.securities) == ["GOOG", "GOOGL"]
    assert outcome.rejected == []


def test_reason_counts_group_by_prefix() -> None:
    outcome = normalize_records(
        [
            _raw("OK", "Fine Co", "1"),
            _raw("BAD1", "No Exchange", "2", exchange=""),
            _raw("BAD2", "Weird Venue", "3", exchange="Toronto"),
            _raw("BAD3", "Bad Cik", "12A"),
            _raw("OTC1", "Pink Sheet Co", "4", exchange="OTC"),
        ]
    )
    assert len(outcome.securities) == 1
    assert outcome.reason_counts == {
        "unmapped_or_missing_exchange": 2,
        "invalid_cik": 1,
        "unsupported_exchange_v1": 1,
    }
