"""Purchasing and customer schemas, shaped like the frontend `purchasing.ts` and `sales.ts` types."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import Command, Out
from app.schemas.inventory import TimelineEvent

Status = Literal["ACTIVE", "INACTIVE"]
Qty = Field(ge=0, max_digits=19, decimal_places=4)
Cost = Field(ge=0, max_digits=19, decimal_places=4)


def _blank(value: Any) -> Any:
    return None if value == "" else value


# Suppliers

class ContactIn(Command):
    id: str | None = None
    name: str = Field(min_length=1, max_length=200)
    position: str = Field(default="", max_length=100)
    phone: str = Field(default="", max_length=50)
    email: EmailStr | Literal[""] = ""


class SupplierFields(Command):
    code: str | None = Field(default=None, max_length=30)
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_km: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | Literal[""] | None = None
    address: str | None = Field(default=None, max_length=1000)
    payment_terms: str | None = Field(default=None, max_length=100)
    currency: Literal["USD", "KHR"] | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    status: Status | None = None
    contacts: list[ContactIn] | None = None


class SupplierCreate(SupplierFields):
    code: str = Field(min_length=1, max_length=30)
    name_en: str = Field(min_length=1, max_length=200)


class SupplierUpdate(SupplierFields):
    pass


class ContactOut(Out):
    id: str
    name: str
    position: str
    phone: str
    email: str


class SupplierOut(Out):
    id: uuid.UUID
    code: str
    name_en: str
    name_km: str
    tax_id: str
    phone: str
    email: str
    address: str
    payment_terms: str
    currency: str
    lead_time_days: int
    status: str
    contacts: list[ContactOut]
    open_po_count: int
    on_time_rate: Decimal | None
    fill_rate: Decimal | None
    outstanding_balance: Decimal


# Purchase orders

class PoLineIn(Command):
    product_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    quantity: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    unit_cost: Decimal = Cost


class PoCreate(Command):
    supplier_id: uuid.UUID
    warehouse_id: uuid.UUID
    expected_date: date
    notes: str = Field(default="", max_length=2000)
    lines: list[PoLineIn] = Field(min_length=1)


class PoUpdate(Command):
    supplier_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    expected_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[PoLineIn] | None = None


class PoLineOut(Out):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    supplier_sku: str
    unit_id: uuid.UUID
    unit_code: str
    factor: Decimal
    quantity: Decimal
    quantity_base: Decimal
    unit_cost: Decimal | None
    tax_rate: Decimal
    line_total: Decimal | None
    received_base: Decimal
    cancelled_base: Decimal


class PoOut(Out):
    id: uuid.UUID
    po_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    branch_id: uuid.UUID | None
    expected_date: date
    status: str
    notes: str
    lines: list[PoLineOut]
    subtotal: Decimal | None
    tax_total: Decimal | None
    total: Decimal | None
    created_by: str
    created_by_id: uuid.UUID | None
    approved_by: str | None
    created_at: datetime
    sent_at: datetime | None
    first_received_at: datetime | None
    timeline: list[TimelineEvent]
    version: int


class DocAction(Command):
    reason: str | None = Field(default=None, max_length=500)
    credit_note_ref: str | None = Field(default=None, max_length=100)


# Goods receipts

class GrnLineIn(Command):
    po_line_id: uuid.UUID | None = None
    product_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    quantity_received: Decimal = Qty
    quantity_damaged: Decimal = Field(default=Decimal("0"), ge=0, max_digits=19, decimal_places=4)
    quantity_rejected: Decimal = Field(default=Decimal("0"), ge=0, max_digits=19, decimal_places=4)
    unit_cost: Decimal = Cost
    batch_no: str = Field(default="", max_length=60)
    expiry_date: date | None = None
    # Display fields the form sends back; ignored.
    name: str | None = None
    unit_code: str | None = None
    factor: Decimal | None = None
    open: Decimal | None = None
    track_expiry: bool | None = None

    _blank = field_validator("po_line_id", "expiry_date", mode="before")(_blank)


class GrnCreate(Command):
    po_id: uuid.UUID | None = None
    supplier_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    delivery_note: str = Field(default="", max_length=100)
    invoice_ref: str = Field(default="", max_length=100)
    exception_reason: str = Field(default="", max_length=500)
    blind: bool = False
    lines: list[GrnLineIn] = Field(min_length=1)

    _blank = field_validator("po_id", "supplier_id", "warehouse_id", mode="before")(_blank)


class GrnUpdate(Command):
    delivery_note: str | None = Field(default=None, max_length=100)
    invoice_ref: str | None = Field(default=None, max_length=100)
    exception_reason: str | None = Field(default=None, max_length=500)
    lines: list[GrnLineIn] | None = None


class GrnLineOut(Out):
    id: uuid.UUID
    po_line_id: uuid.UUID | None
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_id: uuid.UUID
    unit_code: str
    factor: Decimal
    ordered_open: Decimal
    quantity_received: Decimal
    quantity_damaged: Decimal
    quantity_rejected: Decimal
    unit_cost: Decimal | None
    batch_no: str
    expiry_date: date | None
    track_expiry: bool


class GrnOut(Out):
    id: uuid.UUID
    receipt_no: str
    po_id: uuid.UUID | None
    po_no: str | None
    supplier_id: uuid.UUID
    supplier_name: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    branch_id: uuid.UUID | None
    status: str
    blind: bool
    exception_reason: str | None
    delivery_note: str
    invoice_ref: str
    lines: list[GrnLineOut]
    discrepancies: list[str]
    total_cost: Decimal | None
    created_by: str
    created_by_id: uuid.UUID | None
    approved_by: str | None
    posted_by: str | None
    posted_at: datetime | None
    created_at: datetime
    flagged_for_review: bool
    version: int


# Supplier invoices

class InvoiceCreate(Command):
    invoice_no: str = Field(min_length=1, max_length=60)
    supplier_id: uuid.UUID
    po_id: uuid.UUID | None = None
    invoice_date: date
    due_date: date
    amount: Decimal = Field(gt=0, max_digits=19, decimal_places=4)

    _blank = field_validator("po_id", mode="before")(_blank)


class InvoicePaymentIn(Command):
    amount: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    reference: str = Field(min_length=1, max_length=100)


class SupplierPaymentOut(Out):
    id: uuid.UUID
    amount: Decimal
    reference: str
    paid_at: datetime
    by: str


class InvoiceOut(Out):
    id: uuid.UUID
    invoice_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    po_id: uuid.UUID | None
    po_no: str | None
    invoice_date: date
    due_date: date
    amount: Decimal
    paid_amount: Decimal
    status: str
    match_notes: str
    payments: list[SupplierPaymentOut]
    created_by: str
    created_at: datetime


# Purchase returns

class PrLineIn(Command):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity_base: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    name: str | None = None


class PrCreate(Command):
    goods_receipt_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)
    lines: list[PrLineIn] = Field(min_length=1)


class PrLineOut(Out):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    location_id: uuid.UUID
    location_name: str
    quantity_base: Decimal
    unit_cost: Decimal | None
    total: Decimal | None


class PrOut(Out):
    id: uuid.UUID
    return_no: str
    supplier_id: uuid.UUID
    supplier_name: str
    goods_receipt_id: uuid.UUID
    goods_receipt_no: str
    warehouse_id: uuid.UUID
    status: str
    reason: str
    lines: list[PrLineOut]
    total: Decimal | None
    credit_note_ref: str | None
    created_by: str
    created_by_id: uuid.UUID | None
    approved_by: str | None
    created_at: datetime
    version: int


# Customers

class GroupFields(Command):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    price_list_id: uuid.UUID | None = None
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100, max_digits=9, decimal_places=4)
    status: Status | None = None

    _blank = field_validator("price_list_id", mode="before")(_blank)


class GroupCreate(GroupFields):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)


class GroupOut(Out):
    id: uuid.UUID
    code: str
    name: str
    price_list_id: uuid.UUID | None
    discount_pct: Decimal
    status: str


class CustomerFields(Command):
    code: str | None = Field(default=None, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | Literal[""] | None = None
    address: str | None = Field(default=None, max_length=1000)
    group_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)
    consent_marketing: bool | None = None
    credit_limit: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    status: Status | None = None

    _blank = field_validator("group_id", "code", mode="before")(_blank)


class CustomerCreate(CustomerFields):
    name: str = Field(min_length=1, max_length=200)


class CustomerOut(Out):
    id: uuid.UUID
    code: str
    name: str
    phone: str
    email: str
    address: str
    group_id: uuid.UUID | None
    group_name: str | None
    notes: str
    consent_marketing: bool
    loyalty_points: Decimal
    tier: str
    store_credit: Decimal
    credit_limit: Decimal
    last_purchase_at: datetime | None
    total_spent: Decimal
    status: str
    anonymized: bool
    created_at: datetime
