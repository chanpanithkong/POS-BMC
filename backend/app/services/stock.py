"""Stock ledger, balances and weighted-average costing (INV, CST; Phase 4).

`post()` is the only code that changes inventory balances. In one transaction it:
1. locks the affected products, then the balance rows in a fixed order (location,
   product, batch) so concurrent postings cannot deadlock;
2. checks quantities, product type, count freezes and stock availability;
3. updates weighted-average cost (company scope, D-05) for costed receipts;
4. writes one append-only movement per change and updates the balances.
Callers commit. Nothing else writes `inventory_balances.on_hand`.
"""

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, NotFound, ValidationFailed
from app.models import (
    Branch,
    Category,
    Company,
    InventoryBalance,
    InventoryBatch,
    InventoryMovement,
    Product,
    ProductSupplier,
    ProductWarehouseSetting,
    StockCount,
    StockCountLine,
    StockTransfer,
    StockTransferLine,
    Supplier,
    Unit,
    UnitConversion,
    User,
    Warehouse,
    WarehouseLocation,
)
from app.services.common import record_audit
from app.services.principal import Principal

# Inbound movements that carry their own cost and so update the weighted average.
COSTED_INBOUND = {"OPENING", "PURCHASE_RECEIPT", "SALE_VOID", "SALE_RETURN"}
REVERSIBLE = {"OPENING", "ADJUSTMENT_IN", "ADJUSTMENT_OUT", "COUNT_VARIANCE", "DAMAGE", "EXPIRY", "LOSS", "WRITE_OFF", "RELOCATION"}
NON_STOCK_TYPES = {"SERVICE", "VARIANT_PARENT"}
COST_PLACES = Decimal("0.000001")
MONEY_PLACES = Decimal("0.0001")
FROZEN_STATUSES = ("COUNTING", "REVIEW", "APPROVED")


class InsufficientStock(AppError):
    status_code, code = 409, "INSUFFICIENT_STOCK"


class StockFrozen(AppError):
    status_code, code = 409, "STOCK_FROZEN"


@dataclass
class Move:
    product: Product
    quantity: Decimal
    movement_type: str
    source_type: str
    source_id: str
    source_line_id: str
    from_location: WarehouseLocation | None = None
    to_location: WarehouseLocation | None = None
    source_no: str = ""
    unit_cost: Decimal | None = None  # explicit cost for costed receipts; otherwise the current average
    remove_cost: Decimal | None = None  # reversing a costed receipt takes its cost back out of the average
    reason: str | None = None
    batch_no: str = ""
    expiry_date: date | None = None
    approved_by: str | None = None
    reverses_movement_id: int | None = None
    unit_id: uuid.UUID | None = None
    quantity_entered: Decimal | None = None
    ignore_freeze_for_count: uuid.UUID | None = None
    # Warehouse the movement is booked to when one side is the system in-transit location (e.g. a transfer shortage).
    ledger_warehouse_id: uuid.UUID | None = None


@dataclass
class _Context:
    company_settings: dict
    warehouses: dict[uuid.UUID, Warehouse] = field(default_factory=dict)
    branches: dict[uuid.UUID, Branch] = field(default_factory=dict)
    categories: dict[uuid.UUID, Category] = field(default_factory=dict)


def now() -> datetime:
    return datetime.now(UTC)


def business_date(branch: Branch | None, at: datetime | None = None) -> date:
    """The trading day a moment belongs to: branch local time, shifted by the day cut-off (FR-ORG-007)."""
    at = at or now()
    if branch is None:
        return at.astimezone(ZoneInfo("Asia/Phnom_Penh")).date()
    local = at.astimezone(ZoneInfo(branch.timezone))
    cutoff = branch.day_cutoff
    shifted = local - timedelta(hours=cutoff.hour, minutes=cutoff.minute)
    return shifted.date()


def check_quantity(product: Product, quantity: Decimal, field_name: str = "quantity") -> None:
    if quantity != quantity.quantize(Decimal(1).scaleb(-product.precision)):
        raise ValidationFailed(field_name, f"{product.sku} allows {product.precision} decimal places.")


async def in_transit_location(db: AsyncSession, company_id: uuid.UUID) -> WarehouseLocation:
    location = await db.scalar(
        select(WarehouseLocation).join(Warehouse, Warehouse.id == WarehouseLocation.warehouse_id)
        .where(Warehouse.company_id == company_id, Warehouse.is_system.is_(True), WarehouseLocation.location_type == "IN_TRANSIT")
    )
    if location is None:
        raise AppError("The in-transit location is missing.", code="CONFIGURATION_ERROR", status_code=500)
    return location


async def _negative_allowed(db: AsyncSession, ctx: _Context, product: Product) -> bool:
    if not ctx.company_settings.get("negative_stock_allowed"):
        return False
    category = ctx.categories.get(product.category_id) or await db.get(Category, product.category_id)
    if category is None:
        return False
    ctx.categories[category.id] = category
    return category.allow_negative_stock


async def _check_freeze(db: AsyncSession, move: Move, location: WarehouseLocation) -> None:
    query = (
        select(StockCount.count_no).join(StockCountLine, StockCountLine.count_id == StockCount.id)
        .where(StockCount.freeze.is_(True), StockCount.status.in_(FROZEN_STATUSES), StockCountLine.location_id == location.id, StockCountLine.product_id == move.product.id)
    )
    if move.ignore_freeze_for_count:
        query = query.where(StockCount.id != move.ignore_freeze_for_count)
    count_no = await db.scalar(query.limit(1))
    if count_no:
        raise StockFrozen(f"{move.product.sku} at {location.code} is frozen by stock count {count_no}.")


async def _company_total(db: AsyncSession, product_id: uuid.UUID) -> Decimal:
    return Decimal(await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand), 0)).where(InventoryBalance.product_id == product_id)) or 0)


async def lock_balances(db: AsyncSession, company_id: uuid.UUID, keys: Iterable[tuple[WarehouseLocation, uuid.UUID, str]]) -> dict[tuple[uuid.UUID, uuid.UUID, str], InventoryBalance]:
    unique = {(loc.id, pid, batch): loc for loc, pid, batch in keys}
    ordered = sorted(unique, key=lambda k: (str(k[0]), str(k[1]), k[2]))
    if ordered:
        await db.execute(
            insert(InventoryBalance).values([{"location_id": k[0], "product_id": k[1], "batch_no": k[2], "company_id": company_id, "warehouse_id": unique[k].warehouse_id} for k in ordered])
            .on_conflict_do_nothing()
        )
    locked: dict[tuple[uuid.UUID, uuid.UUID, str], InventoryBalance] = {}
    for key in ordered:  # one at a time, in key order
        row = await db.scalar(
            select(InventoryBalance).where(InventoryBalance.location_id == key[0], InventoryBalance.product_id == key[1], InventoryBalance.batch_no == key[2])
            .with_for_update().execution_options(populate_existing=True)
        )
        assert row is not None
        locked[key] = row
    return locked


async def post(db: AsyncSession, actor: Principal, moves: list[Move]) -> list[InventoryMovement]:
    if not moves:
        return []
    company = await db.get(Company, actor.company_id)
    ctx = _Context(company_settings=(company.settings or {}) if company else {})
    products: dict[uuid.UUID, Product] = {}
    for pid in sorted({m.product.id for m in moves}, key=str):
        product = await db.scalar(select(Product).where(Product.id == pid, Product.company_id == actor.company_id).with_for_update().execution_options(populate_existing=True))
        if product is None:
            raise NotFound("Product")
        products[pid] = product
    keys = []
    for m in moves:
        m.product = products[m.product.id]
        for loc in (m.from_location, m.to_location):
            if loc is not None:
                if loc.company_id != actor.company_id:
                    raise NotFound("Location")
                keys.append((loc, m.product.id, m.batch_no))
    balances = await lock_balances(db, actor.company_id, keys)

    posted = []
    for m in moves:
        product = m.product
        if product.type in NON_STOCK_TYPES:
            raise ValidationFailed("product_id", f"{product.sku} does not hold stock.")
        if m.quantity <= 0:
            raise ValidationFailed("quantity", "Quantity must be greater than zero.")
        check_quantity(product, m.quantity)
        for loc in (m.from_location, m.to_location):
            if loc is not None:
                await _check_freeze(db, m, loc)

        # Cost (weighted average, company scope).
        if m.movement_type in COSTED_INBOUND and m.unit_cost is not None:
            total = await _company_total(db, product.id)
            if total <= 0:
                product.avg_cost = m.unit_cost.quantize(COST_PLACES, ROUND_HALF_UP)
            else:
                product.avg_cost = ((total * product.avg_cost + m.quantity * m.unit_cost) / (total + m.quantity)).quantize(COST_PLACES, ROUND_HALF_UP)
            if m.movement_type == "PURCHASE_RECEIPT":
                product.last_purchase_cost = m.unit_cost.quantize(MONEY_PLACES, ROUND_HALF_UP)
            unit_cost = m.unit_cost
        elif m.remove_cost is not None:
            total = await _company_total(db, product.id)
            remaining = total - m.quantity
            if remaining > 0:
                product.avg_cost = max(Decimal("0"), (total * product.avg_cost - m.quantity * m.remove_cost) / remaining).quantize(COST_PLACES, ROUND_HALF_UP)
            unit_cost = m.remove_cost
        else:
            unit_cost = product.avg_cost

        # Balances.
        if m.from_location is not None:
            bal = balances[(m.from_location.id, product.id, m.batch_no)]
            bal.on_hand -= m.quantity
            if bal.on_hand < bal.reserved:
                allowed = m.from_location.location_type != "IN_TRANSIT" and await _negative_allowed(db, ctx, product)
                if not allowed:
                    available = bal.on_hand + m.quantity - bal.reserved
                    raise InsufficientStock(
                        f"Not enough {product.sku} at {m.from_location.code}: {available.normalize()} available, {m.quantity.normalize()} needed.",
                        details=[{"product_id": str(product.id), "sku": product.sku, "location_id": str(m.from_location.id), "available": str(available), "requested": str(m.quantity)}],
                    )
                bal.allow_negative = True
            bal.updated_at = now()
        if m.to_location is not None:
            bal = balances[(m.to_location.id, product.id, m.batch_no)]
            bal.on_hand += m.quantity
            bal.updated_at = now()
        if m.batch_no and m.expiry_date:
            await db.execute(insert(InventoryBatch).values(company_id=actor.company_id, product_id=product.id, batch_no=m.batch_no, expiry_date=m.expiry_date).on_conflict_do_nothing())

        # Book the movement to the real warehouse involved, never to the system in-transit warehouse.
        real = [loc for loc in (m.from_location, m.to_location) if loc is not None and loc.location_type != "IN_TRANSIT"]
        warehouse_id = m.ledger_warehouse_id or (real[0].warehouse_id if real else (m.from_location or m.to_location).warehouse_id)  # type: ignore[union-attr]
        warehouse = ctx.warehouses.get(warehouse_id) or await db.get(Warehouse, warehouse_id)
        assert warehouse is not None
        ctx.warehouses[warehouse.id] = warehouse
        branch = None
        if warehouse.branch_id:
            branch = ctx.branches.get(warehouse.branch_id) or await db.get(Branch, warehouse.branch_id)
            if branch:
                ctx.branches[branch.id] = branch
        movement = InventoryMovement(
            company_id=actor.company_id, branch_id=warehouse.branch_id, warehouse_id=warehouse.id, product_id=product.id,
            from_location_id=m.from_location.id if m.from_location else None, to_location_id=m.to_location.id if m.to_location else None,
            movement_type=m.movement_type, quantity_base=m.quantity, unit_id=m.unit_id or product.base_unit_id, quantity_entered=m.quantity_entered or m.quantity,
            unit_cost=unit_cost.quantize(COST_PLACES, ROUND_HALF_UP), total_cost=(unit_cost * m.quantity).quantize(MONEY_PLACES, ROUND_HALF_UP),
            batch_no=m.batch_no, business_date=business_date(branch), source_type=m.source_type, source_id=m.source_id, source_line_id=m.source_line_id,
            source_no=m.source_no, reason_code=m.reason, reverses_movement_id=m.reverses_movement_id, user_id=actor.user_id, user_name=actor.full_name, approved_by=m.approved_by,
        )
        db.add(movement)
        product.has_movements = True
        posted.append(movement)
    await db.flush()
    return posted


# Locations and scope

def visible_warehouses(actor: Principal):
    query = select(Warehouse.id).where(Warehouse.company_id == actor.company_id, Warehouse.is_system.is_(False))
    if actor.warehouse_ids is not None:
        query = query.where(Warehouse.id.in_(actor.warehouse_ids))
    elif actor.branch_ids is not None:
        query = query.where(Warehouse.branch_id.in_(actor.branch_ids) | Warehouse.branch_id.is_(None))
    return query


async def scoped_warehouse(db: AsyncSession, actor: Principal, warehouse_id: uuid.UUID) -> Warehouse:
    warehouse = await db.scalar(select(Warehouse).where(Warehouse.id == warehouse_id, Warehouse.id.in_(visible_warehouses(actor))))
    if warehouse is None:
        raise NotFound("Warehouse")
    return warehouse


async def scoped_location(db: AsyncSession, actor: Principal, location_id: uuid.UUID, *, warehouse_id: uuid.UUID | None = None) -> WarehouseLocation:
    location = await db.scalar(select(WarehouseLocation).where(WarehouseLocation.id == location_id, WarehouseLocation.warehouse_id.in_(visible_warehouses(actor))))
    if location is None or (warehouse_id and location.warehouse_id != warehouse_id):
        raise NotFound("Location")
    if location.status != "ACTIVE":
        raise ValidationFailed("location_id", f"Location {location.code} is inactive.")
    return location


async def stock_product(db: AsyncSession, actor: Principal, product_id: uuid.UUID) -> Product:
    product = await db.scalar(select(Product).where(Product.id == product_id, Product.company_id == actor.company_id, Product.deleted_at.is_(None)))
    if product is None:
        raise NotFound("Product")
    if product.type in NON_STOCK_TYPES:
        raise ValidationFailed("product_id", f"{product.sku} does not hold stock.")
    return product


# Commands: opening balances, relocation, reversal

async def opening_balance(db: AsyncSession, actor: Principal, *, product_id: uuid.UUID, location_id: uuid.UUID, quantity: Decimal, unit_cost: Decimal,
                          batch_no: str, expiry_date: date | None, key: str) -> InventoryMovement:
    """Initial stock for a product that has never moved (go-live, FR-INV-001)."""
    product = await stock_product(db, actor, product_id)
    if product.has_movements:
        raise Conflict(f"{product.sku} already has stock movements. Use an adjustment instead.", code="HAS_MOVEMENTS")
    location = await scoped_location(db, actor, location_id)
    if location.location_type == "IN_TRANSIT":
        raise ValidationFailed("location_id", "Opening stock cannot be placed in transit.")
    [movement] = await post(db, actor, [Move(product, quantity, "OPENING", "OPENING", str(product.id), f"OPENING:{key}", to_location=location, unit_cost=unit_cost,
                                             batch_no=batch_no, expiry_date=expiry_date, reason="OPENING")])
    await record_audit(db, actor, "OPENING_STOCK_POSTED", "INV", "product", product.id, after={"location": location.code, "quantity": str(quantity), "unit_cost": str(unit_cost)}, branch_id=movement.branch_id)
    await db.commit()
    return movement


async def split_by_batch(db: AsyncSession, product_id: uuid.UUID, location_id: uuid.UUID, quantity: Decimal, *, usable_on: date | None = None) -> list[tuple[str, Decimal]]:
    """Splits a quantity leaving a location across the batches held there, earliest expiry first (FEFO).

    With `usable_on`, batches that expired before that day are skipped, so expired stock is never sold.
    Stock without a batch has batch_no "". Any shortfall is returned as a "" part so the ledger
    reports it with its usual INSUFFICIENT_STOCK error.
    """
    query = (select(InventoryBalance.batch_no, InventoryBalance.on_hand - InventoryBalance.reserved)
             .outerjoin(InventoryBatch, (InventoryBatch.product_id == InventoryBalance.product_id) & (InventoryBatch.batch_no == InventoryBalance.batch_no)
                        & (InventoryBatch.company_id == InventoryBalance.company_id))
             .where(InventoryBalance.location_id == location_id, InventoryBalance.product_id == product_id, InventoryBalance.on_hand > InventoryBalance.reserved)
             .order_by(InventoryBatch.expiry_date.asc().nulls_last(), InventoryBalance.batch_no))
    if usable_on is not None:
        query = query.where((InventoryBatch.expiry_date.is_(None)) | (InventoryBatch.expiry_date >= usable_on))
    parts: dict[str, Decimal] = {}
    remaining = quantity
    for batch_no, free in await db.execute(query):
        take = min(remaining, free)
        if take > 0:
            parts[batch_no] = parts.get(batch_no, Decimal(0)) + take
            remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        parts[""] = parts.get("", Decimal(0)) + remaining
    return list(parts.items())


async def sold_batches(db: AsyncSession, company_id: uuid.UUID, line_id: uuid.UUID) -> list[tuple[str, Decimal]]:
    """The batches a sale line took stock from, in the order they were taken."""
    rows = await db.execute(
        select(InventoryMovement.batch_no, InventoryMovement.quantity_base)
        .where(InventoryMovement.company_id == company_id, InventoryMovement.movement_type == "SALE",
               (InventoryMovement.source_line_id == str(line_id)) | InventoryMovement.source_line_id.like(f"{line_id}:%"))
        .order_by(InventoryMovement.id))
    return [(batch, qty) for batch, qty in rows]


def take_from(parts: list[tuple[str, Decimal]], quantity: Decimal) -> list[tuple[str, Decimal]]:
    """Allocates a quantity across (batch, quantity) parts in order; any excess goes to the last batch (or "")."""
    out: dict[str, Decimal] = {}
    remaining = quantity
    for batch, available in parts:
        take = min(remaining, available)
        if take > 0:
            out[batch] = out.get(batch, Decimal(0)) + take
            remaining -= take
    if remaining > 0:
        last = parts[-1][0] if parts else ""
        out[last] = out.get(last, Decimal(0)) + remaining
    return list(out.items())


def line_key(line_id: uuid.UUID | str, batch_no: str, split: bool) -> str:
    """Ledger source_line_id for a document line; a line taken from several batches gets one row per batch."""
    return f"{line_id}:{batch_no or '-'}" if split else str(line_id)


async def relocate(db: AsyncSession, actor: Principal, *, product_id: uuid.UUID, from_location_id: uuid.UUID, to_location_id: uuid.UUID, quantity: Decimal, reason: str, key: str) -> InventoryMovement:
    product = await stock_product(db, actor, product_id)
    source = await scoped_location(db, actor, from_location_id)
    target = await scoped_location(db, actor, to_location_id)
    if source.id == target.id:
        raise ValidationFailed("to_location_id", "Choose a different location.")
    if source.warehouse_id != target.warehouse_id:
        raise ValidationFailed("to_location_id", "Moving stock between warehouses needs a transfer.")
    if "IN_TRANSIT" in (source.location_type, target.location_type):
        raise ValidationFailed("to_location_id", "In-transit stock moves only through transfers.")
    moves = [Move(product, part, "RELOCATION", "RELOCATION", str(product.id), f"RELOCATION:{key}:{n}", from_location=source, to_location=target, reason=reason or None, batch_no=batch_no)
             for n, (batch_no, part) in enumerate(await split_by_batch(db, product.id, source.id, quantity))]
    movement = (await post(db, actor, moves))[0]
    await record_audit(db, actor, "STOCK_RELOCATED", "INV", "product", product.id, after={"from": source.code, "to": target.code, "quantity": str(quantity), "reason": reason}, branch_id=movement.branch_id)
    await db.commit()
    return movement


async def reverse(db: AsyncSession, actor: Principal, movement_id: int, reason: str) -> InventoryMovement:
    original = await db.scalar(select(InventoryMovement).where(InventoryMovement.id == movement_id, InventoryMovement.company_id == actor.company_id, InventoryMovement.warehouse_id.in_(visible_warehouses(actor))))
    if original is None:
        raise NotFound("Movement")
    if original.movement_type not in REVERSIBLE:
        raise Conflict(f"{original.movement_type} movements are corrected through their own documents (void, return or transfer), not reversed here.", code="NOT_REVERSIBLE")
    if await db.scalar(select(InventoryMovement.id).where(InventoryMovement.reverses_movement_id == original.id)):
        raise Conflict("This movement has already been reversed.", code="ALREADY_REVERSED")
    product = await db.get(Product, original.product_id)
    assert product is not None
    source = await db.get(WarehouseLocation, original.to_location_id) if original.to_location_id else None
    target = await db.get(WarehouseLocation, original.from_location_id) if original.from_location_id else None
    costed = original.movement_type in COSTED_INBOUND
    [movement] = await post(db, actor, [Move(
        product, original.quantity_base, "REVERSAL", "REVERSAL", str(original.id), f"REVERSAL:{original.id}", from_location=source, to_location=target,
        source_no=original.source_no, reason=reason, batch_no=original.batch_no, reverses_movement_id=original.id, remove_cost=original.unit_cost if costed and source else None,
        unit_id=original.unit_id, quantity_entered=original.quantity_entered,
    )])
    await record_audit(db, actor, "MOVEMENT_REVERSED", "INV", "movement", original.id, after={"reversal_id": movement.id, "reason": reason, "type": original.movement_type}, flagged=True, branch_id=movement.branch_id)
    await db.commit()
    return movement


# Queries

def _cost(actor: Principal, value: Decimal | None) -> Decimal | None:
    return value if actor.sees_cost else None


async def movement_rows(db: AsyncSession, actor: Principal, *, product_id: uuid.UUID | None = None, warehouse_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None,
                        location_id: uuid.UUID | None = None, movement_type: str | None = None, source_id: str | None = None, date_from: date | None = None, date_to: date | None = None,
                        movement_id: int | None = None, limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
    from_loc, to_loc = WarehouseLocation.__table__.alias("from_loc"), WarehouseLocation.__table__.alias("to_loc")
    reversal = InventoryMovement.__table__.alias("reversal")
    query = (
        select(InventoryMovement, Product.sku, Product.name_en, Unit.code, from_loc.c.name, to_loc.c.name, reversal.c.id)
        .join(Product, Product.id == InventoryMovement.product_id).join(Unit, Unit.id == InventoryMovement.unit_id)
        .outerjoin(from_loc, from_loc.c.id == InventoryMovement.from_location_id).outerjoin(to_loc, to_loc.c.id == InventoryMovement.to_location_id)
        .outerjoin(reversal, reversal.c.reverses_movement_id == InventoryMovement.id)
        .where(InventoryMovement.company_id == actor.company_id)
    )
    query = query.where(InventoryMovement.warehouse_id.in_(visible_warehouses(actor)))
    for column, value in ((InventoryMovement.id, movement_id), (InventoryMovement.product_id, product_id), (InventoryMovement.warehouse_id, warehouse_id), (InventoryMovement.branch_id, branch_id),
                          (InventoryMovement.movement_type, movement_type), (InventoryMovement.source_id, source_id)):
        if value is not None:
            query = query.where(column == value)
    if location_id:
        query = query.where(or_(InventoryMovement.from_location_id == location_id, InventoryMovement.to_location_id == location_id))
    if date_from:
        query = query.where(InventoryMovement.business_date >= date_from)
    if date_to:
        query = query.where(InventoryMovement.business_date <= date_to)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = (await db.execute(query.order_by(InventoryMovement.id.desc()).limit(limit).offset(offset))).all()
    running: dict[uuid.UUID, Decimal] = {}
    if product_id and location_id:
        # Signed running balance at this location, newest first: start from the current balance and walk back.
        current = Decimal(await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand), 0)).where(InventoryBalance.product_id == product_id, InventoryBalance.location_id == location_id)) or 0)
        later = Decimal(0)
        if offset:
            newer = query.order_by(InventoryMovement.id.desc()).limit(offset).subquery()
            signed = case((newer.c.to_location_id == location_id, newer.c.quantity_base), else_=-newer.c.quantity_base)
            later = Decimal(await db.scalar(select(func.coalesce(func.sum(signed), 0))) or 0)
        running[product_id] = current - later
    out = []
    for m, sku, name, unit_code, from_name, to_name, reversed_by in rows:
        row = {
            "id": m.id, "branch_id": m.branch_id, "warehouse_id": m.warehouse_id, "product_id": m.product_id, "sku": sku, "product_name": name,
            "from_location_id": m.from_location_id, "to_location_id": m.to_location_id, "from_location_name": from_name, "to_location_name": to_name, "type": m.movement_type,
            "quantity_base": m.quantity_base, "unit_code": unit_code, "quantity_entered": m.quantity_entered, "unit_cost": _cost(actor, m.unit_cost), "total_cost": _cost(actor, m.total_cost),
            "batch_no": m.batch_no or None, "business_date": m.business_date, "posted_at": m.posted_at, "source_type": m.source_type, "source_id": m.source_id, "source_no": m.source_no,
            "reason_code": m.reason_code, "reverses_movement_id": m.reverses_movement_id, "reversed_by_movement_id": reversed_by, "approved_by": m.approved_by, "user_id": m.user_id, "user_name": m.user_name,
            "running_balance": None,
        }
        if product_id in running:
            row["running_balance"] = running[product_id]
            running[product_id] -= m.quantity_base if m.to_location_id == location_id else -m.quantity_base
        out.append(row)
    return out, total


async def overview(db: AsyncSession, actor: Principal, *, branch_id: uuid.UUID | None, warehouse_id: uuid.UUID | None, location_type: str | None, q: str | None,
                   category_id: uuid.UUID | None, product_id: uuid.UUID | None, limit: int, offset: int) -> tuple[list[dict], int]:
    """One row per stock product with on-hand, reserved, available, in-transit and per-location detail."""
    if branch_id:
        actor.assert_branch(branch_id)
    warehouses = visible_warehouses(actor)
    if warehouse_id:
        warehouses = warehouses.where(Warehouse.id == warehouse_id)
    if branch_id:
        warehouses = warehouses.where(Warehouse.branch_id == branch_id)
    product_query = select(Product).where(Product.company_id == actor.company_id, Product.deleted_at.is_(None), Product.type.not_in(NON_STOCK_TYPES), Product.status != "DRAFT")
    if q:
        like = f"%{q.lower()}%"
        product_query = product_query.where(or_(func.lower(Product.name_en).like(like), func.lower(Product.sku).like(like)))
    if category_id:
        product_query = product_query.where(Product.category_id == category_id)
    if product_id:
        product_query = product_query.where(Product.id == product_id)
    total = int(await db.scalar(select(func.count()).select_from(product_query.subquery())) or 0)
    products = list(await db.scalars(product_query.order_by(Product.name_en).limit(limit).offset(offset)))
    if not products:
        return [], total
    ids = [p.id for p in products]
    loc_query = (
        select(InventoryBalance, WarehouseLocation, Warehouse)
        .join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .where(InventoryBalance.product_id.in_(ids), InventoryBalance.warehouse_id.in_(warehouses))
    )
    if location_type:
        loc_query = loc_query.where(WarehouseLocation.location_type == location_type)
    by_product: dict[uuid.UUID, list] = {}
    for bal, loc, wh in await db.execute(loc_query):
        by_product.setdefault(bal.product_id, []).append((bal, loc, wh))
    transit_query = (
        select(StockTransferLine.product_id, func.sum(StockTransferLine.quantity_dispatched - StockTransferLine.quantity_received - StockTransferLine.quantity_short - StockTransferLine.quantity_damaged))
        .join(StockTransfer, StockTransfer.id == StockTransferLine.transfer_id)
        .where(StockTransfer.company_id == actor.company_id, StockTransfer.status.in_(("DISPATCHED", "PARTIALLY_RECEIVED")), StockTransfer.destination_warehouse_id.in_(warehouses), StockTransferLine.product_id.in_(ids))
        .group_by(StockTransferLine.product_id)
    )
    in_transit = {pid: Decimal(qty or 0) for pid, qty in await db.execute(transit_query)}
    from app.services.purchasing import on_order as open_po_qty

    ordered = await open_po_qty(db, ids, warehouses)
    categories = {c.id: c.name_en for c in await db.scalars(select(Category).where(Category.id.in_({p.category_id for p in products})))}
    units = {u.id: u.code for u in await db.scalars(select(Unit).where(Unit.id.in_({p.base_unit_id for p in products})))}
    rows = []
    for p in products:
        entries = by_product.get(p.id, [])
        on_hand = sum((b.on_hand for b, _, _ in entries), Decimal(0))
        reserved = sum((b.reserved for b, _, _ in entries), Decimal(0))
        available = sum((b.on_hand - b.reserved for b, loc, _ in entries if loc.is_available_for_sale), Decimal(0))
        reorder, max_level = p.reorder_level, p.max_level
        if warehouse_id:
            override = await db.get(ProductWarehouseSetting, (p.id, warehouse_id))
            if override is not None:
                reorder, max_level = override.reorder_level, override.max_level
        if on_hand < 0:
            status = "NEGATIVE"
        elif on_hand == 0:
            status = "OUT"
        elif reorder > 0 and available <= reorder:
            status = "LOW"
        elif max_level > 0 and on_hand > max_level:
            status = "OVER"
        else:
            status = "IN_STOCK"
        locations: dict[uuid.UUID, dict] = {}
        for b, loc, wh in entries:
            entry = locations.setdefault(loc.id, {"location_id": loc.id, "location_name": loc.name, "location_type": loc.location_type, "warehouse_id": wh.id, "warehouse_name": wh.name,
                                                  "branch_id": wh.branch_id, "on_hand": Decimal(0), "reserved": Decimal(0)})
            entry["on_hand"] += b.on_hand
            entry["reserved"] += b.reserved
        rows.append({
            "product_id": p.id, "sku": p.sku, "product_name": p.name_en, "category_id": p.category_id, "category_name": categories.get(p.category_id, ""), "unit_code": units.get(p.base_unit_id, ""),
            "on_hand": on_hand, "reserved": reserved, "available": available, "on_order": ordered.get(p.id, Decimal(0)), "in_transit": in_transit.get(p.id, Decimal(0)),
            "reorder_level": reorder, "max_level": max_level, "avg_cost": _cost(actor, p.avg_cost), "value": _cost(actor, (on_hand * p.avg_cost).quantize(MONEY_PLACES, ROUND_HALF_UP)),
            "status": status, "by_location": [v for v in locations.values() if v["on_hand"] or v["reserved"]],
        })
    return rows, total


async def availability(db: AsyncSession, actor: Principal, product_ids: list[uuid.UUID], *, branch_id: uuid.UUID | None, location_id: uuid.UUID | None) -> list[dict]:
    """Sellable quantity (on hand minus reserved) at sellable locations, for POS checks."""
    query = (
        select(InventoryBalance.product_id, func.coalesce(func.sum(InventoryBalance.on_hand - InventoryBalance.reserved), 0))
        .join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .where(InventoryBalance.product_id.in_(product_ids), WarehouseLocation.is_available_for_sale.is_(True), InventoryBalance.warehouse_id.in_(visible_warehouses(actor)))
        .group_by(InventoryBalance.product_id)
    )
    if branch_id:
        actor.assert_branch(branch_id)
        query = query.where(Warehouse.branch_id == branch_id)
    if location_id:
        query = query.where(InventoryBalance.location_id == location_id)
    found = {pid: Decimal(qty) for pid, qty in await db.execute(query)}
    return [{"product_id": pid, "available": found.get(pid, Decimal(0))} for pid in product_ids]


async def reconcile(db: AsyncSession, actor: Principal) -> dict:
    """Every balance must equal the sum of its movements (BR-INV-001)."""
    to_sum = select(InventoryMovement.to_location_id.label("location_id"), InventoryMovement.product_id, InventoryMovement.batch_no, InventoryMovement.quantity_base.label("qty")).where(
        InventoryMovement.company_id == actor.company_id, InventoryMovement.to_location_id.is_not(None))
    from_sum = select(InventoryMovement.from_location_id.label("location_id"), InventoryMovement.product_id, InventoryMovement.batch_no, (-InventoryMovement.quantity_base).label("qty")).where(
        InventoryMovement.company_id == actor.company_id, InventoryMovement.from_location_id.is_not(None))
    ledger = to_sum.union_all(from_sum).subquery()
    sums = select(ledger.c.location_id, ledger.c.product_id, ledger.c.batch_no, func.sum(ledger.c.qty).label("total")).group_by(ledger.c.location_id, ledger.c.product_id, ledger.c.batch_no).subquery()
    query = (
        select(InventoryBalance.on_hand, func.coalesce(sums.c.total, 0), Product.sku, WarehouseLocation.code, Warehouse.code)
        .outerjoin(sums, and_(sums.c.location_id == InventoryBalance.location_id, sums.c.product_id == InventoryBalance.product_id, sums.c.batch_no == InventoryBalance.batch_no))
        .join(Product, Product.id == InventoryBalance.product_id).join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .where(InventoryBalance.company_id == actor.company_id)
    )
    checked, differences = 0, []
    for on_hand, total, sku, loc, wh in await db.execute(query):
        checked += 1
        if Decimal(on_hand) != Decimal(total):
            differences.append({"sku": sku, "location": f"{wh}/{loc}", "balance": on_hand, "movement_sum": total})
    orphan = select(sums.c.location_id).outerjoin(InventoryBalance, and_(InventoryBalance.location_id == sums.c.location_id, InventoryBalance.product_id == sums.c.product_id, InventoryBalance.batch_no == sums.c.batch_no)).where(InventoryBalance.location_id.is_(None), sums.c.total != 0)
    if await db.scalar(select(func.count()).select_from(orphan.subquery())):
        differences.append({"sku": "(several)", "location": "(missing balance rows)", "balance": Decimal(0), "movement_sum": Decimal(0)})
    if differences:
        await record_audit(db, actor, "RECONCILIATION_MISMATCH", "INV", "inventory", "reconciliation", after={"differences": len(differences)}, flagged=True)
        await db.commit()
    return {"checked_at": now(), "balances_checked": checked, "differences": differences}


async def batches(db: AsyncSession, actor: Principal, *, within_days: int | None = None) -> list[dict]:
    query = (
        select(InventoryBalance, InventoryBatch, Product, WarehouseLocation, Warehouse)
        .join(InventoryBatch, and_(InventoryBatch.product_id == InventoryBalance.product_id, InventoryBatch.batch_no == InventoryBalance.batch_no))
        .join(Product, Product.id == InventoryBalance.product_id).join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id).join(Warehouse, Warehouse.id == InventoryBalance.warehouse_id)
        .where(InventoryBalance.company_id == actor.company_id, InventoryBalance.on_hand > 0, InventoryBalance.warehouse_id.in_(visible_warehouses(actor)), InventoryBatch.expiry_date.is_not(None))
    )
    today = now().date()
    if within_days is not None:
        query = query.where(InventoryBatch.expiry_date <= today + timedelta(days=within_days))
    rows = []
    for bal, batch, product, loc, wh in await db.execute(query.order_by(InventoryBatch.expiry_date, Product.sku)):
        rows.append({
            "id": f"{batch.id}:{loc.id}", "product_id": product.id, "location_id": loc.id, "batch_no": batch.batch_no, "expiry_date": batch.expiry_date, "quantity": bal.on_hand,
            "receipt_id": batch.receipt_id, "sku": product.sku, "product_name": product.name_en, "location_name": loc.name, "warehouse_name": wh.name,
            "days_to_expiry": (batch.expiry_date - today).days, "value": _cost(actor, (bal.on_hand * product.avg_cost).quantize(MONEY_PLACES, ROUND_HALF_UP)),
        })
    return rows


async def reorder_suggestions(db: AsyncSession, actor: Principal, *, warehouse_id: uuid.UUID | None, branch_id: uuid.UUID | None) -> list[dict]:
    """Products at or below their reorder level, per warehouse, with a suggested purchase quantity (FR-ALR-006)."""
    from app.services.purchasing import on_order as open_po_qty

    warehouses_q = select(Warehouse).where(Warehouse.id.in_(visible_warehouses(actor)))
    if warehouse_id:
        warehouses_q = warehouses_q.where(Warehouse.id == warehouse_id)
    if branch_id:
        actor.assert_branch(branch_id)
        warehouses_q = warehouses_q.where(Warehouse.branch_id == branch_id)
    warehouses = list(await db.scalars(warehouses_q))
    products = list(await db.scalars(select(Product).where(Product.company_id == actor.company_id, Product.deleted_at.is_(None), Product.status == "ACTIVE", Product.type.not_in(NON_STOCK_TYPES))))
    units = {u.id: u.code for u in await db.scalars(select(Unit).where(Unit.company_id == actor.company_id))}
    rows = []
    for wh in warehouses:
        for p in products:
            override = await db.get(ProductWarehouseSetting, (p.id, wh.id))
            reorder = override.reorder_level if override else p.reorder_level
            max_level = override.max_level if override else p.max_level
            reorder_qty = override.reorder_qty if override else p.reorder_qty
            if reorder <= 0:
                continue
            available = Decimal(await db.scalar(
                select(func.coalesce(func.sum(InventoryBalance.on_hand - InventoryBalance.reserved), 0)).join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id)
                .where(InventoryBalance.product_id == p.id, InventoryBalance.warehouse_id == wh.id, WarehouseLocation.location_type.in_(("SELLABLE", "STORAGE", "RECEIVING")))
            ) or 0)
            if available > reorder:
                continue
            on_order = (await open_po_qty(db, [p.id], select(Warehouse.id).where(Warehouse.id == wh.id))).get(p.id, Decimal(0))
            suggested_base = (max_level - available - on_order) if max_level > 0 else reorder_qty
            if suggested_base <= 0:
                continue
            link = await db.scalar(select(ProductSupplier).where(ProductSupplier.product_id == p.id).order_by(ProductSupplier.preferred.desc()).limit(1))
            supplier = await db.get(Supplier, link.supplier_id) if link else None
            conversion = await db.scalar(select(UnitConversion).where(UnitConversion.product_id == p.id, UnitConversion.is_purchase_default.is_(True)))
            factor = conversion.factor if conversion else Decimal(1)
            unit_id = conversion.unit_id if conversion else p.base_unit_id
            if link is not None:  # the supplier's purchase unit wins
                unit_id = link.purchase_unit_id
                factor = await db.scalar(select(UnitConversion.factor).where(UnitConversion.product_id == p.id, UnitConversion.unit_id == unit_id)) or Decimal(1)
            rows.append({
                "product_id": p.id, "sku": p.sku, "product_name": p.name_en, "warehouse_id": wh.id, "warehouse_name": wh.name, "available": available, "on_order": on_order,
                "max_level": max_level, "suggested_base": suggested_base, "purchase_unit_id": unit_id, "purchase_unit_code": units.get(unit_id, ""), "purchase_factor": factor,
                "suggested_qty": Decimal(math.ceil(suggested_base / factor)), "supplier_id": supplier.id if supplier else None, "supplier_name": supplier.name_en if supplier else "",
                "cost": _cost(actor, link.cost if link and link.cost else (p.last_purchase_cost or p.avg_cost)), "lead_time_days": link.lead_time_days if link else 0,
            })
    return rows


async def user_name(db: AsyncSession, user_id: uuid.UUID | None) -> str:
    if user_id is None:
        return "System"
    user = await db.get(User, user_id)
    return user.full_name if user else "Unknown"
