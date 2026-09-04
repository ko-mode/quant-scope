"""Parsing the Kenneth French daily FF3 CSV body (pure; no I/O)."""

from __future__ import annotations

import pytest

from quantscope.data.providers.base import FactorDataUnavailableError, FactorProviderBlockedError
from quantscope.data.providers.french_factors import parse_ff_daily_factors

_HEADER = ",Mkt-RF,SMB,HML,RF"


def _body(preamble: str, rows: str, footer: str = "") -> str:
    return f"{preamble}\n{_HEADER}\n{rows}{footer}"


def test_parses_valid_daily_rows() -> None:
    text = _body(
        "This file was created by CMPT_ME_BEHAVIOR_DAILY using the 202401 CRSP database.",
        "19260701,0.10,-0.24,-0.28,0.009\n20240628,-0.20,0.30,0.68,0.021\n",
    )
    records = parse_ff_daily_factors(text)
    assert len(records) == 8  # 2 dates x 4 factors
    by_key = {(r.trade_date, r.factor_name): r.value for r in records}
    assert by_key[("19260701", "mkt_rf")] == "0.10"
    assert by_key[("19260701", "smb")] == "-0.24"
    assert by_key[("19260701", "hml")] == "-0.28"
    assert by_key[("19260701", "rf")] == "0.009"
    assert by_key[("20240628", "mkt_rf")] == "-0.20"


def test_header_found_after_a_varying_length_preamble() -> None:
    text = _body(
        "line one\nline two\nline three describing the file\n",
        "19260701,0.10,-0.24,-0.28,0.009\n",
    )
    records = parse_ff_daily_factors(text)
    assert len(records) == 4


def test_whitespace_around_cells_is_stripped() -> None:
    text = _body("desc", "20240701,  0.55 , -0.10 ,  0.05 , 0.021 \n")
    records = parse_ff_daily_factors(text)
    values = {r.factor_name: r.value for r in records}
    assert values == {"mkt_rf": "0.55", "smb": "-0.10", "hml": "0.05", "rf": "0.021"}


def test_footer_and_trailing_blank_lines_are_ignored() -> None:
    text = _body(
        "desc",
        "19260701,0.10,-0.24,-0.28,0.009\n20240628,-0.20,0.30,0.68,0.021\n",
        footer="\n\n  Copyright 2024 Kenneth R. French\n",
    )
    records = parse_ff_daily_factors(text)
    assert len(records) == 8
    assert all(r.trade_date in {"19260701", "20240628"} for r in records)


def test_short_row_is_skipped_not_crashed_on() -> None:
    text = _body(
        "desc",
        "19260701,0.10,-0.24,-0.28,0.009\n20240628,-0.20,0.30\n20240629,0.01,0.02,0.03,0.04\n",
    )
    records = parse_ff_daily_factors(text)
    dates = {r.trade_date for r in records}
    assert dates == {"19260701", "20240629"}


def test_no_header_row_raises_data_unavailable() -> None:
    with pytest.raises(FactorDataUnavailableError):
        parse_ff_daily_factors("just some text\nwith no header\n19260701,1,2,3,4\n")


def test_header_with_no_data_rows_raises_data_unavailable() -> None:
    with pytest.raises(FactorDataUnavailableError):
        parse_ff_daily_factors(f"desc\n{_HEADER}\n\nCopyright notice only\n")


def test_html_challenge_page_raises_blocked() -> None:
    with pytest.raises(FactorProviderBlockedError):
        parse_ff_daily_factors("<html><body>verify you are human</body></html>")


def test_uninterpreted_values_stay_in_percent_not_decimal() -> None:
    # The parser must NOT convert units - that is normalize_factor_returns' job.
    text = _body("desc", "19260701,0.10,-0.24,-0.28,0.009\n")
    records = parse_ff_daily_factors(text)
    rf = next(r for r in records if r.factor_name == "rf")
    assert rf.value == "0.009"
