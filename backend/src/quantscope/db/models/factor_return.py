"""``factor_return`` - one daily factor value per (factor, frequency, date, source).

Holds the Kenneth R. French research factors (Mkt-RF, SMB, HML) and the
risk-free rate (RF) as **decimal daily returns** - the source publishes them in
percent and the ingestion layer divides by 100 before persistence (ADR 0009).

The primary key ``(factor_name, frequency, trade_date, source)`` follows
ADR 0009: the ``frequency`` column (``'daily'`` in V1) keeps monthly factors,
FF5 and momentum addable as data, without a schema change. Its leading columns
also serve "one factor's series over a date range" scans, so no separate index
is created.

There is **no foreign key to ``security``** - factors are market-wide series,
not securities. Provenance is ``source`` + ``ingested_at``; each ingestion run is
recorded in ``data_ingestion_run`` with ``entity = 'factors'`` (ADR 0003).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from quantscope.db.base import Base

#: Canonical factor names persisted in :attr:`FactorReturn.factor_name`.
FACTOR_NAMES: tuple[str, ...] = ("mkt_rf", "smb", "hml", "rf")
#: Frequencies persisted in :attr:`FactorReturn.frequency` (V1: daily only).
FACTOR_FREQUENCIES: tuple[str, ...] = ("daily",)

#: Same exact-decimal type as price columns: 18 digits, 6 after the point.
#: FF publishes percent to 2 dp -> decimal has <= 4 dp -> scale 6 is exact.
_FACTOR_VALUE = Numeric(precision=18, scale=6)


class FactorReturn(Base):
    __tablename__ = "factor_return"

    factor_name: Mapped[str] = mapped_column(String(16), primary_key=True)
    frequency: Mapped[str] = mapped_column(String(8), primary_key=True)
    trade_date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)

    value: Mapped[Decimal] = mapped_column(_FACTOR_VALUE, nullable=False)

    ingested_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "factor_name IN ('mkt_rf', 'smb', 'hml', 'rf')",
            name="factor_name_allowed",
        ),
        # Relaxed to add 'monthly' when monthly factors are ingested (ADR 0009).
        CheckConstraint("frequency = 'daily'", name="frequency_allowed"),
        CheckConstraint("char_length(source) > 0", name="source_not_blank"),
    )
