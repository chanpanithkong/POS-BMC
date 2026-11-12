"""Sales, payments, cashier sessions, returns and refunds (POS, PAY, CSH, SAL, DOC, RET; Phase 5).

Sale lines keep snapshots of name, unit, price, discount, tax and cost, so later
catalogue changes never alter completed sales (BR-SAL-005). Finalized sales are
never deleted or edited; corrections are voids, returns and refunds that reference
the original (BR-SAL-003, BR-SAL-004).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Money, Quantity, Rate, UUIDPk


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({','.join(repr(v) for v in values)})"


SESSION_STATUS = ("OPEN", "CLOSING", "CLOSED", "FORCE_CLOSED")
SALE_STATUS = ("DRAFT", "HELD", "PENDING_PAYMENT", "FINALIZED", "CANCELLED", "VOIDED")
SALE_PAYMENT_STATUS = ("UNPAID", "PARTIALLY_PAID", "PAID", "PARTIALLY_REFUNDED", "REFUNDED", "ON_ACCOUNT")
PAYMENT_STATUS = ("PENDING", "AUTHORIZED", "COMPLETED", "FAILED", "CANCELLED", "PARTIALLY_REFUNDED", "REFUNDED")
PAYMENT_METHODS = ("CASH", "CARD", "QR", "BANK_TRANSFER", "STORE_CREDIT", "EXCHANGE_CREDIT")


class CashierSession(UUIDPk, Base):
    __tablename__ = "cashier_sessions"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    session_no: Mapped[str] = mapped_column(String(40))
    terminal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pos_terminals.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"))
    cashier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(15), default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    closed_at: Mapped[datetime | None]
    business_date: Mapped[date] = mapped_column(Date)
    opening_usd: Mapped[Money]
    opening_khr: Mapped[Money]
    witness: Mapped[str | None] = mapped_column(String(200))
    counted_usd: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    counted_khr: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    denominations: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expected_usd: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    expected_khr: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    variance_usd: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    variance_khr: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    variance_reason: Mapped[str | None] = mapped_column(Text)
    needs_approval: Mapped[bool] = mapped_column(default=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("company_id", "session_no"),
        CheckConstraint(_in("status", SESSION_STATUS), name="status"),
        CheckConstraint("opening_usd >= 0 AND opening_khr >= 0", name="opening_non_negative"),
        # One open session per terminal and per cashier (BR-CSH-003).
        Index("uq_cashier_sessions_open_terminal", "terminal_id", unique=True, postgresql_where=text("status IN ('OPEN','CLOSING')")),
        Index("uq_cashier_sessions_open_cashier", "cashier_id", unique=True, postgresql_where=text("status IN ('OPEN','CLOSING')")),
    )


class CashMovement(UUIDPk, Base):
    __tablename__ = "cash_movements"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cashier_sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    amount: Mapped[Money]
    reason: Mapped[str] = mapped_column(Text)
    witness: Mapped[str | None] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    expense_id: Mapped[uuid.UUID | None]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    by_name: Mapped[str] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (CheckConstraint("kind IN ('CASH_IN','CASH_OUT','PAID_OUT','DROP')", name="kind"), CheckConstraint("amount > 0", name="amount_positive"))


class Sale(UUIDPk, Base):
    __tablename__ = "sales"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    terminal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pos_terminals.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cashier_sessions.id"), index=True)
    cashier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    payment_status: Mapped[str] = mapped_column(String(20), default="UNPAID")
    fulfilment_status: Mapped[str] = mapped_column(String(15), default="NOT_REQUIRED")
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="USD")
    tax_inclusive: Mapped[bool] = mapped_column(default=False)
    subtotal: Mapped[Money] = mapped_column(default=Decimal("0"))
    discount_total: Mapped[Money] = mapped_column(default=Decimal("0"))
    tax_total: Mapped[Money] = mapped_column(default=Decimal("0"))
    rounding: Mapped[Money] = mapped_column(default=Decimal("0"))
    grand_total: Mapped[Money] = mapped_column(default=Decimal("0"))
    paid_total: Mapped[Money] = mapped_column(default=Decimal("0"))
    refunded_total: Mapped[Money] = mapped_column(default=Decimal("0"))
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    order_discount: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    coupon_code: Mapped[str | None] = mapped_column(String(40))
    hold_label: Mapped[str | None] = mapped_column(String(100))
    business_date: Mapped[date | None] = mapped_column(Date, index=True)
    receipt_no: Mapped[str | None] = mapped_column(String(40))
    invoice_no: Mapped[str | None] = mapped_column(String(40))
    finalized_at: Mapped[datetime | None]
    reprint_count: Mapped[int] = mapped_column(default=0)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    void_reason: Mapped[str | None] = mapped_column(Text)
    voided_by: Mapped[str | None] = mapped_column(String(200))
    voided_at: Mapped[datetime | None]
    exchange_return_id: Mapped[uuid.UUID | None]
    loyalty_earned: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"))
    notices: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=text("now()"))
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        # Unique receipt numbers within the company (BR-SAL-001, BR-DOC-001).
        Index("uq_sales_receipt_no", "company_id", "receipt_no", unique=True, postgresql_where=text("receipt_no IS NOT NULL")),
        Index("uq_sales_invoice_no", "company_id", "invoice_no", unique=True, postgresql_where=text("invoice_no IS NOT NULL")),
        CheckConstraint(_in("status", SALE_STATUS), name="status"),
        CheckConstraint(_in("payment_status", SALE_PAYMENT_STATUS), name="payment_status"),
        CheckConstraint("fulfilment_status IN ('NOT_REQUIRED','PENDING','FULFILLED')", name="fulfilment_status"),
        CheckConstraint("status <> 'FINALIZED' OR receipt_no IS NOT NULL", name="finalized_has_receipt"),
        CheckConstraint("grand_total >= 0 AND paid_total >= 0 AND refunded_total >= 0", name="totals_non_negative"),
        Index("ix_sales_terminal_status", "terminal_id", "status"),
    )


class SaleLine(UUIDPk, Base):
    __tablename__ = "sale_lines"

    sale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int]
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    sku: Mapped[str] = mapped_column(String(60))
    name_en: Mapped[str] = mapped_column(String(200))
    name_km: Mapped[str] = mapped_column(String(200), default="")
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    unit_code: Mapped[str] = mapped_column(String(20))
    factor: Mapped[Quantity]
    quantity: Mapped[Quantity]
    quantity_base: Mapped[Quantity]
    allow_fraction: Mapped[bool] = mapped_column(default=False)
    precision: Mapped[int] = mapped_column(default=0)
    is_service: Mapped[bool] = mapped_column(default=False)
    list_price: Mapped[Money]
    unit_price: Mapped[Money]
    price_source: Mapped[str] = mapped_column(String(20))
    price_explanation: Mapped[str] = mapped_column(String(200), default="")
    override_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    override_reason: Mapped[str | None] = mapped_column(String(200))
    override_approved_by: Mapped[str | None] = mapped_column(String(200))
    line_discount: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    promotion_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("promotions.id"))
    promotion_name: Mapped[str | None] = mapped_column(String(200))
    gross_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    discount_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    order_discount_share: Mapped[Money] = mapped_column(default=Decimal("0"))
    tax_code_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_codes.id"))
    tax_code: Mapped[str] = mapped_column(String(30), default="")
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0"))
    tax_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    line_total: Mapped[Money] = mapped_column(default=Decimal("0"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouse_locations.id"))
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    cost_total: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    returned_quantity: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    price_changed: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        CheckConstraint("quantity > 0 AND quantity_base > 0 AND factor > 0", name="quantities_positive"),
        CheckConstraint("returned_quantity >= 0 AND returned_quantity <= quantity", name="returned_within_sold"),
        CheckConstraint("unit_price >= 0 AND list_price >= 0 AND discount_amount >= 0 AND order_discount_share >= 0", name="amounts_non_negative"),
    )


class SalePayment(UUIDPk, Base):
    __tablename__ = "sale_payments"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    sale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales.id"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cashier_sessions.id"), index=True)
    terminal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pos_terminals.id"))
    method: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    amount_tendered: Mapped[Money]
    exchange_rate: Mapped[Rate] = mapped_column(default=Decimal("1"))
    # Amount settled, in the sale currency.
    amount_applied: Mapped[Money]
    change_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    change_currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    # Cash rounding to the KHR increment, in the sale currency (positive: customer paid slightly more).
    rounding_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str | None] = mapped_column(String(100))
    reference: Mapped[str | None] = mapped_column(String(100))
    approval_code: Mapped[str | None] = mapped_column(String(40))
    card_last4: Mapped[str | None] = mapped_column(String(4))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    refunded_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    reconciled: Mapped[bool] = mapped_column(default=False)
    business_date: Mapped[date] = mapped_column(Date)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    completed_at: Mapped[datetime | None]

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint(_in("method", PAYMENT_METHODS), name="method"),
        CheckConstraint(_in("status", PAYMENT_STATUS), name="status"),
        CheckConstraint("amount_tendered > 0 AND amount_applied >= 0 AND change_amount >= 0 AND refunded_amount >= 0", name="amounts"),
        CheckConstraint("refunded_amount <= amount_applied", name="refund_within_payment"),
        CheckConstraint("card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'", name="card_last4"),
        # A provider or terminal reference identifies one payment (BR-PAY-002).
        Index("uq_sale_payments_reference", "company_id", "method", "reference", unique=True, postgresql_where=text("reference IS NOT NULL AND status NOT IN ('FAILED','CANCELLED')")),
    )


class StockReservation(UUIDPk, Base):
    """Short reservation while an electronic payment is pending (BR-INV-009, D-07)."""

    __tablename__ = "stock_reservations"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    sale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales.id"), index=True)
    sale_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sale_lines.id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse_locations.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    quantity_base: Mapped[Quantity]
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (CheckConstraint("status IN ('ACTIVE','CONSUMED','RELEASED')", name="status"), CheckConstraint("quantity_base > 0", name="quantity_positive"))


class SalesReturn(UUIDPk, Base):
    __tablename__ = "sales_returns"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    return_no: Mapped[str] = mapped_column(String(40))
    original_sale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales.id"), index=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"))
    terminal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pos_terminals.id"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cashier_sessions.id"))
    type: Mapped[str] = mapped_column(String(10), default="RETURN")
    refund_method: Mapped[str] = mapped_column(String(20))
    net_total: Mapped[Money]
    tax_total: Mapped[Money]
    refund_total: Mapped[Money]
    refund_status: Mapped[str] = mapped_column(String(10), default="PENDING")
    reference: Mapped[str | None] = mapped_column(String(100))
    exchange_sale_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales.id"))
    difference_paid: Mapped[Money] = mapped_column(default=Decimal("0"))
    override_window: Mapped[bool] = mapped_column(default=False)
    approved_by: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_by_name: Mapped[str] = mapped_column(String(200))
    business_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("company_id", "return_no"),
        CheckConstraint("type IN ('RETURN','EXCHANGE')", name="type"),
        CheckConstraint("refund_status IN ('PENDING','COMPLETED')", name="refund_status"),
        CheckConstraint("refund_total >= 0", name="refund_non_negative"),
    )


class SalesReturnLine(UUIDPk, Base):
    __tablename__ = "sales_return_lines"

    return_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales_returns.id", ondelete="CASCADE"), index=True)
    sale_line_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sale_lines.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    sku: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[Quantity]
    quantity_base: Mapped[Quantity]
    condition: Mapped[str] = mapped_column(String(15))
    reason: Mapped[str] = mapped_column(String(200))
    net_amount: Mapped[Money]
    tax_amount: Mapped[Money]
    refund_amount: Mapped[Money]
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(19, 6))
    destination_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouse_locations.id"))

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("condition IN ('RESALABLE','DAMAGED','EXPIRED','NON_RETURNABLE')", name="condition"),
    )


class Refund(UUIDPk, Base):
    __tablename__ = "refunds"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    sale_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sales.id"), index=True)
    return_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales_returns.id"), index=True)
    sale_payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sale_payments.id"))
    kind: Mapped[str] = mapped_column(String(10))
    method: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"))
    amount: Mapped[Money]
    # Amount in the sale currency, used for refunded totals.
    amount_applied: Mapped[Money]
    status: Mapped[str] = mapped_column(String(10))
    reference: Mapped[str | None] = mapped_column(String(100))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cashier_sessions.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    business_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    completed_at: Mapped[datetime | None]

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint("kind IN ('RETURN','VOID','CANCEL')", name="kind"),
        CheckConstraint("status IN ('PENDING','COMPLETED','FAILED')", name="status"),
        CheckConstraint("amount > 0 AND amount_applied > 0", name="amount_positive"),
        CheckConstraint(_in("method", PAYMENT_METHODS), name="method"),
    )
