"""Inventory alerts (ALR; Phase 4).

`evaluate()` raises one open alert per condition (a partial unique index enforces
this) and resolves open alerts whose condition has cleared. Snoozed alerts are left
alone until their snooze ends. Unusual adjustments are raised when an adjustment posts.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFound, ValidationFailed
from app.models import (
    Company,
    InventoryAlert,
    InventoryBalance,
    InventoryBatch,
    InventoryMovement,
    Product,
    ProductWarehouseSetting,
    StockAdjustment,
    StockAdjustmentLine,
    Warehouse,
    WarehouseLocation,
)
from app.services.common import record_audit
from app.services.notifications import notify
from app.services.principal import Principal
from app.services.stock import visible_warehouses

STOCK_TYPES = ("LOW_STOCK", "OUT_OF_STOCK", "OVERSTOCK", "NEGATIVE_STOCK", "EXPIRING", "EXPIRED", "SLOW_MOVING")


def _now() -> datetime:
    return datetime.now(UTC)


async def _settings(db: AsyncSession, company_id: uuid.UUID) -> dict:
    company = await db.get(Company, company_id)
    return (company.settings or {}) if company else {}


async def _raise(db: AsyncSession, company_id: uuid.UUID, kind: str, product_id: uuid.UUID, warehouse: Warehouse | None, message: str, subject: str = "") -> bool:
    inserted = await _insert_alert(db, company_id, kind, product_id, warehouse, message, subject)
    if inserted and kind in ("OUT_OF_STOCK", "NEGATIVE_STOCK", "EXPIRED", "LOW_STOCK", "UNUSUAL_ADJUSTMENT"):
        notify(db, company_id, "STOCK_ALERT", kind.replace("_", " ").title(), message, link="/inventory/alerts", permission="inventory.alert.view",
               branch_id=warehouse.branch_id if warehouse else None)
    return inserted


async def _insert_alert(db: AsyncSession, company_id: uuid.UUID, kind: str, product_id: uuid.UUID, warehouse: Warehouse | None, message: str, subject: str) -> bool:
    inserted = await db.scalar(
        insert(InventoryAlert).values(id=uuid.uuid4(), company_id=company_id, type=kind, product_id=product_id, warehouse_id=warehouse.id if warehouse else None,
                                      branch_id=warehouse.branch_id if warehouse else None, subject=subject, message=message, status="OPEN")
        .on_conflict_do_nothing().returning(InventoryAlert.id)
    )
    return inserted is not None


async def unusual_adjustment(db: AsyncSession, actor: Principal, adj: StockAdjustment, lines: list[StockAdjustmentLine], total: Decimal) -> None:
    threshold = Decimal(str((await _settings(db, actor.company_id)).get("adjustment_alert_value", "100")))
    impact = sum((abs(line.value_impact) for line in lines), Decimal(0))
    if impact < threshold or not lines:
        return
    warehouse = await db.get(Warehouse, adj.warehouse_id)
    biggest = max(lines, key=lambda line: abs(line.value_impact))
    await _raise(db, actor.company_id, "UNUSUAL_ADJUSTMENT", biggest.product_id, warehouse, f"{adj.adjustment_no} changed stock value by {total.quantize(Decimal('0.01'))} (alert threshold {threshold}).", subject=adj.adjustment_no)


async def evaluate(db: AsyncSession, actor: Principal) -> dict:
    settings = await _settings(db, actor.company_id)
    warning_days = int(settings.get("expiry_warning_days", 30))
    slow_days = int(settings.get("slow_moving_days", 60))
    today = _now().date()
    active: set[tuple[str, uuid.UUID, uuid.UUID | None, str]] = set()
    raised = 0

    warehouses = {w.id: w for w in await db.scalars(select(Warehouse).where(Warehouse.company_id == actor.company_id, Warehouse.is_system.is_(False), Warehouse.status == "ACTIVE"))}
    products = {p.id: p for p in await db.scalars(select(Product).where(Product.company_id == actor.company_id, Product.deleted_at.is_(None), Product.status == "ACTIVE", Product.type.in_(("STANDARD", "WEIGHED"))))}
    totals = await db.execute(
        select(InventoryBalance.product_id, InventoryBalance.warehouse_id, func.sum(InventoryBalance.on_hand), func.min(InventoryBalance.on_hand))
        .where(InventoryBalance.company_id == actor.company_id).group_by(InventoryBalance.product_id, InventoryBalance.warehouse_id)
    )
    for product_id, warehouse_id, on_hand, lowest in totals:
        product, warehouse = products.get(product_id), warehouses.get(warehouse_id)
        if product is None or warehouse is None:
            continue
        override = await db.get(ProductWarehouseSetting, (product_id, warehouse_id))
        reorder = override.reorder_level if override else product.reorder_level
        max_level = override.max_level if override else product.max_level
        checks = [
            ("NEGATIVE_STOCK", lowest < 0, f"{product.sku} is negative in {warehouse.name}."),
            ("OUT_OF_STOCK", on_hand <= 0, f"{product.sku} is out of stock in {warehouse.name}."),
            ("LOW_STOCK", 0 < on_hand <= reorder and reorder > 0, f"{product.sku} is at {on_hand.normalize()} in {warehouse.name}, at or below the reorder level {reorder.normalize()}."),
            ("OVERSTOCK", max_level > 0 and on_hand > max_level, f"{product.sku} is at {on_hand.normalize()} in {warehouse.name}, above the maximum {max_level.normalize()}."),
        ]
        for kind, condition, message in checks:
            if condition:
                active.add((kind, product_id, warehouse_id, ""))
                raised += await _raise(db, actor.company_id, kind, product_id, warehouse, message)
        if on_hand > 0:
            last_sale = await db.scalar(select(func.max(InventoryMovement.posted_at)).where(InventoryMovement.product_id == product_id, InventoryMovement.warehouse_id == warehouse_id, InventoryMovement.movement_type == "SALE"))
            first_in = await db.scalar(select(func.min(InventoryMovement.posted_at)).where(InventoryMovement.product_id == product_id, InventoryMovement.warehouse_id == warehouse_id))
            reference = last_sale or first_in
            if reference is not None and reference < _now() - timedelta(days=slow_days):
                active.add(("SLOW_MOVING", product_id, warehouse_id, ""))
                raised += await _raise(db, actor.company_id, "SLOW_MOVING", product_id, warehouse, f"{product.sku} has not sold in {warehouse.name} for over {slow_days} days.")

    expiring = await db.execute(
        select(InventoryBalance.product_id, InventoryBalance.warehouse_id, InventoryBatch.batch_no, InventoryBatch.expiry_date, func.sum(InventoryBalance.on_hand))
        .join(InventoryBatch, (InventoryBatch.product_id == InventoryBalance.product_id) & (InventoryBatch.batch_no == InventoryBalance.batch_no))
        .join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id)
        .where(InventoryBalance.company_id == actor.company_id, InventoryBalance.on_hand > 0, InventoryBatch.expiry_date <= today + timedelta(days=warning_days), WarehouseLocation.location_type != "EXPIRED")
        .group_by(InventoryBalance.product_id, InventoryBalance.warehouse_id, InventoryBatch.batch_no, InventoryBatch.expiry_date)
    )
    for product_id, warehouse_id, batch_no, expiry, qty in expiring:
        product, warehouse = products.get(product_id), warehouses.get(warehouse_id)
        if product is None or warehouse is None:
            continue
        kind = "EXPIRED" if expiry < today else "EXPIRING"
        message = f"Batch {batch_no} of {product.sku} ({qty.normalize()}) in {warehouse.name} {'expired' if kind == 'EXPIRED' else 'expires'} on {expiry:%d/%m/%Y}."
        active.add((kind, product_id, warehouse_id, batch_no))
        raised += await _raise(db, actor.company_id, kind, product_id, warehouse, message, subject=batch_no)

    resolved = 0
    open_alerts = await db.scalars(select(InventoryAlert).where(InventoryAlert.company_id == actor.company_id, InventoryAlert.type.in_(STOCK_TYPES), InventoryAlert.status.in_(("OPEN", "ACKNOWLEDGED"))))
    for alert in open_alerts:
        if (alert.type, alert.product_id, alert.warehouse_id, alert.subject) not in active:
            alert.status, alert.note = "RESOLVED", "Condition cleared"
            resolved += 1
    for alert in await db.scalars(select(InventoryAlert).where(InventoryAlert.company_id == actor.company_id, InventoryAlert.status == "SNOOZED", InventoryAlert.snoozed_until <= _now())):
        alert.status = "OPEN"
    await db.commit()
    return {"raised": raised, "resolved": resolved}


async def alert_view(db: AsyncSession, alert: InventoryAlert) -> dict:
    product = await db.get(Product, alert.product_id)
    warehouse = await db.get(Warehouse, alert.warehouse_id) if alert.warehouse_id else None
    return {
        **{f: getattr(alert, f) for f in ("id", "type", "product_id", "warehouse_id", "branch_id", "message", "status", "assigned_to", "snoozed_until", "note", "created_at", "updated_at")},
        "sku": product.sku if product else "", "product_name": product.name_en if product else "", "warehouse_name": warehouse.name if warehouse else "",
    }


async def list_alerts(db: AsyncSession, actor: Principal, status: str | None, include_resolved: bool) -> list[dict]:
    query = select(InventoryAlert).where(InventoryAlert.company_id == actor.company_id, InventoryAlert.warehouse_id.in_(visible_warehouses(actor)) | InventoryAlert.warehouse_id.is_(None))
    if status:
        query = query.where(InventoryAlert.status == status)
    elif not include_resolved:
        query = query.where(InventoryAlert.status != "RESOLVED")
    return [await alert_view(db, a) for a in await db.scalars(query.order_by(InventoryAlert.created_at.desc()).limit(500))]


async def act(db: AsyncSession, actor: Principal, alert_id: uuid.UUID, action: str, note: str | None, assigned_to: str | None, days: int | None) -> dict:
    alert = await db.scalar(select(InventoryAlert).where(InventoryAlert.id == alert_id, InventoryAlert.company_id == actor.company_id,
                                                         InventoryAlert.warehouse_id.in_(visible_warehouses(actor)) | InventoryAlert.warehouse_id.is_(None)).with_for_update())
    if alert is None:
        raise NotFound("Alert")
    if action == "ACKNOWLEDGE":
        alert.status = "ACKNOWLEDGED"
    elif action == "RESOLVE":
        alert.status = "RESOLVED"
    elif action == "SNOOZE":
        if not days or not 1 <= days <= 30:
            raise ValidationFailed("days", "Snooze for 1 to 30 days.")
        alert.status, alert.snoozed_until = "SNOOZED", _now() + timedelta(days=days)
    elif action == "ASSIGN":
        if not assigned_to:
            raise ValidationFailed("assigned_to", "Choose who to assign it to.")
        alert.assigned_to = assigned_to[:200]
    if note:
        alert.note = note
    await record_audit(db, actor, f"ALERT_{action}", "ALR", "inventory_alert", alert.id, after={"type": alert.type, "status": alert.status, "note": note})
    await db.commit()
    await db.refresh(alert)
    return await alert_view(db, alert)
