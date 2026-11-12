"""Customers, customer groups and store credit (CUS; Phase 6).

Walk-in sales need no customer (BR-CUS-001). Personal data is masked for users
without customers.personal_data.view, and can be anonymised while sales history is kept.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, Money, UUIDPk


class CustomerGroup(UUIDPk, Authored, Base):
    __tablename__ = "customer_groups"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    # A GROUP price list holding this group's prices; without a price, discount_pct applies to the retail price.
    price_list_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_lists.id"))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 100", name="discount_range"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )


class Customer(UUIDPk, Authored, Base):
    __tablename__ = "customers"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(50), default="")
    # Digits only, for lookup and uniqueness.
    phone_normalised: Mapped[str] = mapped_column(String(30), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_groups.id"))
    notes: Mapped[str] = mapped_column(Text, default="")
    consent_marketing: Mapped[bool] = mapped_column(default=False)
    loyalty_points: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"))
    tier: Mapped[str] = mapped_column(String(20), default="STANDARD")
    store_credit: Mapped[Money] = mapped_column(default=Decimal("0"))
    credit_limit: Mapped[Money] = mapped_column(default=Decimal("0"))
    last_purchase_at: Mapped[datetime | None]
    total_spent: Mapped[Money] = mapped_column(default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    anonymized: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        Index("uq_customers_phone", "company_id", "phone_normalised", unique=True, postgresql_where=text("phone_normalised <> '' AND NOT anonymized")),
        Index("ix_customers_name_trgm", "name", postgresql_using="gin", postgresql_ops={"name": "gin_trgm_ops"}),
        CheckConstraint("store_credit >= 0 AND loyalty_points >= 0 AND credit_limit >= 0", name="balances_non_negative"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )


class StoreCreditEntry(UUIDPk, Base):
    """Every change to a customer's store credit, so the balance is explainable."""

    __tablename__ = "store_credit_entries"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    amount: Mapped[Money]
    balance_after: Mapped[Money]
    reason: Mapped[str] = mapped_column(String(200))
    sale_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales.id"))
    return_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_returns.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (CheckConstraint("amount <> 0 AND balance_after >= 0", name="values"),)
