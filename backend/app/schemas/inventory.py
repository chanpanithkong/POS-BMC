"""Inventory schemas, shaped like the frontend `inventory.ts` types. Quantities are in base units."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.common import Command, Out

Qty = Field(max_digits=19, decimal_places=4)
PositiveQty = Field(gt=0, max_digits=19, decimal_places=4)
NonNegativeQty = Field(default=Decimal("0"), ge=0, max_digits=19, decimal_places=4)
Reason = Literal["DAMAGED", "EXPIRED", "LOST", "FOUND", "DATA_CORRECTION", "INTERNAL_USE", "WRITE_OFF"]


class TimelineEvent(Out):
    at: datetime
    label: str
    by: str
    note: str | None = None


# Ledger

class MovementOut(Out):
    id: int
    branch_id: uuid.UUID | None
    warehouse_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    from_location_id: uuid.UUID | None
    to_location_id: uuid.UUID | None
    from_location_name: str | None
    to_location_name: str | None
    type: str
    quantity_base: Decimal
    unit_code: str
    quantity_entered: Decimal
    unit_cost: Decimal | None = Field(description="Only with inventory.cost.view")
    total_cost: Decimal | None = Field(description="Only with inventory.cost.view")
    batch_no: str | None
    business_date: date
    posted_at: datetime
    source_type: str
    source_id: str
    source_no: str
    reason_code: str | None
    reverses_movement_id: int | None
    reversed_by_movement_id: int | None
    approved_by: str | None
    user_id: uuid.UUID | None
    user_name: str
    running_balance: Decimal | None = Field(description="Balance at the location after this movement; filled when product_id and location_id are given")


class LocationStock(Out):
    location_id: uuid.UUID
    location_name: str
    location_type: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    branch_id: uuid.UUID | None
    on_hand: Decimal
    reserved: Decimal


class StockOverviewRow(Out):
    product_id: uuid.UUID
    sku: str
    product_name: str
    category_id: uuid.UUID
    category_name: str
    unit_code: str
    on_hand: Decimal
    reserved: Decimal
    available: Decimal = Field(description="On hand minus reserved, at sellable locations")
    on_order: Decimal = Field(description="Open purchase order quantity; purchasing arrives in Phase 6")
    in_transit: Decimal
    reorder_level: Decimal
    max_level: Decimal
    avg_cost: Decimal | None
    value: Decimal | None
    status: Literal["IN_STOCK", "LOW", "OUT", "NEGATIVE", "OVER"]
    by_location: list[LocationStock]


class Availability(Out):
    product_id: uuid.UUID
    available: Decimal


class ReconciliationDifference(Out):
    sku: str
    location: str
    balance: Decimal
    movement_sum: Decimal


class ReconciliationResult(Out):
    checked_at: datetime
    balances_checked: int
    differences: list[ReconciliationDifference]


class BatchRow(Out):
    id: str
    product_id: uuid.UUID
    location_id: uuid.UUID
    batch_no: str
    expiry_date: date
    quantity: Decimal
    receipt_id: uuid.UUID | None
    sku: str
    product_name: str
    location_name: str
    warehouse_name: str
    days_to_expiry: int
    value: Decimal | None


class ReorderSuggestion(Out):
    product_id: uuid.UUID
    sku: str
    product_name: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    available: Decimal
    on_order: Decimal
    max_level: Decimal
    suggested_base: Decimal
    purchase_unit_id: uuid.UUID
    purchase_unit_code: str
    purchase_factor: Decimal
    suggested_qty: Decimal
    supplier_id: uuid.UUID | None
    supplier_name: str
    cost: Decimal | None
    lead_time_days: int


class OpeningBalanceIn(Command):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = PositiveQty
    unit_cost: Decimal = Field(ge=0, max_digits=19, decimal_places=6)
    batch_no: str = Field(default="", max_length=60)
    expiry_date: date | None = None


class RelocationIn(Command):
    product_id: uuid.UUID
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    quantity: Decimal = PositiveQty
    reason: str = Field(default="", max_length=200)


class ReverseIn(Command):
    reason: str = Field(min_length=3, max_length=500)


# Adjustments

class AdjustmentLineIn(Command):
    product_id: uuid.UUID
    location_id: uuid.UUID
    quantity: Decimal = Field(description="Signed, in base units: negative removes stock", max_digits=19, decimal_places=4)
    reason: Reason
    notes: str = Field(default="", max_length=500)
    name: str | None = Field(default=None, description="Ignored; display text from the form")


class AdjustmentCreate(Command):
    warehouse_id: uuid.UUID
    notes: str = Field(default="", max_length=2000)
    lines: list[AdjustmentLineIn]


class AdjustmentUpdate(Command):
    notes: str | None = Field(default=None, max_length=2000)
    lines: list[AdjustmentLineIn] | None = None


class AdjustmentLineOut(Out):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    location_id: uuid.UUID
    location_name: str
    quantity: Decimal
    unit_code: str
    reason: str
    notes: str
    unit_cost: Decimal | None
    value_impact: Decimal | None


class AdjustmentOut(Out):
    id: uuid.UUID
    adjustment_no: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    branch_id: uuid.UUID | None
    status: str
    lines: list[AdjustmentLineOut]
    notes: str
    attachment: str | None
    total_value: Decimal | None
    requires_approval: bool
    created_by: str
    created_by_id: uuid.UUID | None
    approved_by: str | None
    created_at: datetime
    posted_at: datetime | None
    timeline: list[TimelineEvent]
    version: int


class DocumentAction(Command):
    reason: str | None = Field(default=None, max_length=500)


# Transfers

class TransferLineIn(Command):
    product_id: uuid.UUID
    quantity: Decimal = PositiveQty
    name: str | None = Field(default=None, description="Ignored; display text from the form")


class TransferCreate(Command):
    source_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=500)
    lines: list[TransferLineIn]


class DispatchLineIn(Command):
    line_id: uuid.UUID
    quantity: Decimal = Field(ge=0, max_digits=19, decimal_places=4)


class ReceiveLineIn(Command):
    line_id: uuid.UUID
    received: Decimal = NonNegativeQty
    short: Decimal = NonNegativeQty
    damaged: Decimal = NonNegativeQty
    excess: Decimal = NonNegativeQty
    name: str | None = Field(default=None, description="Ignored")
    outstanding: Decimal | None = Field(default=None, description="Ignored; recomputed by the server")


class TransferAction(Command):
    reason: str | None = Field(default=None, max_length=500)


class DispatchAction(TransferAction):
    lines: list[DispatchLineIn] | None = Field(default=None, description="Omit to dispatch every line in full")


class ReceiveAction(TransferAction):
    lines: list[ReceiveLineIn]


TRANSFER_BODIES: dict[str, type[TransferAction]] = {"dispatch": DispatchAction, "receive": ReceiveAction}


class TransferLineOut(Out):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_code: str
    quantity_requested: Decimal
    quantity_dispatched: Decimal
    quantity_received: Decimal
    quantity_short: Decimal
    quantity_damaged: Decimal
    quantity_excess: Decimal


class TransferOut(Out):
    id: uuid.UUID
    transfer_no: str
    source_warehouse_id: uuid.UUID
    source_warehouse_name: str
    destination_warehouse_id: uuid.UUID
    destination_warehouse_name: str
    status: str
    reason: str
    lines: list[TransferLineOut]
    value: Decimal | None
    created_by: str
    created_by_id: uuid.UUID | None
    approved_by: str | None
    created_at: datetime
    dispatched_at: datetime | None
    received_at: datetime | None
    timeline: list[TimelineEvent]
    version: int


# Counts

class CountCreate(Command):
    warehouse_id: uuid.UUID
    scope: Literal["FULL", "CYCLE_CATEGORY", "CYCLE_LOCATION", "CYCLE_RANDOM"] = "FULL"
    category_id: uuid.UUID | None | Literal[""] = None
    location_id: uuid.UUID | None | Literal[""] = None
    sample_size: int = Field(default=20, ge=1, le=1000)
    freeze: bool = False
    blind: bool = True


class CountLineIn(Command):
    line_id: uuid.UUID
    counted_qty: Decimal | None = Field(default=None, ge=0, max_digits=19, decimal_places=4)
    reason: str | None = Field(default=None, max_length=200)


class CountLinesUpdate(Command):
    lines: list[CountLineIn]


class CountAction(Command):
    reason: str | None = Field(default=None, max_length=500)
    line_ids: list[uuid.UUID] | None = None


class CountLineOut(Out):
    id: uuid.UUID
    location_id: uuid.UUID
    location_name: str
    product_id: uuid.UUID
    sku: str
    product_name: str
    unit_code: str
    batch_no: str | None
    snapshot_qty: Decimal | None = Field(description="Hidden in blind counts until submitted")
    counted_qty: Decimal | None
    counted_at: datetime | None
    counted_by: str | None
    variance: Decimal | None
    value_variance: Decimal | None
    reason: str
    recount_required: bool


class CountOut(Out):
    id: uuid.UUID
    count_no: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    scope: str
    scope_label: str
    freeze: bool
    blind: bool
    status: str
    lines: list[CountLineOut]
    created_by: str
    created_by_id: uuid.UUID | None
    approved_by: str | None
    created_at: datetime
    posted_at: datetime | None
    timeline: list[TimelineEvent]
    version: int


# Alerts

class AlertOut(Out):
    id: uuid.UUID
    type: str
    product_id: uuid.UUID
    sku: str
    product_name: str
    warehouse_id: uuid.UUID | None
    warehouse_name: str
    branch_id: uuid.UUID | None
    message: str
    status: str
    assigned_to: str | None
    snoozed_until: datetime | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class AlertAction(Command):
    action: Literal["ACKNOWLEDGE", "RESOLVE", "SNOOZE", "ASSIGN"]
    note: str | None = Field(default=None, max_length=1000)
    assigned_to: str | None = Field(default=None, max_length=200)
    days: int | None = None


class EvaluateResult(Out):
    raised: int
    resolved: int
