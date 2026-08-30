"""``security`` - reference data for the searchable US-equity universe.

See docs/architecture.md section 7 and ADRs 0004 (provenance / schema minimalism),
0006 (US equities, USD only), 0011 (``security_id`` is the universal FK).

The surrogate ``id`` is the join key for every other table; ``ticker`` is a
current-value attribute only and is never referenced by a foreign key.
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Identity,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from quantscope.db.base import Base

#: Allowed values for :attr:`Security.asset_type` (architecture.md section 7).
ASSET_TYPES: tuple[str, ...] = ("common_stock", "etf", "index")


class Security(Base):
    __tablename__ = "security"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cik: Mapped[str | None] = mapped_column(String(10))
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'USD'"))
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    first_trade_date: Mapped[datetime.date | None] = mapped_column(Date)
    last_trade_date: Mapped[datetime.date | None] = mapped_column(Date)
    delisted_date: Mapped[datetime.date | None] = mapped_column(Date)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "asset_type IN ('common_stock', 'etf', 'index')",
            name="asset_type_allowed",
        ),
        CheckConstraint("currency = 'USD'", name="currency_usd_only"),
        CheckConstraint("char_length(ticker) > 0", name="ticker_not_blank"),
        CheckConstraint("cik IS NULL OR cik ~ '^[0-9]{10}$'", name="cik_10_digits"),
        CheckConstraint(
            "delisted_date IS NULL OR is_active = false",
            name="delisted_implies_inactive",
        ),
        # Fuzzy ticker/name search (pg_trgm). Created by migration 0001.
        Index(
            "ix_security_ticker_trgm",
            "ticker",
            postgresql_using="gin",
            postgresql_ops={"ticker": "gin_trgm_ops"},
        ),
        Index(
            "ix_security_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )
