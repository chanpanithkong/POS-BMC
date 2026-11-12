"""Sales, payments, cashier sessions and returns, shaped like the frontend `sales.ts` types.

Requests carry products, quantities, units and requested discounts only. Every amount
in a response is computed by the server; amounts sent by a client are never trusted (BR-POS-001).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas.common import Command, Out

Currency = Literal["USD", "KHR"]
PayMethod = Literal["CASH", "CARD", "QR", "BANK_TRANSFER", "STORE_CREDIT"]
Amount = Field(gt=0, max_digits=19, decimal_places=4)
NonNegative = Field(ge=0, max_digits=19, decimal_places=4)


# Cashier sessions

class CurrencyAmounts(Command):
    USD: Decimal = Field(default=Decimal("0"), ge=0, max_digits=19, decimal_places=2)
    KHR: Decimal = Field(default=Decimal("0"), ge=0, max_digits=19, decimal_places=0)


class SessionOpen(Command):
    opening: CurrencyAmounts
    witness: str | None = Field(default=None, max_length=200)


class SessionClose(Command):
    counted: CurrencyAmounts
    denominations: dict[str, int] | None = None
    variance_reason: str | None = Field(default=None, max_length=500)


class ReasonIn(Command):
    reason: str = Field(min_length=3, max_length=500)


class CashMovementIn(Command):
    kind: Literal["CASH_IN", "CASH_OUT", "PAID_OUT", "DROP"]
    currency: Currency
    amount: Decimal = Amount
    reason: str = Field(min_length=3, max_length=500)
    witness: str | None = Field(default=None, max_length=200)
    approval_token: str | None = None
    expense_category_id: str | None = None


class AmountsOut(Out):
    USD: Decimal
    KHR: Decimal


class CashSessionOut(Out):
    id: uuid.UUID
    session_no: str
    terminal_id: uuid.UUID
    terminal_name: str
    branch_id: uuid.UUID
    cashier_id: uuid.UUID
    cashier_name: str
    status: str
    opened_at: datetime
    closed_at: datetime | None
    opening: AmountsOut
    witness: str | None
    counted: AmountsOut | None
    denominations: dict[str, Any] | None
    expected: AmountsOut | None = Field(description="Hidden from the cashier until the blind count is submitted")
    variance: AmountsOut | None
    variance_reason: str | None
    reviewed_by: str | None
    needs_approval: bool
    business_date: date
    version: int


class CashMovementOut(Out):
    id: uuid.UUID
    session_id: uuid.UUID
    kind: str
    currency: str
    amount: Decimal
    reason: str
    witness: str | None
    approved_by: str | None
    expense_id: uuid.UUID | None
    at: datetime
    by: str


class SessionSummary(Out):
    session: CashSessionOut
    movements: list[CashMovementOut]
    cash_sales: AmountsOut | None
    cash_refunds: AmountsOut | None
    movement_totals: dict[str, AmountsOut] | None
    non_cash_totals: dict[str, Decimal]
    sales_count: int
    sales_total: Decimal
    pending_payments: int


# Sales

class AppliedDiscount(Out):
    type: Literal["PERCENT", "AMOUNT"]
    value: Decimal
    reason: str
    source: Literal["MANUAL", "PROMOTION", "COUPON", "CUSTOMER"]
    approved_by: str | None


class SaleLineOut(Out):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name_en: str
    name_km: str
    unit_id: uuid.UUID
    unit_code: str
    factor: Decimal
    quantity: Decimal
    quantity_base: Decimal
    allow_fraction: bool
    precision: int
    unit_price: Decimal
    price_source: str
    price_explanation: str
    list_price: Decimal
    override_approved_by: str | None
    override_reason: str | None
    line_discount: AppliedDiscount | None
    promotion_name: str | None
    gross_amount: Decimal
    discount_amount: Decimal
    order_discount_share: Decimal
    tax_code_id: uuid.UUID | None
    tax_code: str
    tax_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal
    unit_cost: Decimal | None = Field(default=None, description="Only with inventory.cost.view")
    cost_total: Decimal | None = Field(default=None, description="Only with inventory.cost.view")
    returned_quantity: Decimal
    available: Decimal
    is_service: bool
    price_changed: bool


class SalePaymentOut(Out):
    id: uuid.UUID
    sale_id: uuid.UUID
    session_id: uuid.UUID | None
    terminal_id: uuid.UUID
    method: str
    currency: str
    amount_tendered: Decimal
    exchange_rate: Decimal
    amount_applied: Decimal
    change_amount: Decimal
    change_currency: str
    rounding_amount: Decimal
    status: str
    provider: str | None
    reference: str | None
    approval_code: str | None
    card_last4: str | None
    failure_reason: str | None
    refunded_amount: Decimal
    created_at: datetime
    completed_at: datetime | None
    reconciled: bool


class SaleOut(Out):
    id: uuid.UUID
    receipt_no: str | None
    branch_id: uuid.UUID
    branch_name: str
    terminal_id: uuid.UUID
    terminal_name: str
    session_id: uuid.UUID | None
    cashier_id: uuid.UUID
    cashier_name: str
    salesperson_id: uuid.UUID | None
    customer_id: uuid.UUID | None
    customer_name: str | None
    status: str
    payment_status: str
    fulfilment_status: str
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    rounding: Decimal
    grand_total: Decimal
    paid_total: Decimal
    refunded_total: Decimal
    balance: Decimal
    exchange_rate: Decimal | None
    grand_total_khr: Decimal | None
    order_discount: AppliedDiscount | None
    coupon_code: str | None
    lines: list[SaleLineOut]
    payments: list[SalePaymentOut]
    return_ids: list[uuid.UUID]
    hold_label: str | None
    business_date: date | None
    created_at: datetime
    finalized_at: datetime | None
    reprint_count: int
    cancel_reason: str | None
    void_reason: str | None
    voided_by: str | None
    invoice_no: str | None
    loyalty_earned: Decimal
    version: int
    notices: list[str]


class _Op(Command):
    approval_token: str | None = None


class AddBarcode(_Op):
    type: Literal["add_barcode"]
    barcode: str = Field(min_length=1, max_length=64)


class AddProduct(_Op):
    type: Literal["add_product"]
    product_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    quantity: Decimal = Field(default=Decimal("1"), gt=0, max_digits=19, decimal_places=4)


class SetQuantity(_Op):
    type: Literal["set_quantity"]
    line_id: uuid.UUID
    quantity: Decimal = Field(gt=0, max_digits=19, decimal_places=4)


class SetUnit(_Op):
    type: Literal["set_unit"]
    line_id: uuid.UUID
    unit_id: uuid.UUID


class RemoveLine(_Op):
    type: Literal["remove_line"]
    line_id: uuid.UUID


class LineDiscount(_Op):
    type: Literal["line_discount"]
    line_id: uuid.UUID
    discount_type: Literal["PERCENT", "AMOUNT"]
    value: Decimal = Field(ge=0, max_digits=19, decimal_places=4)
    reason: str = Field(default="", max_length=200)


class OrderDiscount(_Op):
    type: Literal["order_discount"]
    discount_type: Literal["PERCENT", "AMOUNT"]
    value: Decimal = Field(ge=0, max_digits=19, decimal_places=4)
    reason: str = Field(default="", max_length=200)


class OverridePrice(_Op):
    type: Literal["override_price"]
    line_id: uuid.UUID
    price: Decimal = Field(ge=0, max_digits=19, decimal_places=4)
    reason: str = Field(min_length=3, max_length=200)


class SetCustomer(_Op):
    type: Literal["set_customer"]
    customer_id: uuid.UUID | None


class ApplyCoupon(_Op):
    type: Literal["apply_coupon"]
    code: str | None


class Hold(_Op):
    type: Literal["hold"]
    label: str = Field(default="", max_length=100)


class Resume(_Op):
    type: Literal["resume"]


SaleOp = Annotated[AddBarcode | AddProduct | SetQuantity | SetUnit | RemoveLine | LineDiscount | OrderDiscount | OverridePrice | SetCustomer | ApplyCoupon | Hold | Resume, Field(discriminator="type")]


class SaleOps(Command):
    ops: list[SaleOp] = Field(min_length=1, max_length=50)


class SaleCreate(Command):
    pass


class PaymentIn(Command):
    method: PayMethod
    currency: Currency = "USD"
    amount_tendered: Decimal = Amount
    change_currency: Currency | None = None
    reference: str | None = Field(default=None, max_length=100)
    approval_code: str | None = Field(default=None, max_length=40)
    card_last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    provider: str | None = Field(default=None, max_length=100)


class PaymentResolve(Command):
    outcome: Literal["COMPLETED", "FAILED", "CANCELLED"]
    reference: str | None = Field(default=None, max_length=100)
    reason: str | None = Field(default=None, max_length=500)


class SaleCancel(Command):
    reason: str = Field(min_length=1, max_length=500)
    approval_token: str | None = None


class PaymentRow(SalePaymentOut):
    receipt_no: str | None
    branch_name: str
    business_date: date


class ReconcileIn(Command):
    reconciled: bool


# Receipts

class ReceiptLine(Out):
    name_en: str
    name_km: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal
    discount: Decimal
    tax_code: str
    amount: Decimal


class ReceiptPayment(Out):
    method: str
    currency: str
    tendered: Decimal
    applied: Decimal
    change: Decimal
    change_currency: str
    reference: str | None


class Receipt(Out):
    copy_label: str | None = Field(description="'COPY / ច្បាប់ចម្លង' on reprints")
    reprint_count: int
    company_name_en: str
    company_name_km: str
    tax_id: str
    branch_name: str
    branch_address: str
    branch_phone: str
    header: str
    footer: str
    receipt_no: str
    invoice_no: str | None
    business_date: date
    finalized_at: datetime
    cashier_name: str
    terminal_name: str
    customer_name: str | None
    lines: list[ReceiptLine]
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    tax_inclusive: bool
    rounding: Decimal
    grand_total: Decimal
    exchange_rate: Decimal | None
    grand_total_khr: Decimal | None
    payments: list[ReceiptPayment]
    status: str


# Returns

class ReturnLineIn(Command):
    sale_line_id: uuid.UUID
    quantity: Decimal = Amount
    condition: Literal["RESALABLE", "DAMAGED", "EXPIRED", "NON_RETURNABLE"]
    reason: str = Field(min_length=1, max_length=200)


class ReplacementLineIn(Command):
    product_id: uuid.UUID
    unit_id: uuid.UUID | None = None
    quantity: Decimal = Amount


class ReturnIn(Command):
    lines: list[ReturnLineIn] = Field(min_length=1)
    refund_method: PayMethod
    reference: str | None = Field(default=None, max_length=100)
    approval_token: str | None = None
    replacement_lines: list[ReplacementLineIn] | None = None
    settlement_method: PayMethod | None = None
    settlement_reference: str | None = Field(default=None, max_length=100)


class QuoteLine(Out):
    sale_line_id: uuid.UUID
    quantity: Decimal
    net_amount: Decimal
    tax_amount: Decimal
    refund_amount: Decimal


class ReturnQuote(Out):
    refund_total: Decimal
    net_total: Decimal
    tax_total: Decimal
    lines: list[QuoteLine]
    window_expired: bool
    approval_reasons: list[str]
    replacement_total: Decimal
    difference: Decimal = Field(description="Replacement total minus refund: positive means the customer pays")


class ReturnLineOut(Out):
    sale_line_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    quantity: Decimal
    condition: str
    reason: str
    net_amount: Decimal
    tax_amount: Decimal
    refund_amount: Decimal
    unit_cost: Decimal | None
    destination_location_id: uuid.UUID | None


class ReturnOut(Out):
    id: uuid.UUID
    return_no: str
    original_sale_id: uuid.UUID
    original_receipt_no: str
    branch_id: uuid.UUID
    branch_name: str
    terminal_id: uuid.UUID
    session_id: uuid.UUID | None
    customer_name: str | None
    type: str
    lines: list[ReturnLineOut]
    refund_method: str
    refund_total: Decimal
    net_total: Decimal
    tax_total: Decimal
    refund_status: str
    reference: str | None
    exchange_sale_id: uuid.UUID | None
    difference_paid: Decimal
    created_by: str
    approved_by: str | None
    override_window: bool
    created_at: datetime
    business_date: date


class RefundOut(Out):
    id: uuid.UUID
    return_id: uuid.UUID | None
    sale_id: uuid.UUID
    sale_payment_id: uuid.UUID | None
    kind: str
    method: str
    amount: Decimal
    currency: str
    status: str
    reference: str | None
    session_id: uuid.UUID | None
    created_at: datetime
    business_date: date


class ConfirmRefund(Command):
    reference: str = Field(min_length=1, max_length=100)
