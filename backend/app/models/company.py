"""Company-level configuration: companies, currencies, rates, tax codes, numbering (ORG)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, Rate, Timestamps, UUIDPk


class Company(UUIDPk, Timestamps, Base):
    __tablename__ = "companies"

    legal_name_en: Mapped[str] = mapped_column(String(200))
    legal_name_km: Mapped[str] = mapped_column(String(200), default="")
    trading_name_en: Mapped[str] = mapped_column(String(200))
    trading_name_km: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    tax_id: Mapped[str] = mapped_column(String(50), default="")
    logo_url: Mapped[str | None] = mapped_column(String(500))
    base_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="USD")
    fiscal_year_start_month: Mapped[int] = mapped_column(SmallInteger, default=1)
    # Configurable policies (tax inclusive, tolerances, SoD mode...). Values are proposals until approved.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="fiscal_month"),)


class Currency(Base):
    __tablename__ = "currencies"

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    symbol: Mapped[str] = mapped_column(String(5))
    decimals: Mapped[int] = mapped_column(SmallInteger)
    cash_rounding_increment: Mapped[Decimal] = mapped_column(Numeric(19, 4))


class ExchangeRate(UUIDPk, Base):
    __tablename__ = "exchange_rates"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    from_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    to_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    rate: Mapped[Rate]
    effective_at: Mapped[datetime] = mapped_column(server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", use_alter=True))

    __table_args__ = (
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("from_currency <> to_currency", name="distinct_currencies"),
    )


class TaxCode(UUIDPk, Authored, Base):
    __tablename__ = "tax_codes"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    # Rates are configuration to be confirmed (V-01), never seeded as fact.
    rate: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("rate >= 0 AND rate <= 100", name="rate_range"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )


class DocumentSequence(Base):
    """Locked FOR UPDATE when allocating numbers; numbers are never reused (BR-DOC-001)."""

    __tablename__ = "document_sequences"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    doc_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    scope_key: Mapped[str] = mapped_column(String(60), primary_key=True, default="")
    prefix: Mapped[str] = mapped_column(String(20))
    next_value: Mapped[int] = mapped_column(default=1)
    padding: Mapped[int] = mapped_column(SmallInteger, default=6)
    include_branch: Mapped[bool] = mapped_column(default=False)
    include_year: Mapped[bool] = mapped_column(default=True)

    __table_args__ = (CheckConstraint("next_value >= 1", name="next_value"),)
