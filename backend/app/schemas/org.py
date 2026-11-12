"""Organisation and settings schemas. Field names match the frontend types (snake_case on the wire)."""

import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.common import Command, Out

Status = Literal["ACTIVE", "INACTIVE"]
CODE_PATTERN = r"^[A-Za-z0-9._-]+$"
Code = Field(min_length=1, max_length=20, pattern=CODE_PATTERN)
OptCode = Field(default=None, min_length=1, max_length=20, pattern=CODE_PATTERN)


class CompanyOut(Out):
    id: uuid.UUID
    legal_name_en: str
    legal_name_km: str
    trading_name_en: str
    trading_name_km: str
    address: str
    phone: str
    tax_id: str
    logo: str | None
    base_currency: str
    fiscal_year_start_month: int


class CompanyUpdate(Command):
    legal_name_en: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name_km: str | None = Field(default=None, max_length=200)
    trading_name_en: str | None = Field(default=None, min_length=1, max_length=200)
    trading_name_km: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=50)
    tax_id: str | None = Field(default=None, max_length=50)
    logo: str | None = Field(default=None, max_length=500)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)


class SystemSettings(Command):
    """Company settings. Defaults are the SRS's proposed values; every value is changeable."""

    tax_inclusive: bool = False
    khr_cash_increment: Decimal = Field(default=Decimal("100"), gt=0)
    sku_mode: Literal["AUTO", "MANUAL"] = "AUTO"
    sku_prefix: str = Field(default="SKU", max_length=20)
    branch_pricing_enabled: bool = True
    # D-05: weighted average cost, company scope. Other methods are out of scope for v1.
    costing_method: Literal["WAC"] = "WAC"
    costing_scope: Literal["COMPANY"] = "COMPANY"
    negative_stock_allowed: bool = False
    reduced_sod_mode: bool = False
    pos_idle_lock_minutes: int = Field(default=2, ge=1, le=60)
    return_window_days: int = Field(default=7, ge=0, le=365)
    no_receipt_returns_enabled: bool = False
    store_credit_enabled: bool = False
    loyalty_enabled: bool = False
    loyalty_points_per_usd: Decimal = Field(default=Decimal("1"), ge=0)
    loyalty_redeem_usd_per_point: Decimal = Field(default=Decimal("0.01"), ge=0)
    expense_approval_threshold: Decimal = Field(default=Decimal("100"), ge=0)
    expense_attachment_threshold: Decimal = Field(default=Decimal("50"), ge=0)
    over_delivery_tolerance_pct: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    session_variance_tolerance_usd: Decimal = Field(default=Decimal("1.00"), ge=0)
    session_variance_tolerance_khr: Decimal = Field(default=Decimal("4000"), ge=0)
    cash_movement_approval_threshold: Decimal = Field(default=Decimal("50"), ge=0)
    refund_cash_approval_threshold: Decimal = Field(default=Decimal("20"), ge=0)
    adjustment_alert_value: Decimal = Field(default=Decimal("100"), ge=0)
    count_variance_recount_qty: Decimal = Field(default=Decimal("5"), ge=0)
    transfer_approval_value: Decimal = Field(default=Decimal("500"), ge=0)
    slow_moving_days: int = Field(default=60, ge=1)
    expiry_warning_days: int = Field(default=30, ge=0)
    date_format: Literal["DD/MM/YYYY"] = "DD/MM/YYYY"
    time_zone: str = Field(default="Asia/Phnom_Penh", max_length=50)


class SettingsUpdate(Command):
    """Partial update; any SystemSettings field may be sent."""

    model_config = {**Command.model_config, "extra": "allow"}


class BranchOut(Out):
    id: uuid.UUID
    code: str
    name_en: str
    name_km: str
    address: str
    phone: str
    receipt_header: str
    open_time: time | None
    close_time: time | None
    day_cutoff: time
    timezone: str
    status: str


class BranchCreate(Command):
    code: str = Code
    name_en: str = Field(min_length=1, max_length=200)
    name_km: str = Field(default="", max_length=200)
    address: str = Field(default="", max_length=1000)
    phone: str = Field(default="", max_length=50)
    receipt_header: str = Field(default="", max_length=200)
    open_time: time | None = None
    close_time: time | None = None
    day_cutoff: time = time(0, 0)
    status: Status = "ACTIVE"
    create_store_warehouse: bool = Field(default=True, description="Also create the branch store warehouse with standard locations")


class BranchUpdate(Command):
    code: str | None = OptCode
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_km: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=50)
    receipt_header: str | None = Field(default=None, max_length=200)
    open_time: time | None = None
    close_time: time | None = None
    day_cutoff: time | None = None
    status: Status | None = None


class WarehouseOut(Out):
    id: uuid.UUID
    code: str
    name: str
    branch_id: uuid.UUID | None
    is_central: bool
    status: str


class WarehouseCreate(Command):
    code: str = Code
    name: str = Field(min_length=1, max_length=100)
    branch_id: uuid.UUID | None = None
    status: Status = "ACTIVE"


class WarehouseUpdate(Command):
    code: str | None = OptCode
    name: str | None = Field(default=None, min_length=1, max_length=100)
    branch_id: uuid.UUID | None = None
    status: Status | None = None


LocationType = Literal["SELLABLE", "STORAGE", "RECEIVING", "DAMAGED", "EXPIRED", "QUARANTINE", "RETURNS"]


class LocationOut(Out):
    id: uuid.UUID
    code: str
    name: str
    warehouse_id: uuid.UUID
    type: str
    available_to_sell: bool
    status: str


class LocationCreate(Command):
    code: str = Code
    name: str = Field(min_length=1, max_length=100)
    warehouse_id: uuid.UUID
    type: LocationType
    available_to_sell: bool | None = Field(default=None, description="Defaults from the location type")
    status: Status = "ACTIVE"


class LocationUpdate(Command):
    code: str | None = OptCode
    name: str | None = Field(default=None, min_length=1, max_length=100)
    type: LocationType | None = None
    available_to_sell: bool | None = None
    status: Status | None = None


class TerminalOut(Out):
    id: uuid.UUID
    code: str
    name: str
    branch_id: uuid.UUID
    default_location_id: uuid.UUID
    printer_profile: str
    cash_drawer: bool
    status: str
    assigned_cashier_ids: list[uuid.UUID]


class TerminalCreate(Command):
    code: str = Code
    name: str = Field(min_length=1, max_length=100)
    branch_id: uuid.UUID
    default_location_id: uuid.UUID
    printer_profile: Literal["58mm", "80mm"] = "80mm"
    cash_drawer: bool = True
    status: Status = "ACTIVE"
    assigned_cashier_ids: list[uuid.UUID] = []


class TerminalUpdate(Command):
    code: str | None = OptCode
    name: str | None = Field(default=None, min_length=1, max_length=100)
    default_location_id: uuid.UUID | None = None
    printer_profile: Literal["58mm", "80mm"] | None = None
    cash_drawer: bool | None = None
    status: Status | None = None
    assigned_cashier_ids: list[uuid.UUID] | None = None


class TaxCodeOut(Out):
    id: uuid.UUID
    code: str
    name: str
    rate: Decimal
    status: str


class TaxCodeCreate(Command):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=100)
    rate: Decimal = Field(ge=0, le=100, decimal_places=4)
    status: Status = "ACTIVE"


class TaxCodeUpdate(Command):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    rate: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=4)
    status: Status | None = None


PaymentCode = Literal["CASH", "CARD", "QR", "BANK_TRANSFER", "STORE_CREDIT"]


class PaymentMethodOut(Out):
    id: uuid.UUID
    code: str
    name: str
    requires_reference: bool
    provider: str
    status: str


class PaymentMethodCreate(Command):
    code: PaymentCode
    name: str = Field(min_length=1, max_length=100)
    requires_reference: bool = False
    provider: str = Field(default="", max_length=100)
    status: Status = "ACTIVE"


class PaymentMethodUpdate(Command):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    requires_reference: bool | None = None
    provider: str | None = Field(default=None, max_length=100)
    status: Status | None = None


class ExchangeRateOut(Out):
    id: uuid.UUID
    from_: str = Field(serialization_alias="from")
    to: str
    rate: Decimal
    effective_at: datetime
    created_by: str


class ExchangeRateCreate(Command):
    rate: Decimal = Field(gt=0, decimal_places=8, description="KHR per 1 USD")
    from_: Literal["USD"] = Field(default="USD", alias="from")
    to: Literal["KHR"] = "KHR"


class SequenceOut(Out):
    id: str
    doc_type: str
    prefix: str
    next_value: int
    padding: int
    include_branch: bool
    include_year: bool
    preview: str


class SequenceUpdate(Command):
    prefix: str | None = Field(default=None, max_length=20, pattern=r"^[A-Za-z0-9-]*$")
    next_value: int | None = Field(default=None, ge=1)
    padding: int | None = Field(default=None, ge=1, le=12)
    include_branch: bool | None = None
    include_year: bool | None = None


class ReceiptTemplateOut(Out):
    id: uuid.UUID
    branch_id: uuid.UUID | None
    name: str
    language: str
    paper_width: str
    header: str
    footer: str
    show_logo: bool
    show_tax_id: bool
    show_qr: bool


class ReceiptTemplateCreate(Command):
    branch_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=100)
    language: Literal["EN", "KM", "BILINGUAL"] = "BILINGUAL"
    paper_width: Literal["58mm", "80mm"] = "80mm"
    header: str = Field(default="", max_length=2000)
    footer: str = Field(default="", max_length=2000)
    show_logo: bool = True
    show_tax_id: bool = True
    show_qr: bool = False


class ReceiptTemplateUpdate(Command):
    branch_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=100)
    language: Literal["EN", "KM", "BILINGUAL"] | None = None
    paper_width: Literal["58mm", "80mm"] | None = None
    header: str | None = Field(default=None, max_length=2000)
    footer: str | None = Field(default=None, max_length=2000)
    show_logo: bool | None = None
    show_tax_id: bool | None = None
    show_qr: bool | None = None
