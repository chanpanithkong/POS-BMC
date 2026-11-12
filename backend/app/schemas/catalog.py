"""Catalogue and pricing schemas, shaped like the frontend `catalog.ts` types."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import Command, Out

Status = Literal["ACTIVE", "INACTIVE"]
ProductType = Literal["STANDARD", "WEIGHED", "VARIANT_PARENT", "SERVICE"]
ProductStatus = Literal["DRAFT", "ACTIVE", "INACTIVE", "DISCONTINUED"]
Symbology = Literal["EAN13", "EAN8", "UPCA", "CODE128"]
Price = Field(ge=0, max_digits=19, decimal_places=4)
Qty = Field(default=Decimal("0"), ge=0, max_digits=19, decimal_places=4)


def _blank_to_none(value: Any) -> Any:
    return None if value == "" else value


# Categories, brands, units

class CategoryOut(Out):
    id: uuid.UUID
    code: str
    name_en: str
    name_km: str
    parent_id: uuid.UUID | None
    default_tax_code_id: uuid.UUID | None
    returnable: bool
    return_window_days: int
    allow_negative_stock: bool
    expiry_tracking_default: bool
    min_margin_pct: Decimal
    icon: str
    status: str


class CategoryCreate(Command):
    code: str = Field(min_length=1, max_length=30)
    name_en: str = Field(min_length=1, max_length=200)
    name_km: str = Field(default="", max_length=200)
    parent_id: uuid.UUID | None = None
    default_tax_code_id: uuid.UUID | None = None
    returnable: bool = True
    return_window_days: int = Field(default=7, ge=0, le=365)
    allow_negative_stock: bool = False
    expiry_tracking_default: bool = False
    min_margin_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    icon: str = Field(default="package", max_length=40)
    status: Status = "ACTIVE"

    _blank = field_validator("parent_id", "default_tax_code_id", mode="before")(_blank_to_none)


class CategoryUpdate(Command):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_km: str | None = Field(default=None, max_length=200)
    parent_id: uuid.UUID | None = None
    default_tax_code_id: uuid.UUID | None = None
    returnable: bool | None = None
    return_window_days: int | None = Field(default=None, ge=0, le=365)
    allow_negative_stock: bool | None = None
    expiry_tracking_default: bool | None = None
    min_margin_pct: Decimal | None = Field(default=None, ge=0, le=100)
    icon: str | None = Field(default=None, max_length=40)
    status: Status | None = None

    _blank = field_validator("parent_id", "default_tax_code_id", mode="before")(_blank_to_none)


class BrandOut(Out):
    id: uuid.UUID
    code: str
    name: str
    status: str


class BrandCreate(Command):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    status: Status = "ACTIVE"


class BrandUpdate(Command):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Status | None = None


class UnitOut(Out):
    id: uuid.UUID
    code: str
    name_en: str
    name_km: str
    dimension: str
    precision: int
    status: str


class UnitCreate(Command):
    code: str = Field(min_length=1, max_length=20)
    name_en: str = Field(min_length=1, max_length=100)
    name_km: str = Field(default="", max_length=100)
    dimension: Literal["COUNT", "MASS", "VOLUME", "LENGTH"] = "COUNT"
    precision: int = Field(default=0, ge=0, le=4)
    status: Status = "ACTIVE"


class UnitUpdate(Command):
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name_en: str | None = Field(default=None, min_length=1, max_length=100)
    name_km: str | None = Field(default=None, max_length=100)
    dimension: Literal["COUNT", "MASS", "VOLUME", "LENGTH"] | None = None
    precision: int | None = Field(default=None, ge=0, le=4)
    status: Status | None = None


# Products

class ConversionIn(Command):
    id: str | None = Field(default=None, description="Ignored; conversions are matched by unit")
    unit_id: uuid.UUID
    factor: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    is_purchase_default: bool = False
    is_sales_default: bool = False


class ConversionOut(Out):
    id: uuid.UUID
    unit_id: uuid.UUID
    factor: Decimal
    is_purchase_default: bool
    is_sales_default: bool


class BarcodeIn(Command):
    id: str | None = Field(default=None, description="Ignored; barcodes are matched by value")
    barcode: str = Field(min_length=1, max_length=64)
    symbology: Symbology = "CODE128"
    unit_id: uuid.UUID
    active: bool = True
    created_at: str | None = Field(default=None, description="Ignored")


class BarcodeOut(Out):
    id: uuid.UUID
    barcode: str
    symbology: str
    unit_id: uuid.UUID
    active: bool
    created_at: datetime


class StockSettingsIn(Command):
    reorder_level: Decimal = Qty
    min_level: Decimal = Qty
    max_level: Decimal = Qty
    reorder_qty: Decimal = Qty


class SupplierLinkIn(Command):
    supplier_id: str
    supplier_sku: str = ""
    purchase_unit_id: str = ""
    cost: Decimal = Decimal("0")
    lead_time_days: int = 0
    preferred: bool = False


class VariantIn(Command):
    attrs: dict[str, str]
    sku: str = Field(default="", max_length=60)
    barcode: str | None = Field(default=None, max_length=64)


class ProductFields(Command):
    sku: str | None = Field(default=None, max_length=60, description="Blank to generate one when SKU mode is AUTO")
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_km: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    type: ProductType | None = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    base_unit_id: uuid.UUID | None = None
    allow_fraction: bool | None = None
    precision: int | None = Field(default=None, ge=0, le=4)
    tax_code_id: uuid.UUID | None = None
    status: ProductStatus | None = None
    image: str | None = Field(default=None, max_length=3_000_000, description="Image URL, or a data: URL (JPEG, PNG or WebP up to 2 MB) that the API stores")
    min_selling_price: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    retail_price: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    wholesale_price: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    track_expiry: bool | None = None
    is_favourite: bool | None = None
    conversions: list[ConversionIn] | None = None
    barcodes: list[BarcodeIn] | None = None
    stock_settings: StockSettingsIn | None = None
    warehouse_settings: dict[uuid.UUID, StockSettingsIn] | None = None
    branch_activation: dict[uuid.UUID, bool] | None = None
    suppliers: list[SupplierLinkIn] | None = Field(default=None, description="Supplier links arrive with purchasing (Phase 6); only an empty list is accepted until then")

    _blank = field_validator("brand_id", "tax_code_id", "category_id", "base_unit_id", mode="before")(_blank_to_none)


class ProductCreate(ProductFields):
    name_en: str = Field(min_length=1, max_length=200)
    type: ProductType = "STANDARD"
    category_id: uuid.UUID
    base_unit_id: uuid.UUID
    status: Literal["DRAFT", "ACTIVE"] = "DRAFT"
    variants: list[VariantIn] = []


class ProductUpdate(ProductFields):
    pass


class StockSettingsOut(Out):
    reorder_level: Decimal
    min_level: Decimal
    max_level: Decimal
    reorder_qty: Decimal


class ProductOut(Out):
    id: uuid.UUID
    sku: str
    name_en: str
    name_km: str
    description: str
    type: str
    parent_id: uuid.UUID | None
    variant_attrs: dict[str, str] | None
    category_id: uuid.UUID
    brand_id: uuid.UUID | None
    base_unit_id: uuid.UUID
    allow_fraction: bool
    precision: int
    tax_code_id: uuid.UUID | None
    status: str
    image: str | None
    conversions: list[ConversionOut]
    barcodes: list[BarcodeOut]
    retail_price: Decimal
    wholesale_price: Decimal
    min_selling_price: Decimal | None
    last_purchase_cost: Decimal | None = Field(default=None, description="Only with inventory.cost.view")
    avg_cost: Decimal | None = Field(default=None, description="Only with inventory.cost.view")
    stock_settings: StockSettingsOut
    warehouse_settings: dict[uuid.UUID, StockSettingsOut]
    suppliers: list[dict]
    track_expiry: bool
    is_favourite: bool
    has_movements: bool
    branch_activation: dict[uuid.UUID, bool]
    created_at: datetime
    updated_at: datetime
    version: int
    category_name: str
    brand_name: str
    unit_code: str
    available: Decimal = Field(description="Sellable quantity in base units; stock is tracked from Phase 4")
    on_hand: Decimal


class ProductChangeOut(Out):
    id: str
    product_id: uuid.UUID
    at: datetime
    user_name: str
    field: str
    before: str
    after: str


class BarcodeRowOut(BarcodeOut):
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_code: str


class GeneratedBarcode(Out):
    barcode: str
    symbology: str


class ScanResult(ProductOut):
    scanned_barcode: str
    scanned_unit_id: uuid.UUID
    unit_factor: Decimal
    unit_price: Decimal | None
    price_source: str | None


# Pricing

class PriceListOut(Out):
    id: uuid.UUID
    code: str
    name: str
    type: str
    status: str


class PriceOut(Out):
    id: uuid.UUID
    product_id: uuid.UUID
    unit_id: uuid.UUID
    price_list_id: uuid.UUID
    branch_id: uuid.UUID | None
    customer_group_id: uuid.UUID | None
    price: Decimal
    effective_from: datetime
    effective_to: datetime | None
    created_by: str
    sku: str
    product_name: str
    scope_label: str


class PriceCreate(Command):
    product_id: uuid.UUID
    unit_id: uuid.UUID | None = Field(default=None, description="Defaults to the base unit")
    price_list_id: uuid.UUID | None = Field(default=None, description="Defaults to the Retail list")
    branch_id: uuid.UUID | None = None
    customer_group_id: uuid.UUID | None = None
    price: Decimal = Price
    effective_from: datetime | None = Field(default=None, description="Defaults to now; cannot be in the past")
    effective_to: datetime | None = None

    _blank = field_validator("unit_id", "price_list_id", "branch_id", "customer_group_id", mode="before")(_blank_to_none)


class PriceHistoryOut(Out):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    scope: str
    old_price: Decimal | None
    new_price: Decimal | None
    effective_from: datetime
    user_name: str
    at: datetime
    approved_by: str | None


class BulkPriceInput(Command):
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    mode: Literal["PERCENT", "AMOUNT"]
    value: Decimal = Field(ge=-100000, le=100000)
    effective_from: datetime | None = None

    _blank = field_validator("category_id", "brand_id", "effective_from", mode="before")(_blank_to_none)


class BulkPreviewRow(Out):
    product_id: uuid.UUID
    sku: str
    product_name: str
    current_price: Decimal
    new_price: Decimal
    margin_pct: Decimal | None
    below_min: bool


class BulkApplyResult(Out):
    updated: int
    scheduled: bool


class ResolvedPrice(Out):
    product_id: uuid.UUID
    unit_id: uuid.UUID
    branch_id: uuid.UUID | None
    price: Decimal | None
    source: str | None
