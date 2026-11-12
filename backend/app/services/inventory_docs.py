"""Stock adjustments, transfers and counts (ADJ, TRF, INV counts; Phase 4).

Adjustments: DRAFT -> submit -> SUBMITTED (needs approval) or APPROVED (within the
  creator's adjustment value limit) -> post -> POSTED. Rejected drafts can be fixed and resubmitted.
  The approver needs inventory.adjustment.approve and a high enough limit, and must
  be another user unless reduced separation-of-duties mode is on (BR-INV-003, D-13).
Transfers: REQUESTED -> APPROVED -> DISPATCHED (source -> in-transit) -> PARTIALLY_RECEIVED /
  RECEIVED (in-transit -> destination) -> CLOSED (shortages and excess posted as variances).
  Stock is conserved: what leaves the source is in transit until received or written off (BR-TRF-001).
Counts: COUNTING -> REVIEW -> APPROVED -> POSTED. Variances post as deltas
  (counted minus snapshot), so sales during an unfrozen count are not overwritten (BR-INV-004).
"""

import random
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.models import (
    Category,
    Company,
    InventoryBalance,
    Product,
    StockAdjustment,
    StockAdjustmentLine,
    StockCount,
    StockCountLine,
    StockTransfer,
    StockTransferLine,
    Unit,
    Warehouse,
    WarehouseLocation,
)
from app.schemas import inventory as s
from app.services import alerts, notifications, stock
from app.services.approvals import SodViolation
from app.services.common import next_number, num, record_audit
from app.services.principal import Principal

MONEY = Decimal("0.0001")
OUT_REASON_TYPE = {"DAMAGED": "DAMAGE", "EXPIRED": "EXPIRY", "LOST": "LOSS", "WRITE_OFF": "WRITE_OFF", "INTERNAL_USE": "ADJUSTMENT_OUT", "DATA_CORRECTION": "ADJUSTMENT_OUT"}
NEGATIVE_ONLY = {"DAMAGED", "EXPIRED", "LOST", "WRITE_OFF", "INTERNAL_USE"}


def _now() -> datetime:
    return datetime.now(UTC)


def _event(doc: Any, label: str, actor: Principal, note: str | None = None) -> None:
    doc.timeline = [*(doc.timeline or []), {"at": _now().isoformat(), "label": label, "by": actor.full_name, **({"note": note} if note else {})}]


def _require_status(doc: Any, *allowed: str, action: str) -> None:
    if doc.status not in allowed:
        raise InvalidStateTransition(f"Cannot {action} a {doc.status.lower().replace('_', ' ')} document.")


async def _reduced_sod(db: AsyncSession, actor: Principal) -> bool:
    company = await db.get(Company, actor.company_id)
    return bool(company and (company.settings or {}).get("reduced_sod_mode"))


async def _second_person(db: AsyncSession, actor: Principal, creator_id: uuid.UUID | None, what: str) -> bool:
    """Returns True when the actor approves their own document (allowed only in reduced SoD mode)."""
    if creator_id != actor.user_id:
        return False
    if await _reduced_sod(db, actor):
        return True
    raise SodViolation(f"{what} must be approved by someone other than the person who created it.")


async def _locked(db: AsyncSession, actor: Principal, model: type, doc_id: uuid.UUID, what: str) -> Any:
    doc = await db.scalar(select(model).where(model.id == doc_id, model.company_id == actor.company_id).with_for_update().execution_options(populate_existing=True))
    if doc is None:
        raise NotFound(what)
    return doc


async def _names(db: AsyncSession, model: type, ids: set) -> dict:
    if not ids:
        return {}
    return {r.id: r for r in await db.scalars(select(model).where(model.id.in_(ids)))}


# Adjustments

async def adjustment_view(db: AsyncSession, actor: Principal, adj: StockAdjustment) -> dict:
    lines = list(await db.scalars(select(StockAdjustmentLine).where(StockAdjustmentLine.adjustment_id == adj.id).order_by(StockAdjustmentLine.line_no)))
    products = await _names(db, Product, {line.product_id for line in lines})
    locations = await _names(db, WarehouseLocation, {line.location_id for line in lines})
    units = await _names(db, Unit, {p.base_unit_id for p in products.values()})
    warehouse = await db.get(Warehouse, adj.warehouse_id)
    see = actor.sees_cost
    return {
        "id": adj.id, "adjustment_no": adj.adjustment_no, "warehouse_id": adj.warehouse_id, "warehouse_name": warehouse.name if warehouse else "", "branch_id": adj.branch_id, "status": adj.status,
        "notes": adj.notes, "attachment": adj.attachment_url, "total_value": adj.total_value if see else None, "requires_approval": adj.requires_approval,
        "created_by": await stock.user_name(db, adj.created_by), "created_by_id": adj.created_by, "approved_by": adj.approved_by_name, "created_at": adj.created_at, "posted_at": adj.posted_at,
        "timeline": adj.timeline or [], "version": adj.version,
        "lines": [{
            "id": line.id, "product_id": line.product_id, "sku": products[line.product_id].sku, "product_name": products[line.product_id].name_en, "location_id": line.location_id,
            "location_name": locations[line.location_id].name, "quantity": line.quantity, "unit_code": units[products[line.product_id].base_unit_id].code, "reason": line.reason, "notes": line.notes,
            "unit_cost": line.unit_cost if see else None, "value_impact": line.value_impact if see else None,
        } for line in lines],
    }


async def list_adjustments(db: AsyncSession, actor: Principal, status: str | None, limit: int, offset: int) -> list[dict]:
    query = select(StockAdjustment).where(StockAdjustment.company_id == actor.company_id, StockAdjustment.warehouse_id.in_(stock.visible_warehouses(actor)))
    if status:
        query = query.where(StockAdjustment.status == status)
    return [await adjustment_view(db, actor, a) for a in await db.scalars(query.order_by(StockAdjustment.created_at.desc()).limit(limit).offset(offset))]


async def _adjustment_lines(db: AsyncSession, actor: Principal, adj: StockAdjustment, lines: list[s.AdjustmentLineIn]) -> None:
    if not lines:
        raise ValidationFailed("lines", "Add at least one line.")
    await db.execute(delete(StockAdjustmentLine).where(StockAdjustmentLine.adjustment_id == adj.id))
    total = Decimal(0)
    for i, line in enumerate(lines, start=1):
        product = await stock.stock_product(db, actor, line.product_id)
        location = await stock.scoped_location(db, actor, line.location_id, warehouse_id=adj.warehouse_id)
        if location.location_type == "IN_TRANSIT":
            raise ValidationFailed("lines", "Stock in transit is adjusted through its transfer.")
        stock.check_quantity(product, abs(line.quantity), f"lines.{i}.quantity")
        if line.reason in NEGATIVE_ONLY and line.quantity > 0:
            raise ValidationFailed(f"lines.{i}.quantity", f"{line.reason.replace('_', ' ').title()} lines remove stock, so the quantity must be negative.")
        if line.reason == "FOUND" and line.quantity < 0:
            raise ValidationFailed(f"lines.{i}.quantity", "Found stock is added, so the quantity must be positive.")
        value = (line.quantity * product.avg_cost).quantize(MONEY, ROUND_HALF_UP)
        total += value
        db.add(StockAdjustmentLine(adjustment_id=adj.id, line_no=i, product_id=product.id, location_id=location.id, quantity=line.quantity, reason=line.reason, notes=line.notes,
                                   unit_cost=product.avg_cost, value_impact=value))
    adj.total_value = total
    await db.flush()


async def create_adjustment(db: AsyncSession, actor: Principal, data: s.AdjustmentCreate) -> dict:
    warehouse = await stock.scoped_warehouse(db, actor, data.warehouse_id)
    adj = StockAdjustment(company_id=actor.company_id, adjustment_no=await next_number(db, actor.company_id, "ADJUSTMENT"), warehouse_id=warehouse.id, branch_id=warehouse.branch_id,
                          notes=data.notes, created_by=actor.user_id)
    _event(adj, "Created", actor)
    db.add(adj)
    await db.flush()
    await _adjustment_lines(db, actor, adj, data.lines)
    await record_audit(db, actor, "ADJUSTMENT_CREATED", "ADJ", "stock_adjustment", adj.id, after={"no": adj.adjustment_no, "lines": len(data.lines)}, branch_id=adj.branch_id)
    await db.commit()
    return await adjustment_view(db, actor, adj)


async def update_adjustment(db: AsyncSession, actor: Principal, adj_id: uuid.UUID, data: s.AdjustmentUpdate) -> dict:
    adj = await _locked(db, actor, StockAdjustment, adj_id, "Adjustment")
    await stock.scoped_warehouse(db, actor, adj.warehouse_id)
    _require_status(adj, "DRAFT", "REJECTED", action="edit")
    if data.notes is not None:
        adj.notes = data.notes
    if data.lines is not None:
        await _adjustment_lines(db, actor, adj, data.lines)
    adj.status = "DRAFT"
    _event(adj, "Edited", actor)
    await db.commit()
    return await adjustment_view(db, actor, adj)


async def _approval_amount(db: AsyncSession, adj: StockAdjustment) -> Decimal:
    return Decimal(await db.scalar(select(func.coalesce(func.sum(func.abs(StockAdjustmentLine.value_impact)), 0)).where(StockAdjustmentLine.adjustment_id == adj.id)) or 0)


async def adjustment_action(db: AsyncSession, actor: Principal, adj_id: uuid.UUID, verb: str, body: s.DocumentAction) -> dict:
    adj = await _locked(db, actor, StockAdjustment, adj_id, "Adjustment")
    await stock.scoped_warehouse(db, actor, adj.warehouse_id)
    amount = await _approval_amount(db, adj)
    if verb == "submit":
        actor.require("inventory.adjustment.create")
        _require_status(adj, "DRAFT", "REJECTED", action="submit")
        # Within the creator's own limit no second approval is needed (role limit `adjustment_value`).
        adj.requires_approval = amount > actor.limits.get("adjustment_value", Decimal(0))
        if adj.requires_approval:
            adj.status = "SUBMITTED"
            _event(adj, "Submitted for approval", actor, f"Value {amount.quantize(Decimal('0.01'))} is above your limit")
            notifications.notify(db, actor.company_id, "APPROVAL", "Adjustment awaiting approval", f"{adj.adjustment_no}: value {amount.quantize(Decimal('0.01'))} USD",
                                 link="/inventory/adjustments", permission="inventory.adjustment.approve", branch_id=adj.branch_id)
        else:
            adj.status, adj.approved_by_name = "APPROVED", None
            _event(adj, "Submitted; within limit, no approval needed", actor)
    elif verb == "approve":
        actor.require("inventory.adjustment.approve")
        _require_status(adj, "SUBMITTED", action="approve")
        self_approved = await _second_person(db, actor, adj.created_by, "An adjustment")
        if amount > actor.limits.get("adjustment_value", Decimal(0)):
            raise AppError(f"Your approval limit is {actor.limits.get('adjustment_value')}; this adjustment is worth {amount.quantize(Decimal('0.01'))}.", code="LIMIT_EXCEEDED", status_code=403)
        adj.status, adj.approved_by_id, adj.approved_by_name = "APPROVED", actor.user_id, actor.full_name
        _event(adj, "Approved" + (" (own document, reduced SoD mode)" if self_approved else ""), actor)
    elif verb == "reject":
        actor.require("inventory.adjustment.approve")
        _require_status(adj, "SUBMITTED", action="reject")
        if not body.reason:
            raise ValidationFailed("reason", "Give a reason for rejecting.")
        adj.status = "REJECTED"
        _event(adj, "Rejected", actor, body.reason)
    elif verb == "post":
        actor.require("inventory.adjustment.create", "inventory.adjustment.approve")
        _require_status(adj, "APPROVED", action="post")
        await _post_adjustment(db, actor, adj)
    elif verb == "cancel":
        actor.require("inventory.adjustment.create")
        _require_status(adj, "DRAFT", "REJECTED", "SUBMITTED", "APPROVED", action="cancel")
        adj.status = "CANCELLED"
        _event(adj, "Cancelled", actor, body.reason)
    else:
        raise NotFound("Action")
    await record_audit(db, actor, f"ADJUSTMENT_{verb.upper()}", "ADJ", "stock_adjustment", adj.id, after={"no": adj.adjustment_no, "status": adj.status, "value": str(amount)},
                       branch_id=adj.branch_id, flagged=verb == "approve" and adj.approved_by_id == adj.created_by)
    await db.commit()
    return await adjustment_view(db, actor, adj)


async def _post_adjustment(db: AsyncSession, actor: Principal, adj: StockAdjustment) -> None:
    lines = list(await db.scalars(select(StockAdjustmentLine).where(StockAdjustmentLine.adjustment_id == adj.id).order_by(StockAdjustmentLine.line_no)))
    moves = []
    for line in lines:
        product = await db.get(Product, line.product_id)
        location = await db.get(WarehouseLocation, line.location_id)
        assert product is not None and location is not None
        positive = line.quantity > 0
        moves.append(stock.Move(
            product, abs(line.quantity), "ADJUSTMENT_IN" if positive else OUT_REASON_TYPE[line.reason], "ADJUSTMENT", str(adj.id), str(line.id),
            from_location=None if positive else location, to_location=location if positive else None, source_no=adj.adjustment_no, reason=line.reason, approved_by=adj.approved_by_name,
        ))
    movements = await stock.post(db, actor, moves)
    total = Decimal(0)
    for line, movement in zip(lines, movements, strict=True):
        line.unit_cost = movement.unit_cost
        line.value_impact = (line.quantity * movement.unit_cost).quantize(MONEY, ROUND_HALF_UP)
        total += line.value_impact
    adj.total_value, adj.status, adj.posted_at = total, "POSTED", _now()
    _event(adj, "Posted", actor)
    await alerts.unusual_adjustment(db, actor, adj, lines, total)


# Transfers

async def transfer_view(db: AsyncSession, actor: Principal, t: StockTransfer) -> dict:
    lines = list(await db.scalars(select(StockTransferLine).where(StockTransferLine.transfer_id == t.id).order_by(StockTransferLine.line_no)))
    products = await _names(db, Product, {line.product_id for line in lines})
    units = await _names(db, Unit, {p.base_unit_id for p in products.values()})
    warehouses = await _names(db, Warehouse, {t.source_warehouse_id, t.destination_warehouse_id})
    return {
        "id": t.id, "transfer_no": t.transfer_no, "source_warehouse_id": t.source_warehouse_id, "source_warehouse_name": warehouses[t.source_warehouse_id].name,
        "destination_warehouse_id": t.destination_warehouse_id, "destination_warehouse_name": warehouses[t.destination_warehouse_id].name, "status": t.status, "reason": t.reason,
        "value": t.value if actor.sees_cost else None, "created_by": await stock.user_name(db, t.created_by), "created_by_id": t.created_by, "approved_by": t.approved_by_name,
        "created_at": t.created_at, "dispatched_at": t.dispatched_at, "received_at": t.received_at, "timeline": t.timeline or [], "version": t.version,
        "lines": [{
            "id": line.id, "product_id": line.product_id, "sku": products[line.product_id].sku, "product_name": products[line.product_id].name_en, "unit_code": units[products[line.product_id].base_unit_id].code,
            "quantity_requested": line.quantity_requested, "quantity_dispatched": line.quantity_dispatched, "quantity_received": line.quantity_received,
            "quantity_short": line.quantity_short, "quantity_damaged": line.quantity_damaged, "quantity_excess": line.quantity_excess,
        } for line in lines],
    }


def _transfer_scope(actor: Principal):
    visible = stock.visible_warehouses(actor)
    return StockTransfer.source_warehouse_id.in_(visible) | StockTransfer.destination_warehouse_id.in_(visible)


async def list_transfers(db: AsyncSession, actor: Principal, status: str | None, limit: int, offset: int) -> list[dict]:
    query = select(StockTransfer).where(StockTransfer.company_id == actor.company_id, _transfer_scope(actor))
    if status:
        query = query.where(StockTransfer.status == status)
    return [await transfer_view(db, actor, t) for t in await db.scalars(query.order_by(StockTransfer.created_at.desc()).limit(limit).offset(offset))]


async def create_transfer(db: AsyncSession, actor: Principal, data: s.TransferCreate) -> dict:
    source = await stock.scoped_warehouse(db, actor, data.source_warehouse_id)
    destination = await db.scalar(select(Warehouse).where(Warehouse.id == data.destination_warehouse_id, Warehouse.company_id == actor.company_id, Warehouse.is_system.is_(False)))
    if destination is None:
        raise NotFound("Destination warehouse")
    if destination.id == source.id:
        raise ValidationFailed("destination_warehouse_id", "Source and destination must differ.")
    if destination.status != "ACTIVE" or source.status != "ACTIVE":
        raise ValidationFailed("destination_warehouse_id", "Both warehouses must be active.")
    if not data.lines:
        raise ValidationFailed("lines", "Add at least one line.")
    transfer = StockTransfer(company_id=actor.company_id, transfer_no=await next_number(db, actor.company_id, "TRANSFER"), source_warehouse_id=source.id,
                             destination_warehouse_id=destination.id, reason=data.reason, created_by=actor.user_id)
    _event(transfer, "Requested", actor, data.reason)
    db.add(transfer)
    await db.flush()
    value = Decimal(0)
    seen = set()
    for i, line in enumerate(data.lines, start=1):
        product = await stock.stock_product(db, actor, line.product_id)
        if product.id in seen:
            raise ValidationFailed("lines", f"{product.sku} is listed twice.")
        seen.add(product.id)
        stock.check_quantity(product, line.quantity, f"lines.{i}.quantity")
        value += line.quantity * product.avg_cost
        db.add(StockTransferLine(transfer_id=transfer.id, line_no=i, product_id=product.id, quantity_requested=line.quantity))
    transfer.value = value.quantize(MONEY, ROUND_HALF_UP)
    notifications.notify(db, actor.company_id, "TRANSFER", "Transfer requested", f"{transfer.transfer_no}: {source.name} to {destination.name}", link="/inventory/transfers",
                         permission="inventory.transfer.approve", branch_id=source.branch_id)
    await record_audit(db, actor, "TRANSFER_REQUESTED", "TRF", "stock_transfer", transfer.id, after={"no": transfer.transfer_no, "from": source.code, "to": destination.code}, branch_id=source.branch_id)
    await db.commit()
    return await transfer_view(db, actor, transfer)


async def _pick_locations(db: AsyncSession, warehouse_id: uuid.UUID, product_id: uuid.UUID) -> list[tuple[WarehouseLocation, InventoryBalance]]:
    """Source stock for a dispatch: storage first, then sellable, then receiving; never damaged, expired, quarantine or returns."""
    order = {"STORAGE": 0, "SELLABLE": 1, "RECEIVING": 2}
    rows = await db.execute(
        select(WarehouseLocation, InventoryBalance).join(InventoryBalance, InventoryBalance.location_id == WarehouseLocation.id)
        .where(WarehouseLocation.warehouse_id == warehouse_id, InventoryBalance.product_id == product_id, WarehouseLocation.location_type.in_(tuple(order)),
               WarehouseLocation.status == "ACTIVE", InventoryBalance.on_hand > InventoryBalance.reserved)
    )
    return sorted(rows.all(), key=lambda r: (order[r[0].location_type], r[0].code, r[1].batch_no))


async def _receiving_location(db: AsyncSession, warehouse_id: uuid.UUID, kind: str) -> WarehouseLocation:
    preference = ["DAMAGED"] if kind == "DAMAGED" else ["RECEIVING", "STORAGE", "SELLABLE"]
    for location_type in preference:
        location = await db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse_id, WarehouseLocation.location_type == location_type, WarehouseLocation.status == "ACTIVE").order_by(WarehouseLocation.code).limit(1))
        if location:
            return location
    raise ValidationFailed("lines", f"The destination warehouse has no active {' or '.join(preference).lower()} location.")


async def _from_transit(db: AsyncSession, transit: WarehouseLocation, product_id: uuid.UUID, qty: Decimal, taken: dict[str, Decimal]) -> list[tuple[str, Decimal]]:
    """Splits a quantity leaving in-transit across the batches held there (batch numbers travel with the stock)."""
    rows = await db.execute(select(InventoryBalance.batch_no, InventoryBalance.on_hand).where(InventoryBalance.location_id == transit.id, InventoryBalance.product_id == product_id, InventoryBalance.on_hand > 0).order_by(InventoryBalance.batch_no))
    parts, remaining = [], qty
    for batch_no, on_hand in rows:
        free = on_hand - taken.get(batch_no, Decimal(0))
        take = min(remaining, free)
        if take > 0:
            parts.append((batch_no, take))
            taken[batch_no] = taken.get(batch_no, Decimal(0)) + take
            remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        parts.append(("", remaining))  # lets the ledger report the shortfall with a clear error
    return parts


async def transfer_action(db: AsyncSession, actor: Principal, transfer_id: uuid.UUID, verb: str, body: s.TransferAction) -> dict:
    t = await _locked(db, actor, StockTransfer, transfer_id, "Transfer")
    visible = set(await db.scalars(stock.visible_warehouses(actor)))
    if t.source_warehouse_id not in visible and t.destination_warehouse_id not in visible:
        raise NotFound("Transfer")
    lines = {line.id: line for line in await db.scalars(select(StockTransferLine).where(StockTransferLine.transfer_id == t.id).with_for_update())}
    source = await db.get(Warehouse, t.source_warehouse_id)
    dest = await db.get(Warehouse, t.destination_warehouse_id)
    assert source is not None and dest is not None
    transit = await stock.in_transit_location(db, actor.company_id)
    flagged = False

    if verb == "approve":
        actor.require("inventory.transfer.approve")
        _require_status(t, "REQUESTED", action="approve")
        company = await db.get(Company, actor.company_id)
        threshold = Decimal(str((company.settings or {}).get("transfer_approval_value", "500"))) if company else Decimal("500")
        if t.created_by == actor.user_id and t.value > threshold:
            flagged = await _second_person(db, actor, t.created_by, "A transfer above the approval value")
        t.status, t.approved_by_id, t.approved_by_name = "APPROVED", actor.user_id, actor.full_name
        _event(t, "Approved", actor)
    elif verb == "cancel":
        actor.require("inventory.transfer.create", "inventory.transfer.approve")
        _require_status(t, "REQUESTED", "APPROVED", action="cancel")
        t.status = "CANCELLED"
        _event(t, "Cancelled", actor, body.reason)
    elif verb == "dispatch":
        actor.require("inventory.transfer.create")
        _require_status(t, "APPROVED", action="dispatch")
        if t.source_warehouse_id not in visible:
            raise Forbidden("Only staff at the source warehouse can dispatch.")
        quantities = {d.line_id: d.quantity for d in body.lines} if isinstance(body, s.DispatchAction) and body.lines else {lid: line.quantity_requested for lid, line in lines.items()}
        moves, value = [], Decimal(0)
        for line_id, qty in quantities.items():
            line = lines.get(line_id)
            if line is None:
                raise ValidationFailed("lines", "Unknown transfer line.")
            if qty < 0 or qty > line.quantity_requested:
                raise ValidationFailed("lines", "Dispatch quantity must be between zero and the requested quantity.")
            if qty == 0:
                continue
            product = await db.get(Product, line.product_id)
            assert product is not None
            stock.check_quantity(product, qty)
            remaining = qty
            for location, balance in await _pick_locations(db, source.id, product.id):
                take = min(remaining, balance.on_hand - balance.reserved)
                if take <= 0:
                    continue
                moves.append(stock.Move(product, take, "TRANSFER_OUT", "TRANSFER", str(t.id), f"{line.id}:{location.id}:{balance.batch_no}", from_location=location, to_location=transit,
                                        source_no=t.transfer_no, batch_no=balance.batch_no, approved_by=t.approved_by_name))
                remaining -= take
                if remaining == 0:
                    break
            if remaining > 0:
                raise stock.InsufficientStock(f"Not enough {product.sku} in {source.name} to dispatch {num(qty)}.",
                                              details=[{"product_id": str(product.id), "sku": product.sku, "requested": str(qty), "short": str(remaining)}])
            line.quantity_dispatched = qty
            line.unit_cost = product.avg_cost
            value += qty * product.avg_cost
        if not moves:
            raise ValidationFailed("lines", "Dispatch at least one item.")
        await stock.post(db, actor, moves)
        t.value = value.quantize(MONEY, ROUND_HALF_UP)
        t.status, t.dispatched_at = "DISPATCHED", _now()
        _event(t, "Dispatched", actor)
    elif verb == "receive":
        actor.require("inventory.transfer.create")
        _require_status(t, "DISPATCHED", "PARTIALLY_RECEIVED", action="receive")
        if t.destination_warehouse_id not in visible:
            raise Forbidden("Only staff at the destination warehouse can receive.")
        if not isinstance(body, s.ReceiveAction) or not body.lines:
            raise ValidationFailed("lines", "Enter what was received.")
        good_location = await _receiving_location(db, dest.id, "GOOD")
        moves = []
        for r in body.lines:
            line = lines.get(r.line_id)
            if line is None:
                raise ValidationFailed("lines", "Unknown transfer line.")
            outstanding = line.quantity_dispatched - line.quantity_received - line.quantity_short - line.quantity_damaged
            if r.received + r.damaged + r.short > outstanding:
                raise ValidationFailed("lines", f"Received, damaged and short together exceed the {num(outstanding)} outstanding.")
            product = await db.get(Product, line.product_id)
            assert product is not None
            taken: dict[str, Decimal] = {}
            for qty, kind in ((r.received, "GOOD"), (r.damaged, "DAMAGED")):
                if qty > 0:
                    stock.check_quantity(product, qty)
                    target = good_location if kind == "GOOD" else await _receiving_location(db, dest.id, "DAMAGED")
                    seq = len(t.timeline or [])
                    for batch_no, part in await _from_transit(db, transit, product.id, qty, taken):
                        moves.append(stock.Move(product, part, "TRANSFER_RECEIVE", "TRANSFER", str(t.id), f"{line.id}:{kind}:{seq}:{batch_no}", from_location=transit, to_location=target,
                                                source_no=t.transfer_no, batch_no=batch_no, reason="DAMAGED_IN_TRANSIT" if kind == "DAMAGED" else None))
            line.quantity_received += r.received
            line.quantity_damaged += r.damaged
            line.quantity_short += r.short
            line.quantity_excess += r.excess
        await stock.post(db, actor, moves)
        open_qty = sum((ln.quantity_dispatched - ln.quantity_received - ln.quantity_short - ln.quantity_damaged for ln in lines.values()), Decimal(0))
        t.status = "RECEIVED" if open_qty == 0 else "PARTIALLY_RECEIVED"
        t.received_at = _now() if t.status == "RECEIVED" else t.received_at
        _event(t, "Received" if t.status == "RECEIVED" else "Partially received", actor)
    elif verb == "close":
        actor.require("inventory.transfer.approve")
        _require_status(t, "RECEIVED", action="close")
        moves = []
        good_location = None
        for line in lines.values():
            product = await db.get(Product, line.product_id)
            assert product is not None
            if line.quantity_short > 0:
                for batch_no, part in await _from_transit(db, transit, product.id, line.quantity_short, {}):
                    moves.append(stock.Move(product, part, "TRANSFER_VARIANCE", "TRANSFER", str(t.id), f"{line.id}:SHORT:{batch_no}", from_location=transit, source_no=t.transfer_no,
                                            batch_no=batch_no, reason="SHORT", ledger_warehouse_id=dest.id, approved_by=actor.full_name))
            if line.quantity_excess > 0:
                good_location = good_location or await _receiving_location(db, dest.id, "GOOD")
                moves.append(stock.Move(product, line.quantity_excess, "TRANSFER_VARIANCE", "TRANSFER", str(t.id), f"{line.id}:EXCESS", to_location=good_location, source_no=t.transfer_no,
                                        reason="EXCESS", approved_by=actor.full_name))
        await stock.post(db, actor, moves)
        t.status, t.closed_at = "CLOSED", _now()
        _event(t, "Closed and reconciled", actor)
        flagged = bool(moves)
    else:
        raise NotFound("Action")
    await record_audit(db, actor, f"TRANSFER_{verb.upper()}", "TRF", "stock_transfer", t.id, after={"no": t.transfer_no, "status": t.status}, branch_id=source.branch_id, flagged=flagged)
    await db.commit()
    return await transfer_view(db, actor, t)


# Counts

def _variance(line: StockCountLine) -> Decimal | None:
    return None if line.counted_qty is None else line.counted_qty - line.snapshot_qty


async def count_view(db: AsyncSession, actor: Principal, c: StockCount) -> dict:
    lines = list(await db.scalars(select(StockCountLine).where(StockCountLine.count_id == c.id)))
    products = await _names(db, Product, {line.product_id for line in lines})
    locations = await _names(db, WarehouseLocation, {line.location_id for line in lines})
    units = await _names(db, Unit, {p.base_unit_id for p in products.values()})
    warehouse = await db.get(Warehouse, c.warehouse_id)
    hide = c.blind and c.status == "COUNTING"  # blind counts reveal the system quantity only after submission
    lines.sort(key=lambda line: (locations[line.location_id].code, products[line.product_id].sku, line.batch_no))
    rows = []
    for line in lines:
        product = products[line.product_id]
        variance = None if hide else _variance(line)
        rows.append({
            "id": line.id, "location_id": line.location_id, "location_name": locations[line.location_id].name, "product_id": line.product_id, "sku": product.sku, "product_name": product.name_en,
            "unit_code": units[product.base_unit_id].code, "batch_no": line.batch_no or None, "snapshot_qty": None if hide else line.snapshot_qty, "counted_qty": line.counted_qty,
            "counted_at": line.counted_at, "counted_by": line.counted_by, "variance": variance,
            "value_variance": (variance * (line.unit_cost or product.avg_cost)).quantize(MONEY, ROUND_HALF_UP) if variance is not None and actor.sees_cost else None,
            "reason": line.reason, "recount_required": line.recount_required,
        })
    return {
        "id": c.id, "count_no": c.count_no, "warehouse_id": c.warehouse_id, "warehouse_name": warehouse.name if warehouse else "", "scope": c.scope, "scope_label": c.scope_label,
        "freeze": c.freeze, "blind": c.blind, "status": c.status, "lines": rows, "created_by": await stock.user_name(db, c.created_by), "created_by_id": c.created_by,
        "approved_by": c.approved_by_name, "created_at": c.created_at, "posted_at": c.posted_at, "timeline": c.timeline or [], "version": c.version,
    }


async def list_counts(db: AsyncSession, actor: Principal, status: str | None, limit: int, offset: int) -> list[dict]:
    query = select(StockCount).where(StockCount.company_id == actor.company_id, StockCount.warehouse_id.in_(stock.visible_warehouses(actor)))
    if status:
        query = query.where(StockCount.status == status)
    return [await count_view(db, actor, c) for c in await db.scalars(query.order_by(StockCount.created_at.desc()).limit(limit).offset(offset))]


async def create_count(db: AsyncSession, actor: Principal, data: s.CountCreate) -> dict:
    warehouse = await stock.scoped_warehouse(db, actor, data.warehouse_id)
    query = (
        select(InventoryBalance).join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id).join(Product, Product.id == InventoryBalance.product_id)
        .where(InventoryBalance.warehouse_id == warehouse.id, WarehouseLocation.location_type != "IN_TRANSIT", Product.deleted_at.is_(None))
    )
    label = "Full count"
    category_id = location_id = None
    if data.scope == "CYCLE_CATEGORY":
        if not data.category_id:
            raise ValidationFailed("category_id", "Select a category.")
        category = await db.scalar(select(Category).where(Category.id == data.category_id, Category.company_id == actor.company_id))
        if category is None:
            raise NotFound("Category")
        query, label, category_id = query.where(Product.category_id == category.id), f"Category: {category.name_en}", category.id
    elif data.scope == "CYCLE_LOCATION":
        if not data.location_id:
            raise ValidationFailed("location_id", "Select a location.")
        location = await stock.scoped_location(db, actor, data.location_id, warehouse_id=warehouse.id)
        query, label, location_id = query.where(InventoryBalance.location_id == location.id), f"Location: {location.name}", location.id
    balances = list(await db.scalars(query))
    if data.scope == "CYCLE_RANDOM":
        balances = random.SystemRandom().sample(balances, min(data.sample_size, len(balances)))
        label = f"Random sample of {len(balances)}"
    if not balances:
        raise ValidationFailed("scope", "Nothing to count: no stock records match this scope.")
    count = StockCount(company_id=actor.company_id, count_no=await next_number(db, actor.company_id, "COUNT"), warehouse_id=warehouse.id, scope=data.scope, scope_label=label,
                       category_id=category_id, location_id=location_id, freeze=data.freeze, blind=data.blind, status="COUNTING", created_by=actor.user_id)
    _event(count, "Created" + (" (stock frozen)" if data.freeze else ""), actor, label)
    db.add(count)
    await db.flush()
    db.add_all(StockCountLine(count_id=count.id, location_id=b.location_id, product_id=b.product_id, batch_no=b.batch_no, snapshot_qty=b.on_hand) for b in balances)
    await record_audit(db, actor, "COUNT_CREATED", "INV", "stock_count", count.id, after={"no": count.count_no, "scope": label, "lines": len(balances), "freeze": data.freeze}, branch_id=warehouse.branch_id)
    await db.commit()
    return await count_view(db, actor, count)


async def set_count_lines(db: AsyncSession, actor: Principal, count_id: uuid.UUID, data: s.CountLinesUpdate) -> dict:
    count = await _locked(db, actor, StockCount, count_id, "Stock count")
    await stock.scoped_warehouse(db, actor, count.warehouse_id)
    _require_status(count, "COUNTING", "REVIEW", action="enter quantities for")
    lines = {line.id: line for line in await db.scalars(select(StockCountLine).where(StockCountLine.count_id == count.id))}
    for entry in data.lines:
        line = lines.get(entry.line_id)
        if line is None:
            raise ValidationFailed("lines", "Unknown count line.")
        if count.status == "REVIEW" and not line.recount_required:
            raise InvalidStateTransition("Only lines marked for recount can change during review.")
        if "counted_qty" in entry.model_fields_set:
            if entry.counted_qty is not None:
                product = await db.get(Product, line.product_id)
                assert product is not None
                stock.check_quantity(product, entry.counted_qty, "counted_qty")
            line.counted_qty, line.counted_at, line.counted_by = entry.counted_qty, _now() if entry.counted_qty is not None else None, actor.full_name if entry.counted_qty is not None else None
            if count.status == "REVIEW" and entry.counted_qty is not None:
                line.recount_required = False
        if entry.reason is not None:
            line.reason = entry.reason
    await db.commit()
    return await count_view(db, actor, count)


async def count_action(db: AsyncSession, actor: Principal, count_id: uuid.UUID, verb: str, body: s.CountAction) -> dict:
    count = await _locked(db, actor, StockCount, count_id, "Stock count")
    warehouse = await stock.scoped_warehouse(db, actor, count.warehouse_id)
    lines = list(await db.scalars(select(StockCountLine).where(StockCountLine.count_id == count.id).with_for_update()))
    flagged = False
    if verb == "submit":
        actor.require("inventory.count.create")
        _require_status(count, "COUNTING", action="submit")
        missing = [line for line in lines if line.counted_qty is None]
        if missing:
            raise ValidationFailed("lines", f"{len(missing)} line(s) have no counted quantity.")
        company = await db.get(Company, actor.company_id)
        threshold = Decimal(str((company.settings or {}).get("count_variance_recount_qty", "5"))) if company else Decimal("5")
        for line in lines:
            variance = _variance(line)
            line.recount_required = variance is not None and abs(variance) >= threshold
            if line.recount_required:
                line.counted_qty, line.counted_at, line.counted_by = None, None, None
        recounts = sum(line.recount_required for line in lines)
        count.status = "REVIEW"
        _event(count, "Submitted" + (f"; {recounts} line(s) need a recount" if recounts else ""), actor)
    elif verb == "recount":
        actor.require("inventory.count.create")
        _require_status(count, "REVIEW", action="request a recount for")
        ids = set(body.line_ids or [])
        if not ids:
            raise ValidationFailed("line_ids", "Select lines to recount.")
        for line in lines:
            if line.id in ids:
                line.recount_required, line.counted_qty, line.counted_at, line.counted_by = True, None, None, None
        _event(count, f"Recount requested for {len(ids)} line(s)", actor)
    elif verb == "approve":
        actor.require("inventory.count.approve")
        _require_status(count, "REVIEW", action="approve")
        if any(line.recount_required or line.counted_qty is None for line in lines):
            raise ValidationFailed("lines", "Finish the recounts before approving.")
        flagged = await _second_person(db, actor, count.created_by, "A stock count")
        count.status, count.approved_by_id, count.approved_by_name = "APPROVED", actor.user_id, actor.full_name
        _event(count, "Approved", actor)
    elif verb == "post":
        actor.require("inventory.count.approve")
        _require_status(count, "APPROVED", action="post")
        moves = []
        for line in lines:
            variance = _variance(line)
            if not variance:
                continue
            product = await db.get(Product, line.product_id)
            location = await db.get(WarehouseLocation, line.location_id)
            assert product is not None and location is not None
            moves.append(stock.Move(product, abs(variance), "COUNT_VARIANCE", "COUNT", str(count.id), str(line.id), from_location=location if variance < 0 else None,
                                    to_location=location if variance > 0 else None, source_no=count.count_no, reason=line.reason or ("COUNT_GAIN" if variance > 0 else "COUNT_LOSS"),
                                    batch_no=line.batch_no, approved_by=count.approved_by_name, ignore_freeze_for_count=count.id))
        movements = await stock.post(db, actor, moves)
        by_line = {m.source_line_id: m for m in movements}
        for line in lines:
            if str(line.id) in by_line:
                line.unit_cost = by_line[str(line.id)].unit_cost
        count.status, count.posted_at = "POSTED", _now()
        _event(count, f"Posted {len(moves)} variance movement(s)", actor)
        flagged = bool(moves)
    elif verb == "cancel":
        actor.require("inventory.count.create", "inventory.count.approve")
        _require_status(count, "OPEN", "COUNTING", "REVIEW", "APPROVED", action="cancel")
        count.status = "CANCELLED"
        _event(count, "Cancelled; no stock changed", actor, body.reason)
    else:
        raise NotFound("Action")
    await record_audit(db, actor, f"COUNT_{verb.upper()}", "INV", "stock_count", count.id, after={"no": count.count_no, "status": count.status}, branch_id=warehouse.branch_id, flagged=flagged)
    await db.commit()
    return await count_view(db, actor, count)
