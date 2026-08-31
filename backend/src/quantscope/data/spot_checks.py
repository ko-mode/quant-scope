"""Coarse corporate-action sanity checks on a normalised price frame.

Phase 1C ships one: the **NVDA 10-for-1 split, ex-date 2024-06-10** (ADR 0012,
0015, 0022).

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


__all__ = [
    "NVDA_SPLIT_EX_DATE",
    "NVDA_SPLIT_RATIO",
    "SpotCheckResult",
    "check_nvda_split_adjustment",
]
