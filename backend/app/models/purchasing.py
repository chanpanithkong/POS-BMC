"""Suppliers, purchase orders, goods receipts, supplier invoices and purchase returns (PUR, GRN; Phase 6).

Ordering never changes stock; only posted goods receipts do (BR-PUR-002). Open purchase
order quantity is reported as "on order".
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, Money, Quantity, SoftDelete, UUIDPk


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({','.join(repr(v) for v in values)})"


class Supplier(UUIDPk, Authored, SoftDelete, Base):
    __tablename__ = "suppliers"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name_en: Mapped[str] = mapped_column(String(200))
    name_km: Mapped[str] = mapped_column(String(200), default="")
    tax_id: Mapped[str] = mapped_column(String(50), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    payment_terms: Mapped[str] = mapped_column(String(100), default="")
    currency: Mapped[str] = mapped_column(ForeignKey("currencies.code"), default="USD")
    lead_time_days: Mapped[int] = mapped_column(default=7)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    __table_args__ = (
        Index("uq_suppliers_company_code", "company_id", text("lower(code)"), unique=True, postgresql_where=text("deleted_at IS NULL")),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
        CheckConstraint("lead_time_days >= 0", name="lead_time"),
    )


class ProductSupplier(Base):
    __tablename__ = "product_suppliers"

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), primary_key=True, index=True)
    supplier_sku: Mapped[str] = mapped_column(String(60), default="")
    purchase_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    cost: Mapped[Money] = mapped_column(default=Decimal("0"))
    lead_time_days: Mapped[int] = mapped_column(default=7)
    preferred: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        CheckConstraint("cost >= 0 AND lead_time_days >= 0", name="values"),
        Index("uq_product_suppliers_preferred", "product_id", unique=True, postgresql_where=text("preferred")),
    )


PO_STATUS = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "SENT", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED", "SHORT_CLOSED")


class PurchaseOrder(UUIDPk, Authored, Base):
    __tablename__ = "purchase_orders"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    po_no: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    expected_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    notes: Mapped[str] = mapped_column(Text, default="")
    subtotal: Mapped[Money] = mapped_column(default=Decimal("0"))
    tax_total: Mapped[Money] = mapped_column(default=Decimal("0"))
    total: Mapped[Money] = mapped_column(default=Decimal("0"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by_name: Mapped[str | None] = mapped_column(String(200))
    sent_at: Mapped[datetime | None]
    first_received_at: Mapped[datetime | None]
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (UniqueConstraint("company_id", "po_no"), CheckConstraint(_in("status", PO_STATUS), name="status"))


class PurchaseOrderLine(UUIDPk, Base):
    __tablename__ = "purchase_order_lines"

    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int]
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    supplier_sku: Mapped[str] = mapped_column(String(60), default="")
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    factor: Mapped[Quantity]
    quantity: Mapped[Quantity]
    quantity_base: Mapped[Quantity]
    # Cost per purchase unit, before tax.
    unit_cost: Mapped[Money]
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0"))
    line_total: Mapped[Money] = mapped_column(default=Decimal("0"))
    received_base: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    cancelled_base: Mapped[Quantity] = mapped_column(default=Decimal("0"))

    __table_args__ = (
        CheckConstraint("quantity > 0 AND factor > 0 AND unit_cost >= 0", name="values"),
        CheckConstraint("received_base >= 0 AND cancelled_base >= 0", name="progress"),
    )


class GoodsReceipt(UUIDPk, Authored, Base):
    __tablename__ = "goods_receipts"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    receipt_no: Mapped[str] = mapped_column(String(40))
    po_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    blind: Mapped[bool] = mapped_column(default=False)
    exception_reason: Mapped[str | None] = mapped_column(Text)
    delivery_note: Mapped[str] = mapped_column(String(100), default="")
    invoice_ref: Mapped[str] = mapped_column(String(100), default="")
    discrepancies: Mapped[list[str]] = mapped_column(JSONB, default=list)
    flagged_for_review: Mapped[bool] = mapped_column(default=False)
    total_cost: Mapped[Money] = mapped_column(default=Decimal("0"))
    approved_by_name: Mapped[str | None] = mapped_column(String(200))
    posted_by_name: Mapped[str | None] = mapped_column(String(200))
    posted_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("company_id", "receipt_no"),
        CheckConstraint("status IN ('DRAFT','PENDING_APPROVAL','POSTED')", name="status"),
        # A receipt without a purchase order must say why (BR-GRN-003).
        CheckConstraint("po_id IS NOT NULL OR exception_reason IS NOT NULL", name="po_or_exception"),
    )


class GoodsReceiptLine(UUIDPk, Base):
    __tablename__ = "goods_receipt_lines"

    receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int]
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_order_lines.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    factor: Mapped[Quantity]
    quantity_received: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    quantity_damaged: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    quantity_rejected: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    # Cost per purchase unit; the ledger stores cost per base unit.
    unit_cost: Mapped[Money]
    batch_no: Mapped[str] = mapped_column(String(60), default="")
    expiry_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (CheckConstraint("quantity_received >= 0 AND quantity_damaged >= 0 AND quantity_rejected >= 0 AND unit_cost >= 0 AND factor > 0", name="values"),)


INVOICE_STATUS = ("RECORDED", "MATCHED", "MISMATCH", "PAID", "PARTIALLY_PAID")


class SupplierInvoice(UUIDPk, Authored, Base):
    __tablename__ = "supplier_invoices"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    invoice_no: Mapped[str] = mapped_column(String(60))
    # Upper-case letters and digits only, so "inv-001" and "INV 001" are the same invoice (BR-PUR-003).
    invoice_no_normalised: Mapped[str] = mapped_column(String(60))
    po_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("purchase_orders.id"))
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Money]
    paid_amount: Mapped[Money] = mapped_column(default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(20), default="RECORDED")
    match_notes: Mapped[str] = mapped_column(Text, default="")

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("supplier_id", "invoice_no_normalised"),
        CheckConstraint(_in("status", INVOICE_STATUS), name="status"),
        CheckConstraint("amount > 0 AND paid_amount >= 0 AND paid_amount <= amount", name="amounts"),
        CheckConstraint("due_date >= invoice_date", name="dates"),
    )


class SupplierPayment(UUIDPk, Base):
    __tablename__ = "supplier_payments"

    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("supplier_invoices.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Money]
    reference: Mapped[str] = mapped_column(String(100))
    paid_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    by_name: Mapped[str] = mapped_column(String(200))

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)


class PurchaseReturn(UUIDPk, Authored, Base):
    __tablename__ = "purchase_returns"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    return_no: Mapped[str] = mapped_column(String(40))
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), index=True)
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(15), default="DRAFT")
    reason: Mapped[str] = mapped_column(Text)
    total: Mapped[Money] = mapped_column(default=Decimal("0"))
    credit_note_ref: Mapped[str | None] = mapped_column(String(100))
    approved_by_name: Mapped[str | None] = mapped_column(String(200))
    dispatched_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (UniqueConstraint("company_id", "return_no"), CheckConstraint("status IN ('DRAFT','APPROVED','DISPATCHED','CREDITED','CANCELLED')", name="status"))


class PurchaseReturnLine(UUIDPk, Base):
    __tablename__ = "purchase_return_lines"

    return_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_returns.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse_locations.id"))
    batch_no: Mapped[str] = mapped_column(String(60), default="")
    quantity_base: Mapped[Quantity]
    # Cost per base unit from the goods receipt.
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 6))
    total: Mapped[Money]

    __table_args__ = (CheckConstraint("quantity_base > 0", name="quantity_positive"),)
