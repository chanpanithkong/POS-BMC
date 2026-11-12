"""Expenses, promotions and coupons, notifications and imports (EXP, PRM, NTF, IMP; Phase 8)."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, Time, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, Money, UUIDPk


class ExpenseCategory(UUIDPk, Authored, Base):
    __tablename__ = "expense_categories"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (UniqueConstraint("company_id", "code"), CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"))


class Expense(UUIDPk, Authored, Base):
    """Operating expenses, kept apart from inventory cost and COGS (FR-EXP-006)."""

    __tablename__ = "expenses"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    expense_no: Mapped[str] = mapped_column(String(40))
    date: Mapped[date] = mapped_column(Date, index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("expense_categories.id"))
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[Money]
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("1"))
    amount_base: Mapped[Money]
    payment_method: Mapped[str] = mapped_column(String(30))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    attachment_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="SUBMITTED")
    reject_reason: Mapped[str | None] = mapped_column(Text)
    # Set when the expense was paid from a cashier drawer (paid-out).
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cashier_sessions.id"))
    cash_movement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cash_movements.id"))
    approved_by_name: Mapped[str | None] = mapped_column(String(200))
    auto_approved: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        UniqueConstraint("company_id", "expense_no"),
        CheckConstraint("status IN ('SUBMITTED','APPROVED','REJECTED')", name="status"),
        CheckConstraint("amount > 0 AND amount_base > 0", name="amount_positive"),
    )


PROMOTION_TYPES = ("PRODUCT", "CATEGORY", "BOGO", "ORDER", "TIME_BASED")


class Promotion(UUIDPk, Authored, Base):
    __tablename__ = "promotions"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(15))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0"))
    discount_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    product_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    category_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    branch_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    customer_group_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    priority: Mapped[int] = mapped_column(default=0)
    combinable: Mapped[bool] = mapped_column(default=False)
    usage_limit: Mapped[int | None]
    usage_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="PENDING_APPROVAL")
    approved_by_name: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint(f"type IN ({','.join(repr(t) for t in PROMOTION_TYPES)})", name="type"),
        CheckConstraint("status IN ('DRAFT','PENDING_APPROVAL','ACTIVE','EXPIRED','DISABLED')", name="status"),
        CheckConstraint("end_date >= start_date", name="dates"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 100 AND discount_amount >= 0", name="discount"),
        CheckConstraint("usage_limit IS NULL OR usage_limit >= 0", name="usage_limit"),
    )


class Coupon(UUIDPk, Authored, Base):
    __tablename__ = "coupons"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(200), default="")
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0"))
    discount_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    min_spend: Mapped[Money] = mapped_column(default=Decimal("0"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    usage_limit: Mapped[int] = mapped_column(default=0)
    usage_count: Mapped[int] = mapped_column(default=0)
    per_customer_limit: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        Index("uq_coupons_company_code", "company_id", text("upper(code)"), unique=True),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
        CheckConstraint("end_date >= start_date", name="dates"),
        CheckConstraint("discount_pct >= 0 AND discount_pct <= 100 AND discount_amount >= 0 AND min_spend >= 0", name="discount"),
        CheckConstraint("usage_limit >= 0 AND usage_count >= 0 AND per_customer_limit >= 0", name="limits"),
    )


NOTIFICATION_KINDS = ("STOCK_ALERT", "PO_APPROVAL", "RECEIPT_DISCREPANCY", "TRANSFER", "REFUND_APPROVAL", "SESSION_REMINDER", "SYSTEM_ERROR", "APPROVAL")


class Notification(UUIDPk, Base):
    """In-app notification for everyone holding `audience_permission` in `branch_id` (or one user)."""

    __tablename__ = "notifications"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    kind: Mapped[str] = mapped_column(String(25))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    audience_permission: Mapped[str | None] = mapped_column(String(80))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_notifications_company_time", "company_id", "created_at"),
        CheckConstraint(f"kind IN ({','.join(repr(k) for k in NOTIFICATION_KINDS)})", name="kind"),
    )


class NotificationRead(Base):
    __tablename__ = "notification_reads"

    notification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


IMPORT_TYPES = ("PRODUCTS", "BARCODES", "SUPPLIERS", "CUSTOMERS", "OPENING_STOCK", "PRICES", "STOCK_COUNT")


class ImportPreview(Base):
    """Validated rows waiting for commit; expires after an hour (BR-IMP-001)."""

    __tablename__ = "import_previews"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    type: Mapped[str] = mapped_column(String(20))
    file_name: Mapped[str] = mapped_column(String(200))
    file_hash: Mapped[str] = mapped_column(String(128))
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    expires_at: Mapped[datetime]


class ImportBatch(UUIDPk, Base):
    __tablename__ = "import_batches"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    file_name: Mapped[str] = mapped_column(String(200))
    file_hash: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    user_name: Mapped[str] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    total_rows: Mapped[int]
    imported_rows: Mapped[int]
    status: Mapped[str] = mapped_column(String(15), default="COMMITTED")
    created_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    can_rollback: Mapped[bool] = mapped_column(default=False)

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint(f"type IN ({','.join(repr(t) for t in IMPORT_TYPES)})", name="type"),
        CheckConstraint("status IN ('COMMITTED','ROLLED_BACK')", name="status"),
    )
