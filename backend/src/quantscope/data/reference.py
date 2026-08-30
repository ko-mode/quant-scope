"""Normalisation and classification of raw security reference records.

Pure functions: a :class:`~quantscope.data.providers.base.RawSecurityRecord` in,
a :class:`NormalizedSecurity` or a :class:`RejectedRecord` out. No I/O, no
database. Nothing here guesses - a field that cannot be determined reliably is
left ``None`` (or the whole record is rejected with an explicit reason).

Exchange normalisation (ADR 0021)
--------------------------------
``security.exchange`` is a **normalised code derived from the single exchange
label SEC publishes** in ``company_tickers_exchange.json``. It is *not*
independently verified listing-venue metadata: the SEC label is mapped
mechanically to a MIC-style code by :data:`_EXCHANGE_CODE_BY_SEC_LABEL`, and no
cross-provider check is performed. It may differ from a security's authoritative
primary-listing MIC (e.g. SEC labels ``SPY`` as ``"NYSE"`` -> ``XNYS``, though
SPY primarily trades on NYSE Arca).

Sub-market tiers (Nasdaq Global Select vs Capital Market, etc.) are collapsed -
SEC does not carry them, and every supported venue shares the XNYS/US session
calendar (ADR 0006).

**V1 seeds exchange-listed US securities only.** ``OTC`` is a recognised label
but is **excluded** from the V1 universe (reason ``unsupported_exchange_v1:OTC``)
because over-the-counter names bring extra price-availability, liquidity,
market-calendar, ticker-normalisation and data-quality concerns. Adding ``"OTC"``
to :data:`SUPPORTED_EXCHANGES` (with the handling it needs) is all that is
required to include it later. An unmapped or missing label is rejected as
``unmapped_or_missing_exchange`` - never guessed.

Asset-type classification (ADR 0021)
-----------------------------------
``company_tickers_exchange.json`` has no asset-type field. ``asset_type`` is set
only from :data:`_CURATED_ETF_TICKERS`, a small hand-maintained, source-cited
list of unmistakable ETFs. Every other record gets ``asset_type = None``. No
inference from names, exchange, or filing type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from quantscope.data.providers.base import RawSecurityRecord

MAX_TICKER_LEN = 32

# SEC exchange label (lower-cased, trimmed) -> normalised exchange code.
# Values are MIC-style codes; "OTC" is a sentinel for over-the-counter (no
# listing MIC). This is a mechanical mapping of SEC's label, not verified
# venue metadata.
_EXCHANGE_CODE_BY_SEC_LABEL: dict[str, str] = {
    "nyse": "XNYS",
    "new york stock exchange": "XNYS",
    "nasdaq": "XNAS",
    "nasdaq stock market": "XNAS",
    "nyse american": "XASE",
    "nyse mkt": "XASE",
    "amex": "XASE",
    "nyse arca": "ARCX",
    "arca": "ARCX",
    "cboe": "BATS",
    "cboe bzx": "BATS",
    "bats": "BATS",
    "bzx": "BATS",
    "iex": "IEXG",
    "otc": "OTC",
}

#: Every code :func:`normalize_exchange` can return (recognised SEC labels).
RECOGNISED_EXCHANGES: frozenset[str] = frozenset(_EXCHANGE_CODE_BY_SEC_LABEL.values())

#: Codes accepted into the V1 seeded universe - exchange-listed venues only.
#: Add "OTC" here (plus the downstream handling it needs) to widen the universe.
SUPPORTED_EXCHANGES: frozenset[str] = RECOGNISED_EXCHANGES - {"OTC"}

#: Unmistakable ETFs, classified out of band (not derived from the SEC file).
_CURATED_ETF_TICKERS: frozenset[str] = frozenset(
    {
        "SPY",  # SPDR S&P 500 ETF Trust
        "QQQ",  # Invesco QQQ Trust
        "IWM",  # iShares Russell 2000 ETF
        "DIA",  # SPDR Dow Jones Industrial Average ETF Trust
        "VOO",  # Vanguard S&P 500 ETF
        "VTI",  # Vanguard Total Stock Market ETF
        "IVV",  # iShares Core S&P 500 ETF
    }
)

_CIK_DIGITS = re.compile(r"^[0-9]+$")
_TICKER_ALLOWED = re.compile(r"^[A-Z0-9.\-]+$")


@dataclass(frozen=True, slots=True)
class NormalizedSecurity:
    ticker: str
    name: str
    cik: str | None
    exchange: str
    asset_type: str | None


@dataclass(frozen=True, slots=True)
class RejectedRecord:
    raw: RawSecurityRecord
    reason: str


class InvalidCikError(ValueError):
    """A CIK value was present but not 1-10 digits."""


def normalize_cik(raw: str | int | None) -> str | None:
    """Return a zero-padded 10-digit CIK, or ``None`` when the source gave none.

    Raises :class:`InvalidCikError` for a present-but-malformed value (non-numeric
    or more than 10 digits) so the caller can reject the record explicitly.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    if not _CIK_DIGITS.match(text):
        raise InvalidCikError(f"non-numeric CIK: {raw!r}")
    trimmed = text.lstrip("0") or "0"
    if len(trimmed) > 10:
        raise InvalidCikError(f"CIK has more than 10 digits: {raw!r}")
    return trimmed.zfill(10)


def normalize_ticker(raw: str | None) -> str | None:
    """Upper-case, trim. Returns ``None`` when unusable (caller rejects)."""
    if raw is None:
        return None
    text = raw.strip().upper()
    if text == "" or len(text) > MAX_TICKER_LEN or not _TICKER_ALLOWED.match(text):
        return None
    return text


def normalize_exchange(raw: str | None) -> str | None:
    """Map a SEC exchange label to its normalised code, or ``None`` if unrecognised.

    Returns recognised codes including ``"OTC"``; whether a code is *accepted*
    into the V1 universe is decided by :data:`SUPPORTED_EXCHANGES`.
    """
    if raw is None:
        return None
    return _EXCHANGE_CODE_BY_SEC_LABEL.get(raw.strip().lower())


def classify_asset_type(ticker: str) -> str | None:
    """``'etf'`` for a curated ETF ticker; ``None`` otherwise (undetermined)."""
    return "etf" if ticker in _CURATED_ETF_TICKERS else None


def normalize_record(raw: RawSecurityRecord) -> NormalizedSecurity | RejectedRecord:
    ticker = normalize_ticker(raw.ticker)
    if ticker is None:
        return RejectedRecord(raw, f"invalid_or_missing_ticker:{raw.ticker!r}")

    name = (raw.name or "").strip()
    if name == "":
        return RejectedRecord(raw, "missing_name")

    try:
        cik = normalize_cik(raw.cik)
    except InvalidCikError as exc:
        return RejectedRecord(raw, f"invalid_cik:{exc}")

    code = normalize_exchange(raw.exchange)
    if code is None:
        return RejectedRecord(raw, f"unmapped_or_missing_exchange:{raw.exchange!r}")
    if code not in SUPPORTED_EXCHANGES:
        return RejectedRecord(raw, f"unsupported_exchange_v1:{code}")

    return NormalizedSecurity(
        ticker=ticker,
        name=name,
        cik=cik,
        exchange=code,
        asset_type=classify_asset_type(ticker),
    )


@dataclass(frozen=True, slots=True)
class NormalizationOutcome:
    securities: list[NormalizedSecurity]
    rejected: list[RejectedRecord]

    @property
    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.rejected:
            key = item.reason.split(":", 1)[0]
            counts[key] = counts.get(key, 0) + 1
        return counts


def normalize_records(raw_records: list[RawSecurityRecord]) -> NormalizationOutcome:
    """Normalise a whole snapshot and de-duplicate by ticker (first wins)."""
    securities: list[NormalizedSecurity] = []
    rejected: list[RejectedRecord] = []
    seen: set[str] = set()

    for raw in raw_records:
        result = normalize_record(raw)
        if isinstance(result, RejectedRecord):
            rejected.append(result)
            continue
        if result.ticker in seen:
            rejected.append(RejectedRecord(raw, f"duplicate_ticker_in_snapshot:{result.ticker}"))
            continue
        seen.add(result.ticker)
        securities.append(result)

    return NormalizationOutcome(securities=securities, rejected=rejected)
