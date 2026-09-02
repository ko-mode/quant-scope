"""Coarse corporate-action sanity checks.

* :func:`check_nvda_split_adjustment` - runs on a **normalised price frame** and
  checks the NVDA 10-for-1 split (ex-date 2024-06-10) shows no ~10x
  discontinuity in ``adj_close``.
* :func:`verify_dividend_back_adjustment` - pure arithmetic on six numbers taken
  from *any* provider's raw payload (raw close, adjusted close, divCash,
  splitFactor); checks whether the adjusted series incorporates a dividend, i.e.
  whether ``adj_close.pct_change()`` is a total-return series (ADR 0012, 0022).

Both are provider-independent (ADR 0022, Phase 1C).

What ``check_nvda_split_adjustment`` proves
-----------------------------------------
* The provider's ``adj_close`` series for NVDA shows **no ~10x discontinuity**
  across the split ex-date (i.e. it is split-adjusted around this one event).
* The values sit in a plausible range for NVDA's known post-split price
  (hand-transcribed reference points, +/-15%).

What it does **not** prove
--------------------------
* That ``adj_close`` is dividend-adjusted.
* That adjustment is correct for any other split, ticker, or period.
* That the values are accurate to any precision, or that Stooq's ``close`` is
  raw vs adjusted.
* That the provider is reliable or authoritative. A pass here is **not** grounds
  to treat the vendor adjusted close as authoritative.

Reference points are approximate public knowledge (NVDA traded ~$110-135
split-adjusted in June 2024); they are **not** copied from any provider response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

NVDA_SPLIT_EX_DATE = date(2024, 6, 10)
NVDA_SPLIT_RATIO = 10.0

# Hand-transcribed, approximate, split-adjusted NVDA closes (public knowledge).
_NVDA_REFERENCE_ADJ_CLOSE: dict[date, float] = {
    date(2024, 6, 7): 120.9,
    date(2024, 6, 10): 121.8,
    date(2024, 6, 12): 125.2,
    date(2024, 7, 1): 124.3,
}
_REFERENCE_TOLERANCE = 0.15
_NO_CLIFF_RANGE = (0.6, 1.6)
# The frame must span at least a few sessions each side of the ex-date.
_WINDOW_START = pd.Timestamp(2024, 6, 4)
_WINDOW_END = pd.Timestamp(2024, 6, 13)


@dataclass(frozen=True, slots=True)
class SpotCheckResult:
    name: str
    passed: bool
    ratio_across_split: float | None
    observations: tuple[str, ...]


def check_nvda_split_adjustment(frame: pd.DataFrame) -> SpotCheckResult:
    """Run the NVDA split spot-check against a normalised NVDA price frame."""
    obs: list[str] = []
    if frame.empty or "adj_close" not in frame.columns:
        return SpotCheckResult("nvda_10for1_2024-06-10", False, None, ("frame is empty",))

    dates = pd.to_datetime(frame["trade_date"])
    if dates.min() > _WINDOW_START or dates.max() < _WINDOW_END:
        return SpotCheckResult(
            "nvda_10for1_2024-06-10",
            False,
            None,
            (
                f"frame does not cover the split window "
                f"({_WINDOW_START.date()}..{_WINDOW_END.date()}); "
                f"have {dates.min().date()}..{dates.max().date()}",
            ),
        )

    ex = pd.Timestamp(NVDA_SPLIT_EX_DATE)
    before = frame.loc[dates < ex].iloc[-1]
    on_after = frame.loc[dates >= ex].iloc[0]
    ratio = float(before["adj_close"]) / float(on_after["adj_close"])
    obs.append(
        f"adj_close {pd.Timestamp(before['trade_date']).date()}={float(before['adj_close']):.2f} -> "
        f"{pd.Timestamp(on_after['trade_date']).date()}={float(on_after['adj_close']):.2f}  ratio={ratio:.3f}"
    )

    no_cliff = _NO_CLIFF_RANGE[0] <= ratio <= _NO_CLIFF_RANGE[1]
    if no_cliff:
        obs.append("no ~10x discontinuity across the ex-date (series is split-adjusted here)")
    else:
        obs.append(
            f"DISCONTINUITY across ex-date: ratio {ratio:.2f} "
            f"(~split ratio {NVDA_SPLIT_RATIO:g} => series looks unadjusted)"
        )

    by_date = {
        pd.Timestamp(d).date(): float(v)
        for d, v in zip(frame["trade_date"], frame["adj_close"], strict=True)
    }
    hits = 0
    checked = 0
    for ref_date, expected in _NVDA_REFERENCE_ADJ_CLOSE.items():
        actual = by_date.get(ref_date)
        if actual is None:
            continue
        checked += 1
        within = abs(actual - expected) / expected <= _REFERENCE_TOLERANCE
        hits += int(within)
        obs.append(
            f"ref {ref_date}: expected ~{expected:.1f}, got {actual:.2f} "
            f"({'ok' if within else 'OUT OF RANGE'})"
        )
    references_ok = checked > 0 and hits >= min(3, checked)
    obs.append(f"reference points within +/-{int(_REFERENCE_TOLERANCE * 100)}%: {hits}/{checked}")

    return SpotCheckResult(
        name="nvda_10for1_2024-06-10",
        passed=bool(no_cliff and references_ok),
        ratio_across_split=ratio,
        observations=tuple(obs),
    )


# --------------------------------------------------------------------------- #
# Dividend back-adjustment semantics (provider-independent, ADR 0022)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class DividendCheckResult:
    name: str
    passed: bool
    dividend_incorporated: bool
    reported_dividend: float
    implied_dividend: float
    adj_total_return: float
    raw_price_return: float
    observations: tuple[str, ...]


def verify_dividend_back_adjustment(
    *,
    close_before: float,
    close_ex: float,
    adj_close_before: float,
    adj_close_ex: float,
    dividend: float,
    split_factor_ex: float = 1.0,
    abs_tol: float | None = None,
) -> DividendCheckResult:
    """Check whether an adjusted series folds a dividend back into prices.

    Inputs are the raw and adjusted closes on the last session **before** an
    ex-dividend date and on the ex-date session, the cash dividend on that
    ex-date, and its split factor. All values are as the provider reported them;
    the check verifies an *economic relationship*, not copied numbers.

    For a CRSP-style dividend back-adjustment with no split in the step, holding
    across the ex-date returns ``(close_ex + dividend) / close_before``, so the
    adjusted series should satisfy
    ``adj_close_ex / adj_close_before == (close_ex + dividend) / close_before``.
    Rearranged, the dividend *implied* by the adjustment is
    ``close_before * (adj_close_ex / adj_close_before) - close_ex``; it should
    match the reported ``divCash``. If instead the adjusted return equals the raw
    price return (implied dividend ~ 0), the series is split-only and
    ``adj_close.pct_change()`` would understate total return.
    """
    obs: list[str] = []
    name = "dividend_back_adjustment"

    def _fail(reason: str, *, incorporated: bool = False) -> DividendCheckResult:
        return DividendCheckResult(
            name,
            False,
            incorporated,
            float(dividend),
            float("nan"),
            float("nan"),
            float("nan"),
            (reason,),
        )

    for label, value in (
        ("close_before", close_before),
        ("close_ex", close_ex),
        ("adj_close_before", adj_close_before),
        ("adj_close_ex", adj_close_ex),
    ):
        if not value > 0:
            return _fail(f"{label} is not positive ({value!r})")
    if abs(split_factor_ex - 1.0) > 1e-9:
        return _fail(
            f"step contains a split (splitFactor={split_factor_ex}); choose a split-free ex-dividend date"
        )
    if not dividend > 0:
        return _fail(f"reported dividend is not positive ({dividend!r}); not an ex-dividend step")

    adj_total_return = adj_close_ex / adj_close_before - 1.0
    raw_price_return = close_ex / close_before - 1.0
    implied_dividend = close_before * (adj_close_ex / adj_close_before) - close_ex

    tol = abs_tol if abs_tol is not None else max(0.01, 0.10 * dividend)
    matches_reported = abs(implied_dividend - dividend) <= tol
    is_nonzero = implied_dividend > tol

    dividend_incorporated = bool(matches_reported and is_nonzero)

    obs.append(f"adj total return across ex-date: {adj_total_return * 100:+.4f}%")
    obs.append(f"raw price return across ex-date: {raw_price_return * 100:+.4f}%")
    obs.append(
        f"dividend implied by adjustment: {implied_dividend:.4f}  "
        f"(reported divCash {dividend:.4f}, tolerance +/-{tol:.4f})"
    )
    if dividend_incorporated:
        obs.append(
            "adjusted series incorporates the dividend -> adj_close.pct_change() is a "
            "TOTAL-RETURN series (compatible with ADR 0012)"
        )
    elif is_nonzero:
        obs.append(
            "adjusted series moves across the ex-date but the implied dividend does not "
            "match divCash -> adjustment semantics UNCLEAR"
        )
    else:
        obs.append(
            "adjusted return == raw price return -> dividend NOT incorporated (split-only). "
            "adj_close.pct_change() would UNDERSTATE total return -- CONTRADICTS ADR 0012."
        )

    return DividendCheckResult(
        name=name,
        passed=dividend_incorporated,
        dividend_incorporated=dividend_incorporated,
        reported_dividend=float(dividend),
        implied_dividend=float(implied_dividend),
        adj_total_return=float(adj_total_return),
        raw_price_return=float(raw_price_return),
        observations=tuple(obs),
    )


__all__ = [
    "NVDA_SPLIT_EX_DATE",
    "NVDA_SPLIT_RATIO",
    "DividendCheckResult",
    "SpotCheckResult",
    "check_nvda_split_adjustment",
    "verify_dividend_back_adjustment",
]
