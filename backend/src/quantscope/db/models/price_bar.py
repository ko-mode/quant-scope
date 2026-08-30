"""``price_bar`` - one daily OHLCV bar per (security, trade date, source).

See docs/architecture.md section 7 and ADR 0012 (total return via vendor
``adj_close``; raw ``close`` retained for later reconstruction).

The natural composite primary key ``(security_id, trade_date, source)`` doubles
as the lookup index: its leading columns serve "series for a security over a
date range" queries, so no separate ``(security_id, trade_date)`` index is
created.

The foreign key to ``security`` is ``ON DELETE RESTRICT``: a security is the
stable root of its historical observations, so deleting one with price bars is
refused. Lifecycle changes use ``security.is_active`` / ``security.delisted_date``,
not row deletion (ADR 0011).
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from quantscope.db.base import Base

#: Numeric type for all price columns: 18 digits total, 6 after the point.
_PRICE = Numeric(precision=18, scale=6)


class PriceBar(Base):
    __tablename__ = "price_bar"

    security_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("security.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    trade_date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), primary_key=True)

    open: Mapped[Decimal | None] = mapped_column(_PRICE)
    high: Mapped[Decimal | None] = mapped_column(_PRICE)
    low: Mapped[Decimal | None] = mapped_column(_PRICE)
    close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    adj_close: Mapped[Decimal] = mapped_column(_PRICE, nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger)

    ingested_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("close > 0", name="close_positive"),
        CheckConstraint("adj_close > 0", name="adj_close_positive"),
        CheckConstraint("open IS NULL OR open > 0", name="open_positive"),
        CheckConstraint("high IS NULL OR high > 0", name="high_positive"),
        CheckConstraint("low IS NULL OR low > 0", name="low_positive"),
        CheckConstraint("high IS NULL OR low IS NULL OR high >= low", name="high_ge_low"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="volume_non_negative"),
        CheckConstraint("char_length(source) > 0", name="source_not_blank"),
    )
