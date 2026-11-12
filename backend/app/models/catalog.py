"""Catalogue and pricing (PRD, CAT, PRC; Phase 3).

Quantities are stored in the product's base unit. Prices are per selling unit
and time-bounded; overlapping prices for the same scope are rejected by an
EXCLUDE constraint created in migration 0002 (SRS 11.7).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, Money, Quantity, SoftDelete, UUIDPk

ACTIVE_STATUS = "status IN ('ACTIVE','INACTIVE')"


class Category(UUIDPk, Authored, Base):
    __tablename__ = "categories"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name_en: Mapped[str] = mapped_column(String(200))
    name_km: Mapped[str] = mapped_column(String(200), default="")
    # Up to four levels; cycles are prevented by the service (FR-CAT-001).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id"))
    default_tax_code_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_codes.id"))
    returnable: Mapped[bool] = mapped_column(default=True)
    return_window_days: Mapped[int] = mapped_column(SmallInteger, default=7)
    allow_negative_stock: Mapped[bool] = mapped_column(default=False)
    expiry_tracking_default: Mapped[bool] = mapped_column(default=False)
    min_margin_pct: Mapped[Decimal] = mapped_column(Numeric(9, 4), default=Decimal("0"))
    icon: Mapped[str] = mapped_column(String(40), default="package")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint(ACTIVE_STATUS, name="status"),
        CheckConstraint("return_window_days >= 0", name="return_window"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )


class Brand(UUIDPk, Authored, Base):
    __tablename__ = "brands"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (UniqueConstraint("company_id", "code"), CheckConstraint(ACTIVE_STATUS, name="status"))


class Unit(UUIDPk, Authored, Base):
    __tablename__ = "units"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(100))
    name_km: Mapped[str] = mapped_column(String(100), default="")
    dimension: Mapped[str] = mapped_column(String(10), default="COUNT")
    precision: Mapped[int] = mapped_column(SmallInteger, default=0)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("dimension IN ('COUNT','MASS','VOLUME','LENGTH')", name="dimension"),
        CheckConstraint("precision BETWEEN 0 AND 4", name="precision"),
        CheckConstraint(ACTIVE_STATUS, name="status"),
    )


class Product(UUIDPk, Authored, SoftDelete, Base):
    __tablename__ = "products"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    sku: Mapped[str] = mapped_column(String(60))
    name_en: Mapped[str] = mapped_column(String(200))
    name_km: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(15), default="STANDARD")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"), index=True)
    variant_attrs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id"), index=True)
    brand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brands.id"))
    # Locked once the product has inventory movements (BR-PRD-002).
    base_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    allow_fraction: Mapped[bool] = mapped_column(default=False)
    precision: Mapped[int] = mapped_column(SmallInteger, default=0)
    tax_code_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tax_codes.id"))
    status: Mapped[str] = mapped_column(String(15), default="DRAFT")
    image_url: Mapped[str | None] = mapped_column(String(500))
    min_selling_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    track_expiry: Mapped[bool] = mapped_column(default=False)
    is_favourite: Mapped[bool] = mapped_column(default=False)
    reorder_level: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    min_level: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    max_level: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    reorder_qty: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    # Maintained only by the inventory service (Phase 4) under a row lock; never writable through the product API.
    avg_cost: Mapped[Decimal] = mapped_column(Numeric(19, 6), default=Decimal("0"))
    last_purchase_cost: Mapped[Money] = mapped_column(default=Decimal("0"))
    has_movements: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        Index("uq_products_company_sku", "company_id", text("lower(sku)"), unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("ix_products_name_en_trgm", "name_en", postgresql_using="gin", postgresql_ops={"name_en": "gin_trgm_ops"}),
        Index("ix_products_name_km_trgm", "name_km", postgresql_using="gin", postgresql_ops={"name_km": "gin_trgm_ops"}),
        CheckConstraint("type IN ('STANDARD','WEIGHED','VARIANT_PARENT','SERVICE')", name="type"),
        CheckConstraint("status IN ('DRAFT','ACTIVE','INACTIVE','DISCONTINUED')", name="status"),
        CheckConstraint("precision BETWEEN 0 AND 4", name="precision"),
        CheckConstraint("min_selling_price IS NULL OR min_selling_price >= 0", name="min_price"),
        CheckConstraint("reorder_level >= 0 AND min_level >= 0 AND max_level >= 0 AND reorder_qty >= 0", name="stock_levels"),
        CheckConstraint("avg_cost >= 0 AND last_purchase_cost >= 0", name="costs"),
    )


class UnitConversion(UUIDPk, Base):
    """1 `unit_id` = `factor` base units of the product (FR-PRD-004)."""

    __tablename__ = "unit_conversions"

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    factor: Mapped[Quantity]
    is_purchase_default: Mapped[bool] = mapped_column(default=False)
    is_sales_default: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (UniqueConstraint("product_id", "unit_id"), CheckConstraint("factor > 0", name="factor_positive"))


class ProductBarcode(UUIDPk, Base):
    __tablename__ = "product_barcodes"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    barcode: Mapped[str] = mapped_column(String(64))
    symbology: Mapped[str] = mapped_column(String(10), default="CODE128")
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        # An active barcode maps to exactly one product and unit (BR-PRD-001).
        Index("uq_product_barcodes_active", "company_id", "barcode", unique=True, postgresql_where=text("active")),
        CheckConstraint("symbology IN ('EAN13','EAN8','UPCA','CODE128')", name="symbology"),
    )


class ProductBranchSetting(Base):
    """Per-branch activation. No row means active wherever the product is active."""

    __tablename__ = "product_branch_settings"

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True)
    active: Mapped[bool] = mapped_column(default=True)


class ProductWarehouseSetting(Base):
    """Per-warehouse reorder settings, overriding the product defaults (FR-ALR)."""

    __tablename__ = "product_warehouse_settings"

    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), primary_key=True)
    reorder_level: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    min_level: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    max_level: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    reorder_qty: Mapped[Quantity] = mapped_column(default=Decimal("0"))

    __table_args__ = (CheckConstraint("reorder_level >= 0 AND min_level >= 0 AND max_level >= 0 AND reorder_qty >= 0", name="levels"),)


class PriceList(UUIDPk, Authored, Base):
    __tablename__ = "price_lists"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(10))
    is_system: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("type IN ('RETAIL','WHOLESALE','GROUP','BRANCH')", name="type"),
        CheckConstraint(ACTIVE_STATUS, name="status"),
    )


class ProductPrice(UUIDPk, Base):
    """A price for one product unit in one scope over [effective_from, effective_to).

    Rows are never edited after they take effect: a change closes the current row
    and inserts a new one, so history is kept (FR-PRC-005).
    """

    __tablename__ = "product_prices"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    price_list_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_lists.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    # Customer groups arrive in Phase 6; the foreign key is added then.
    customer_group_id: Mapped[uuid.UUID | None]
    price: Mapped[Money]
    effective_from: Mapped[datetime]
    effective_to: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", use_alter=True))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("price >= 0", name="price_non_negative"),
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="valid_range"),
    )


class PriceChange(UUIDPk, Base):
    """Price change history (FR-PRC-005)."""

    __tablename__ = "price_changes"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    price_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("product_prices.id", ondelete="SET NULL"))
    scope: Mapped[str] = mapped_column(String(200))
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    new_price: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    effective_from: Mapped[datetime]
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", use_alter=True))
    user_name: Mapped[str] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(server_default=text("now()"))
