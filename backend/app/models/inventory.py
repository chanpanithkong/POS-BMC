"""Inventory (INV, CST, ADJ, TRF, ALR; Phase 4).

`inventory_movements` is the ledger: append-only (a trigger in migration 0003
rejects UPDATE and DELETE) and the only way balances change. Balances are kept
per location, product and batch in the same transaction as the movement, so
the sum of movements always equals the balance (checked by reconciliation).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Identity, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, Money, Quantity, UUIDPk

MOVEMENT_TYPES = (
    "OPENING", "PURCHASE_RECEIPT", "PURCHASE_RETURN", "SALE", "SALE_VOID", "SALE_RETURN", "TRANSFER_OUT", "TRANSFER_RECEIVE", "TRANSFER_VARIANCE",
    "ADJUSTMENT_IN", "ADJUSTMENT_OUT", "COUNT_VARIANCE", "DAMAGE", "EXPIRY", "LOSS", "WRITE_OFF", "RELOCATION", "REVERSAL",
)
DOC_STATUS = "status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED','POSTED','CANCELLED')"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({','.join(repr(v) for v in values)})"


class InventoryBalance(Base):
    __tablename__ = "inventory_balances"

    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse_locations.id"), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), primary_key=True, index=True)
    # '' when the stock is not batch-tracked.
    batch_no: Mapped[str] = mapped_column(String(60), primary_key=True, default="")
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"), index=True)
    on_hand: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    reserved: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    # Set only when the company and the product's category both allow negative stock (D-06).
    allow_negative: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("allow_negative OR on_hand >= 0", name="non_negative"),
        CheckConstraint("reserved >= 0", name="reserved_non_negative"),
    )


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    from_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouse_locations.id"))
    to_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouse_locations.id"))
    movement_type: Mapped[str] = mapped_column(String(20))
    quantity_base: Mapped[Quantity]
    unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("units.id"))
    quantity_entered: Mapped[Quantity]
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 6))
    total_cost: Mapped[Money]
    batch_no: Mapped[str] = mapped_column(String(60), default="")
    business_date: Mapped[date] = mapped_column(Date)
    posted_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(String(64))
    source_line_id: Mapped[str] = mapped_column(String(100))
    source_no: Mapped[str] = mapped_column(String(60), default="")
    reason_code: Mapped[str | None] = mapped_column(String(40))
    reverses_movement_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("inventory_movements.id"), unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", use_alter=True))
    user_name: Mapped[str] = mapped_column(String(200))
    approved_by: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        # One posting per document line and movement type (SRS 11.7).
        UniqueConstraint("source_type", "source_line_id", "movement_type"),
        CheckConstraint("quantity_base > 0", name="quantity_positive"),
        CheckConstraint("from_location_id IS NOT NULL OR to_location_id IS NOT NULL", name="has_location"),
        CheckConstraint("from_location_id IS NULL OR to_location_id IS NULL OR from_location_id <> to_location_id", name="distinct_locations"),
        CheckConstraint("unit_cost >= 0", name="cost_non_negative"),
        CheckConstraint(_in("movement_type", MOVEMENT_TYPES), name="movement_type"),
        Index("ix_inventory_movements_product_time", "product_id", "posted_at"),
        Index("ix_inventory_movements_warehouse_time", "warehouse_id", "posted_at"),
        Index("ix_inventory_movements_source", "source_type", "source_id"),
    )


class InventoryBatch(UUIDPk, Base):
    """Batch master: expiry per product and batch number. Quantities live in balances."""

    __tablename__ = "inventory_batches"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    batch_no: Mapped[str] = mapped_column(String(60))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    receipt_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (UniqueConstraint("product_id", "batch_no"),)


class StockAdjustment(UUIDPk, Authored, Base):
    __tablename__ = "stock_adjustments"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    adjustment_no: Mapped[str] = mapped_column(String(40))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    status: Mapped[str] = mapped_column(String(10), default="DRAFT")
    notes: Mapped[str] = mapped_column(Text, default="")
    attachment_url: Mapped[str | None] = mapped_column(String(500))
    requires_approval: Mapped[bool] = mapped_column(default=False)
    total_value: Mapped[Money] = mapped_column(default=Decimal("0"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by_name: Mapped[str | None] = mapped_column(String(200))
    posted_at: Mapped[datetime | None]
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (UniqueConstraint("company_id", "adjustment_no"), CheckConstraint(DOC_STATUS, name="status"))


class StockAdjustmentLine(UUIDPk, Base):
    __tablename__ = "stock_adjustment_lines"

    adjustment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_adjustments.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int]
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse_locations.id"))
    # Signed, in base units: positive adds stock, negative removes it.
    quantity: Mapped[Quantity]
    reason: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text, default="")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 6), default=Decimal("0"))
    value_impact: Mapped[Money] = mapped_column(default=Decimal("0"))

    __table_args__ = (
        CheckConstraint("quantity <> 0", name="quantity_non_zero"),
        CheckConstraint("reason IN ('DAMAGED','EXPIRED','LOST','FOUND','DATA_CORRECTION','INTERNAL_USE','WRITE_OFF')", name="reason"),
    )


TRANSFER_STATUS = ("REQUESTED", "APPROVED", "DISPATCHED", "PARTIALLY_RECEIVED", "RECEIVED", "CLOSED", "CANCELLED")


class StockTransfer(UUIDPk, Authored, Base):
    __tablename__ = "stock_transfers"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    transfer_no: Mapped[str] = mapped_column(String(40))
    source_warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"))
    destination_warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"))
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")
    reason: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[Money] = mapped_column(default=Decimal("0"))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by_name: Mapped[str | None] = mapped_column(String(200))
    dispatched_at: Mapped[datetime | None]
    received_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("company_id", "transfer_no"),
        CheckConstraint("source_warehouse_id <> destination_warehouse_id", name="distinct_warehouses"),
        CheckConstraint(_in("status", TRANSFER_STATUS), name="status"),
    )


class StockTransferLine(UUIDPk, Base):
    __tablename__ = "stock_transfer_lines"

    transfer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int]
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    quantity_requested: Mapped[Quantity]
    quantity_dispatched: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    quantity_received: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    quantity_short: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    quantity_damaged: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    quantity_excess: Mapped[Quantity] = mapped_column(default=Decimal("0"))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 6), default=Decimal("0"))

    __table_args__ = (
        CheckConstraint("quantity_requested > 0", name="requested_positive"),
        CheckConstraint("quantity_dispatched >= 0 AND quantity_received >= 0 AND quantity_short >= 0 AND quantity_damaged >= 0 AND quantity_excess >= 0", name="non_negative"),
        CheckConstraint("quantity_dispatched <= quantity_requested", name="dispatch_within_request"),
        CheckConstraint("quantity_received + quantity_short + quantity_damaged <= quantity_dispatched", name="receipt_within_dispatch"),
    )


COUNT_STATUS = ("OPEN", "COUNTING", "REVIEW", "APPROVED", "POSTED", "CANCELLED")


class StockCount(UUIDPk, Authored, Base):
    __tablename__ = "stock_counts"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    count_no: Mapped[str] = mapped_column(String(40))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"))
    scope: Mapped[str] = mapped_column(String(20))
    scope_label: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouse_locations.id"))
    freeze: Mapped[bool] = mapped_column(default=False)
    blind: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(10), default="COUNTING")
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    approved_by_name: Mapped[str | None] = mapped_column(String(200))
    posted_at: Mapped[datetime | None]
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("company_id", "count_no"),
        CheckConstraint("scope IN ('FULL','CYCLE_CATEGORY','CYCLE_LOCATION','CYCLE_RANDOM')", name="scope"),
        CheckConstraint(_in("status", COUNT_STATUS), name="status"),
    )


class StockCountLine(UUIDPk, Base):
    __tablename__ = "stock_count_lines"

    count_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("stock_counts.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse_locations.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    batch_no: Mapped[str] = mapped_column(String(60), default="")
    snapshot_qty: Mapped[Quantity]
    counted_qty: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    counted_at: Mapped[datetime | None]
    counted_by: Mapped[str | None] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(String(200), default="")
    recount_required: Mapped[bool] = mapped_column(default=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 6), default=Decimal("0"))

    __table_args__ = (
        UniqueConstraint("count_id", "location_id", "product_id", "batch_no"),
        CheckConstraint("counted_qty IS NULL OR counted_qty >= 0", name="counted_non_negative"),
    )


ALERT_TYPES = ("LOW_STOCK", "OUT_OF_STOCK", "OVERSTOCK", "NEGATIVE_STOCK", "EXPIRING", "EXPIRED", "SLOW_MOVING", "UNUSUAL_ADJUSTMENT")


class InventoryAlert(UUIDPk, Base):
    __tablename__ = "inventory_alerts"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id"))
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    # Distinguishes several open alerts of one type for the same product, e.g. one per batch or adjustment.
    subject: Mapped[str] = mapped_column(String(100), default="")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="OPEN")
    assigned_to: Mapped[str | None] = mapped_column(String(200))
    snoozed_until: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), onupdate=text("now()"))

    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint(_in("type", ALERT_TYPES), name="type"),
        CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED','SNOOZED')", name="status"),
        # At most one unresolved alert per condition (SRS 11.7).
        Index("uq_inventory_alerts_open", "company_id", "type", "product_id", text("coalesce(warehouse_id, '00000000-0000-0000-0000-000000000000'::uuid)"), "subject",
              unique=True, postgresql_where=text("status <> 'RESOLVED'")),
    )
