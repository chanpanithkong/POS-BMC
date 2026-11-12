"""Suppliers, purchase orders, goods receipts, supplier invoices and purchase returns (PUR, GRN; Phase 6).

Purchase orders: DRAFT -> submit -> PENDING_APPROVAL -> approve -> APPROVED -> send -> SENT
  -> PARTIALLY_RECEIVED / RECEIVED; SHORT_CLOSED or CANCELLED. The approver must hold
  purchasing.order.approve with a high enough PO limit and must not be the creator (BR-PUR-001).
  Editing an approved order sends it back for approval.
Goods receipts: posted exactly once (BR-GRN-001). A receipt without a PO needs the receiving-exception
  permission and a reason, and is flagged (BR-GRN-003). Over-delivery beyond tolerance, wrong items and
  receipts without a PO need approval by another user before posting (BR-GRN-002). Damaged quantities go
  to a DAMAGED location; rejected quantities never enter stock. Posting updates weighted-average cost.
Supplier invoices: unique per supplier after normalising the number (BR-PUR-003), matched against
  what was received on the PO.
"""

import re
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.models import (
    Company,
    GoodsReceipt,
    GoodsReceiptLine,
    Product,
    ProductSupplier,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseReturn,
    PurchaseReturnLine,
    Supplier,
    SupplierInvoice,
    SupplierPayment,
    TaxCode,
    Unit,
    Warehouse,
    WarehouseLocation,
)
from app.schemas import purchasing as s
from app.services import pricing, stock
from app.services.approvals import LimitExceeded, SodViolation
from app.services.common import apply_changes, ensure_unique, next_number, owned, plain, record_audit
from app.services.principal import Principal

CENT = Decimal("0.01")
OPEN_PO = ("APPROVED", "SENT", "PARTIALLY_RECEIVED")


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def _now() -> datetime:
    return datetime.now(UTC)


def _event(doc, label: str, actor: Principal, note: str | None = None) -> None:
    doc.timeline = [*(doc.timeline or []), {"at": _now().isoformat(), "label": label, "by": actor.full_name, **({"note": note} if note else {})}]


def _status(doc, *allowed: str, action: str) -> None:
    if doc.status not in allowed:
        raise InvalidStateTransition(f"Cannot {action} a {doc.status.lower().replace('_', ' ')} document.")


async def _settings(db: AsyncSession, company_id: uuid.UUID) -> dict:
    company = await db.get(Company, company_id)
    return (company.settings or {}) if company else {}


async def _not_creator(db: AsyncSession, actor: Principal, creator: uuid.UUID | None, what: str) -> bool:
    if creator != actor.user_id:
        return False
    if (await _settings(db, actor.company_id)).get("reduced_sod_mode"):
        return True
    raise SodViolation(f"{what} must be approved by someone other than its creator.")


def _sees_cost(actor: Principal) -> bool:
    return actor.sees_cost or actor.can("purchasing.order.create", "purchasing.order.approve", "purchasing.invoice.manage")


async def _locked(db: AsyncSession, actor: Principal, model: type, doc_id: uuid.UUID, what: str):
    doc = await db.scalar(select(model).where(model.id == doc_id, model.company_id == actor.company_id).with_for_update().execution_options(populate_existing=True))
    if doc is None:
        raise NotFound(what)
    await stock.scoped_warehouse(db, actor, doc.warehouse_id)
    return doc


async def _user_name(db: AsyncSession, user_id: uuid.UUID | None) -> str:
    return await stock.user_name(db, user_id)


# Suppliers

async def supplier_view(db: AsyncSession, sup: Supplier) -> dict:
    open_count = await db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.status.in_(("PENDING_APPROVAL", *OPEN_PO))))
    received = list(await db.execute(select(PurchaseOrder.first_received_at, PurchaseOrder.expected_date).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.first_received_at.is_not(None))))
    on_time = (Decimal(sum(1 for at, due in received if at.date() <= due)) / len(received) * 100).quantize(CENT) if received else None
    ordered, got = (await db.execute(
        select(func.coalesce(func.sum(PurchaseOrderLine.quantity_base), 0), func.coalesce(func.sum(PurchaseOrderLine.received_base), 0))
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.po_id).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.status.in_(("RECEIVED", "SHORT_CLOSED")))
    )).one()
    fill = (Decimal(got) / Decimal(ordered) * 100).quantize(CENT) if ordered else None
    outstanding = await db.scalar(select(func.coalesce(func.sum(SupplierInvoice.amount - SupplierInvoice.paid_amount), 0)).where(SupplierInvoice.supplier_id == sup.id))
    return {
        **{f: getattr(sup, f) for f in ("id", "code", "name_en", "name_km", "tax_id", "phone", "email", "address", "payment_terms", "currency", "lead_time_days", "status")},
        "contacts": sup.contacts or [], "open_po_count": open_count or 0, "on_time_rate": on_time, "fill_rate": fill, "outstanding_balance": Decimal(outstanding or 0),
    }


async def list_suppliers(db: AsyncSession, actor: Principal, q: str | None, status: str | None) -> list[dict]:
    query = select(Supplier).where(Supplier.company_id == actor.company_id, Supplier.deleted_at.is_(None))
    if q:
        like = f"%{q.lower()}%"
        query = query.where(func.lower(Supplier.name_en).like(like) | func.lower(Supplier.code).like(like))
    if status:
        query = query.where(Supplier.status == status)
    return [await supplier_view(db, x) for x in await db.scalars(query.order_by(Supplier.name_en))]


def _contacts(items: list[s.ContactIn]) -> list[dict]:
    return [{"id": c.id or uuid.uuid4().hex, "name": c.name, "position": c.position, "phone": c.phone, "email": c.email} for c in items]


async def create_supplier(db: AsyncSession, actor: Principal, data: s.SupplierCreate) -> dict:
    await ensure_unique(db, Supplier, actor, "code", data.code)
    values = {k: v for k, v in data.model_dump(exclude={"contacts"}).items() if v is not None}
    sup = Supplier(company_id=actor.company_id, created_by=actor.user_id, contacts=_contacts(data.contacts or []), **values)
    db.add(sup)
    await db.flush()
    await record_audit(db, actor, "SUPPLIER_CREATED", "PUR", "supplier", sup.id, after=plain(values))
    await db.commit()
    return await supplier_view(db, sup)


async def update_supplier(db: AsyncSession, actor: Principal, supplier_id: uuid.UUID, data: s.SupplierUpdate) -> dict:
    sup = await owned(db, Supplier, supplier_id, actor, "Supplier")
    changes = data.model_dump(exclude_unset=True, exclude={"contacts"})
    changes = {k: v for k, v in changes.items() if v is not None}
    await ensure_unique(db, Supplier, actor, "code", changes.get("code"), exclude=sup.id)
    before, after = apply_changes(sup, changes)
    if data.contacts is not None:
        sup.contacts = _contacts(data.contacts)
        after["contacts"] = len(sup.contacts)
    sup.updated_by = actor.user_id
    if after:
        await record_audit(db, actor, "SUPPLIER_UPDATED", "PUR", "supplier", sup.id, before=before, after=after)
    await db.commit()
    await db.refresh(sup)
    return await supplier_view(db, sup)


async def delete_supplier(db: AsyncSession, actor: Principal, supplier_id: uuid.UUID) -> None:
    sup = await owned(db, Supplier, supplier_id, actor, "Supplier")
    if await db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == sup.id, PurchaseOrder.status.in_(("DRAFT", "PENDING_APPROVAL", *OPEN_PO))).limit(1)):
        raise Conflict("This supplier has open purchase orders.", code="SUPPLIER_IN_USE")
    sup.deleted_at, sup.status = func.now(), "INACTIVE"
    await record_audit(db, actor, "SUPPLIER_DELETED", "PUR", "supplier", sup.id, before={"code": sup.code})
    await db.commit()


async def _active_supplier(db: AsyncSession, actor: Principal, supplier_id: uuid.UUID) -> Supplier:
    sup = await owned(db, Supplier, supplier_id, actor, "Supplier")
    if sup.status != "ACTIVE":
        raise ValidationFailed("supplier_id", "This supplier is inactive.")
    return sup


# Purchase orders

async def po_view(db: AsyncSession, actor: Principal, po: PurchaseOrder) -> dict:
    await db.refresh(po)
    lines = list(await db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id).order_by(PurchaseOrderLine.line_no).execution_options(populate_existing=True)))
    products = {p.id: p for p in await db.scalars(select(Product).where(Product.id.in_({ln.product_id for ln in lines})))} if lines else {}
    units = {u.id: u.code for u in await db.scalars(select(Unit).where(Unit.id.in_({ln.unit_id for ln in lines})))} if lines else {}
    supplier = await db.get(Supplier, po.supplier_id)
    warehouse = await db.get(Warehouse, po.warehouse_id)
    see = _sees_cost(actor)
    return {
        **{f: getattr(po, f) for f in ("id", "po_no", "supplier_id", "warehouse_id", "branch_id", "expected_date", "status", "notes", "created_at", "sent_at", "first_received_at", "version")},
        "supplier_name": supplier.name_en if supplier else "", "warehouse_name": warehouse.name if warehouse else "", "timeline": po.timeline or [],
        "subtotal": po.subtotal if see else None, "tax_total": po.tax_total if see else None, "total": po.total if see else None,
        "created_by": await _user_name(db, po.created_by), "created_by_id": po.created_by, "approved_by": po.approved_by_name,
        "lines": [{**{f: getattr(ln, f) for f in ("id", "product_id", "supplier_sku", "unit_id", "factor", "quantity", "quantity_base", "tax_rate", "received_base", "cancelled_base")},
                   "sku": products[ln.product_id].sku, "product_name": products[ln.product_id].name_en, "unit_code": units.get(ln.unit_id, ""),
                   "unit_cost": ln.unit_cost if see else None, "line_total": ln.line_total if see else None} for ln in lines],
    }


async def list_pos(db: AsyncSession, actor: Principal, *, status: str | None, supplier_id: uuid.UUID | None, branch_id: uuid.UUID | None, limit: int, offset: int) -> list[dict]:
    query = select(PurchaseOrder).where(PurchaseOrder.company_id == actor.company_id, PurchaseOrder.warehouse_id.in_(stock.visible_warehouses(actor)))
    for column, value in ((PurchaseOrder.status, status), (PurchaseOrder.supplier_id, supplier_id), (PurchaseOrder.branch_id, branch_id)):
        if value is not None:
            query = query.where(column == value)
    return [await po_view(db, actor, po) for po in await db.scalars(query.order_by(PurchaseOrder.created_at.desc()).limit(limit).offset(offset))]


async def _set_po_lines(db: AsyncSession, actor: Principal, po: PurchaseOrder, lines: list[s.PoLineIn]) -> None:
    await db.execute(delete(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id))
    subtotal = tax_total = Decimal(0)
    for i, item in enumerate(lines, start=1):
        product = await stock.stock_product(db, actor, item.product_id)
        link = await db.get(ProductSupplier, (product.id, po.supplier_id))
        unit_id = item.unit_id or (link.purchase_unit_id if link else product.base_unit_id)
        factor = await pricing.unit_factor(db, product, unit_id)
        if factor is None:
            raise ValidationFailed(f"lines.{i}.unit_id", f"{product.sku} has no conversion for this unit.")
        tax = await db.get(TaxCode, product.tax_code_id) if product.tax_code_id else None
        rate = tax.rate if tax and tax.status == "ACTIVE" else Decimal(0)
        net = cents(item.quantity * item.unit_cost)
        tax_amount = cents(net * rate / 100)
        subtotal, tax_total = subtotal + net, tax_total + tax_amount
        db.add(PurchaseOrderLine(po_id=po.id, line_no=i, product_id=product.id, supplier_sku=link.supplier_sku if link else "", unit_id=unit_id, factor=factor, quantity=item.quantity,
                                 quantity_base=item.quantity * factor, unit_cost=item.unit_cost, tax_rate=rate, line_total=net + tax_amount))
    po.subtotal, po.tax_total, po.total = subtotal, tax_total, subtotal + tax_total
    await db.flush()


async def create_po(db: AsyncSession, actor: Principal, data: s.PoCreate) -> dict:
    await _active_supplier(db, actor, data.supplier_id)
    warehouse = await stock.scoped_warehouse(db, actor, data.warehouse_id)
    po = PurchaseOrder(company_id=actor.company_id, po_no=await next_number(db, actor.company_id, "PO"), supplier_id=data.supplier_id, warehouse_id=warehouse.id, branch_id=warehouse.branch_id,
                       expected_date=data.expected_date, notes=data.notes, created_by=actor.user_id)
    _event(po, "Created", actor)
    db.add(po)
    await db.flush()
    await _set_po_lines(db, actor, po, data.lines)
    await record_audit(db, actor, "PO_CREATED", "PUR", "purchase_order", po.id, after={"po_no": po.po_no, "total": str(po.total)}, branch_id=po.branch_id)
    await db.commit()
    return await po_view(db, actor, po)


async def update_po(db: AsyncSession, actor: Principal, po_id: uuid.UUID, data: s.PoUpdate) -> dict:
    po = await _locked(db, actor, PurchaseOrder, po_id, "Purchase order")
    _status(po, "DRAFT", "PENDING_APPROVAL", "APPROVED", action="edit")
    if data.supplier_id:
        await _active_supplier(db, actor, data.supplier_id)
        po.supplier_id = data.supplier_id
    if data.warehouse_id:
        warehouse = await stock.scoped_warehouse(db, actor, data.warehouse_id)
        po.warehouse_id, po.branch_id = warehouse.id, warehouse.branch_id
    if data.expected_date:
        po.expected_date = data.expected_date
    if data.notes is not None:
        po.notes = data.notes
    if data.lines is not None:
        if not data.lines:
            raise ValidationFailed("lines", "Add at least one line.")
        await _set_po_lines(db, actor, po, data.lines)
    if po.status in ("PENDING_APPROVAL", "APPROVED"):
        # Any change after submission needs approval again (BR-PUR-001).
        po.status, po.approved_by_id, po.approved_by_name = "PENDING_APPROVAL", None, None
        _event(po, "Edited; approval required again", actor)
    else:
        _event(po, "Edited", actor)
    po.updated_by = actor.user_id
    await record_audit(db, actor, "PO_UPDATED", "PUR", "purchase_order", po.id, after={"total": str(po.total), "status": po.status}, branch_id=po.branch_id)
    await db.commit()
    return await po_view(db, actor, po)


async def delete_po(db: AsyncSession, actor: Principal, po_id: uuid.UUID) -> None:
    po = await _locked(db, actor, PurchaseOrder, po_id, "Purchase order")
    _status(po, "DRAFT", action="delete")
    await db.delete(po)
    await record_audit(db, actor, "PO_DELETED", "PUR", "purchase_order", po_id, before={"po_no": po.po_no}, branch_id=po.branch_id)
    await db.commit()


async def po_action(db: AsyncSession, actor: Principal, po_id: uuid.UUID, verb: str, body: s.DocAction) -> dict:
    po = await _locked(db, actor, PurchaseOrder, po_id, "Purchase order")
    flagged = False
    if verb == "submit":
        actor.require("purchasing.order.create")
        _status(po, "DRAFT", action="submit")
        po.status = "PENDING_APPROVAL"
        _event(po, "Submitted for approval", actor)
    elif verb == "approve":
        actor.require("purchasing.order.approve")
        _status(po, "PENDING_APPROVAL", action="approve")
        flagged = await _not_creator(db, actor, po.created_by, "A purchase order")
        limit = actor.limits.get("po_approval_limit", Decimal(0))
        if po.total > limit:
            raise LimitExceeded(f"Your purchase order approval limit is {limit.normalize()}; this order is {po.total.normalize()}.")
        po.status, po.approved_by_id, po.approved_by_name = "APPROVED", actor.user_id, actor.full_name
        _event(po, "Approved", actor)
    elif verb == "reject":
        actor.require("purchasing.order.approve")
        _status(po, "PENDING_APPROVAL", action="reject")
        if not body.reason:
            raise ValidationFailed("reason", "Give a reason for rejecting.")
        po.status = "DRAFT"
        _event(po, "Rejected", actor, body.reason)
    elif verb == "send":
        actor.require("purchasing.order.create", "purchasing.order.approve")
        _status(po, "APPROVED", action="send")
        po.status, po.sent_at = "SENT", _now()
        _event(po, "Sent to supplier", actor)
    elif verb == "cancel":
        actor.require("purchasing.order.create", "purchasing.order.approve")
        _status(po, "DRAFT", "PENDING_APPROVAL", "APPROVED", "SENT", action="cancel")
        po.status = "CANCELLED"
        _event(po, "Cancelled", actor, body.reason)
    elif verb in ("close", "short-close"):
        actor.require("purchasing.order.approve", "purchasing.order.create")
        _status(po, "PARTIALLY_RECEIVED", action="short-close")
        for line in await db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)):
            line.cancelled_base = max(line.quantity_base - line.received_base, Decimal(0))
        po.status = "SHORT_CLOSED"
        _event(po, "Short-closed; remaining quantity cancelled", actor, body.reason)
    else:
        raise NotFound("Action")
    await record_audit(db, actor, f"PO_{verb.upper().replace('-', '_')}", "PUR", "purchase_order", po.id, after={"po_no": po.po_no, "status": po.status, "reason": body.reason},
                       branch_id=po.branch_id, flagged=flagged)
    await db.commit()
    return await po_view(db, actor, po)


# Goods receipts

async def grn_view(db: AsyncSession, actor: Principal, g: GoodsReceipt) -> dict:
    await db.refresh(g)
    lines = list(await db.scalars(select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == g.id).order_by(GoodsReceiptLine.line_no).execution_options(populate_existing=True)))
    products = {p.id: p for p in await db.scalars(select(Product).where(Product.id.in_({ln.product_id for ln in lines})))} if lines else {}
    units = {u.id: u.code for u in await db.scalars(select(Unit).where(Unit.id.in_({ln.unit_id for ln in lines})))} if lines else {}
    po_lines = {pl.id: pl for pl in await db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.id.in_({ln.po_line_id for ln in lines if ln.po_line_id})))}
    po = await db.get(PurchaseOrder, g.po_id) if g.po_id else None
    supplier = await db.get(Supplier, g.supplier_id)
    warehouse = await db.get(Warehouse, g.warehouse_id)
    see = _sees_cost(actor)
    rows = []
    for ln in lines:
        pl = po_lines.get(ln.po_line_id) if ln.po_line_id else None
        open_qty = ((pl.quantity_base - pl.received_base - pl.cancelled_base) / ln.factor) if pl else Decimal(0)
        rows.append({**{f: getattr(ln, f) for f in ("id", "po_line_id", "product_id", "unit_id", "factor", "quantity_received", "quantity_damaged", "quantity_rejected", "batch_no", "expiry_date")},
                     "sku": products[ln.product_id].sku, "product_name": products[ln.product_id].name_en, "unit_code": units.get(ln.unit_id, ""), "ordered_open": max(open_qty, Decimal(0)),
                     "unit_cost": ln.unit_cost if see else None, "track_expiry": products[ln.product_id].track_expiry})
    return {
        **{f: getattr(g, f) for f in ("id", "receipt_no", "po_id", "supplier_id", "warehouse_id", "branch_id", "status", "blind", "exception_reason", "delivery_note", "invoice_ref",
                                      "posted_at", "created_at", "flagged_for_review", "version")},
        "po_no": po.po_no if po else None, "supplier_name": supplier.name_en if supplier else "", "warehouse_name": warehouse.name if warehouse else "",
        "lines": rows, "discrepancies": g.discrepancies or [], "total_cost": g.total_cost if see else None, "created_by": await _user_name(db, g.created_by), "created_by_id": g.created_by,
        "approved_by": g.approved_by_name, "posted_by": g.posted_by_name,
    }


async def list_grns(db: AsyncSession, actor: Principal, *, status: str | None, po_id: uuid.UUID | None, branch_id: uuid.UUID | None, limit: int, offset: int) -> list[dict]:
    query = select(GoodsReceipt).where(GoodsReceipt.company_id == actor.company_id, GoodsReceipt.warehouse_id.in_(stock.visible_warehouses(actor)))
    for column, value in ((GoodsReceipt.status, status), (GoodsReceipt.po_id, po_id), (GoodsReceipt.branch_id, branch_id)):
        if value is not None:
            query = query.where(column == value)
    return [await grn_view(db, actor, g) for g in await db.scalars(query.order_by(GoodsReceipt.created_at.desc()).limit(limit).offset(offset))]


async def _set_grn_lines(db: AsyncSession, actor: Principal, g: GoodsReceipt, items: list[s.GrnLineIn]) -> None:
    await db.execute(delete(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == g.id))
    po_lines = {pl.id: pl for pl in await db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == g.po_id))} if g.po_id else {}
    if not any(i.quantity_received + i.quantity_damaged + i.quantity_rejected > 0 for i in items):
        raise ValidationFailed("lines", "Enter at least one received quantity.")
    total = Decimal(0)
    for n, item in enumerate(items, start=1):
        product = await stock.stock_product(db, actor, item.product_id)
        pl = None
        if item.po_line_id:
            pl = po_lines.get(item.po_line_id)
            if pl is None or pl.product_id != product.id:
                raise ValidationFailed(f"lines.{n}.po_line_id", "This line does not belong to the purchase order.")
        unit_id = item.unit_id or (pl.unit_id if pl else product.base_unit_id)
        factor = await pricing.unit_factor(db, product, unit_id)
        if factor is None:
            raise ValidationFailed(f"lines.{n}.unit_id", f"{product.sku} has no conversion for this unit.")
        for qty in (item.quantity_received, item.quantity_damaged):
            if qty:
                stock.check_quantity(product, qty * factor, f"lines.{n}.quantity_received")
        if product.track_expiry and item.quantity_received > 0 and (not item.batch_no or not item.expiry_date):
            raise ValidationFailed(f"lines.{n}.batch_no", f"{product.sku} tracks expiry: enter the batch number and expiry date.")
        db.add(GoodsReceiptLine(receipt_id=g.id, line_no=n, po_line_id=pl.id if pl else None, product_id=product.id, unit_id=unit_id, factor=factor, quantity_received=item.quantity_received,
                                quantity_damaged=item.quantity_damaged, quantity_rejected=item.quantity_rejected, unit_cost=item.unit_cost, batch_no=item.batch_no.strip(), expiry_date=item.expiry_date))
        total += (item.quantity_received + item.quantity_damaged) * item.unit_cost
    g.total_cost = cents(total)
    await db.flush()
    await _discrepancies(db, actor, g)


async def _discrepancies(db: AsyncSession, actor: Principal, g: GoodsReceipt) -> bool:
    """Lists discrepancies and returns whether approval is needed before posting (BR-GRN-002)."""
    notes: list[str] = []
    needs_approval = False
    tolerance = Decimal(str((await _settings(db, actor.company_id)).get("over_delivery_tolerance_pct", "5")))
    lines = list(await db.scalars(select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == g.id)))
    products = {p.id: p for p in await db.scalars(select(Product).where(Product.id.in_({ln.product_id for ln in lines})))}
    if g.po_id is None:
        notes.append(f"Received without a purchase order: {g.exception_reason}")
        needs_approval = True
    else:
        po_lines = {pl.id: pl for pl in await db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == g.po_id))}
        received_by_line: dict[uuid.UUID, Decimal] = {}
        for ln in lines:
            sku = products[ln.product_id].sku
            if ln.po_line_id is None:
                notes.append(f"{sku} is not on the purchase order")
                needs_approval = True
                continue
            received_by_line[ln.po_line_id] = received_by_line.get(ln.po_line_id, Decimal(0)) + (ln.quantity_received + ln.quantity_damaged) * ln.factor
            pl = po_lines[ln.po_line_id]
            if ln.unit_cost * pl.factor != pl.unit_cost * ln.factor:
                notes.append(f"{sku}: cost {ln.unit_cost.normalize()} differs from the PO cost {pl.unit_cost.normalize()}")
            if ln.quantity_damaged:
                notes.append(f"{sku}: {ln.quantity_damaged.normalize()} damaged")
            if ln.quantity_rejected:
                notes.append(f"{sku}: {ln.quantity_rejected.normalize()} rejected")
        for pl_id, qty in received_by_line.items():
            pl = po_lines[pl_id]
            open_base = pl.quantity_base - pl.received_base - pl.cancelled_base
            sku = products[pl.product_id].sku
            if qty > open_base * (1 + tolerance / 100):
                notes.append(f"{sku}: {qty.normalize()} received against {open_base.normalize()} open, beyond the {tolerance.normalize()}% tolerance")
                needs_approval = True
            elif qty < open_base:
                notes.append(f"{sku}: short by {(open_base - qty).normalize()}")
    g.discrepancies = notes
    g.flagged_for_review = needs_approval
    return needs_approval


async def create_grn(db: AsyncSession, actor: Principal, data: s.GrnCreate) -> dict:
    if data.po_id:
        po = await db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == data.po_id, PurchaseOrder.company_id == actor.company_id))
        if po is None:
            raise NotFound("Purchase order")
        if po.status not in OPEN_PO:
            raise InvalidStateTransition(f"A {po.status.lower().replace('_', ' ')} purchase order cannot be received.")
        supplier_id, warehouse_id, reason = po.supplier_id, po.warehouse_id, None
    else:
        if not actor.can("purchasing.receipt.exception"):
            raise Forbidden("Receiving without a purchase order needs the receiving-exception permission.")  # BR-GRN-003
        if not data.exception_reason or not data.supplier_id or not data.warehouse_id:
            raise ValidationFailed("exception_reason", "Give the supplier, warehouse and a reason for receiving without a purchase order.")
        await _active_supplier(db, actor, data.supplier_id)
        supplier_id, warehouse_id, reason = data.supplier_id, data.warehouse_id, data.exception_reason
    warehouse = await stock.scoped_warehouse(db, actor, warehouse_id)
    g = GoodsReceipt(company_id=actor.company_id, receipt_no=await next_number(db, actor.company_id, "GRN"), po_id=data.po_id, supplier_id=supplier_id, warehouse_id=warehouse.id,
                     branch_id=warehouse.branch_id, blind=data.blind, exception_reason=reason, delivery_note=data.delivery_note, invoice_ref=data.invoice_ref, created_by=actor.user_id)
    db.add(g)
    await db.flush()
    await _set_grn_lines(db, actor, g, data.lines)
    await record_audit(db, actor, "GRN_CREATED", "GRN", "goods_receipt", g.id, after={"receipt_no": g.receipt_no, "po_id": str(g.po_id) if g.po_id else None, "discrepancies": len(g.discrepancies)},
                       branch_id=g.branch_id, flagged=g.po_id is None)
    await db.commit()
    return await grn_view(db, actor, g)


async def update_grn(db: AsyncSession, actor: Principal, grn_id: uuid.UUID, data: s.GrnUpdate) -> dict:
    g = await _locked(db, actor, GoodsReceipt, grn_id, "Goods receipt")
    _status(g, "DRAFT", action="edit")
    for field in ("delivery_note", "invoice_ref"):
        if getattr(data, field) is not None:
            setattr(g, field, getattr(data, field))
    if data.exception_reason is not None and g.po_id is None:
        g.exception_reason = data.exception_reason or g.exception_reason
    if data.lines is not None:
        await _set_grn_lines(db, actor, g, data.lines)
    await db.commit()
    return await grn_view(db, actor, g)


async def delete_grn(db: AsyncSession, actor: Principal, grn_id: uuid.UUID) -> None:
    g = await _locked(db, actor, GoodsReceipt, grn_id, "Goods receipt")
    _status(g, "DRAFT", action="delete")
    await db.delete(g)
    await record_audit(db, actor, "GRN_DELETED", "GRN", "goods_receipt", grn_id, before={"receipt_no": g.receipt_no}, branch_id=g.branch_id)
    await db.commit()


async def _location(db: AsyncSession, warehouse_id: uuid.UUID, preference: list[str]) -> WarehouseLocation:
    for kind in preference:
        loc = await db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse_id, WarehouseLocation.location_type == kind, WarehouseLocation.status == "ACTIVE")
                              .order_by(WarehouseLocation.code).limit(1))
        if loc:
            return loc
    raise ValidationFailed("warehouse_id", f"The warehouse needs an active {' or '.join(preference).lower()} location.")


async def _post_grn(db: AsyncSession, actor: Principal, g: GoodsReceipt) -> None:
    lines = list(await db.scalars(select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == g.id).order_by(GoodsReceiptLine.line_no)))
    good = await _location(db, g.warehouse_id, ["RECEIVING", "STORAGE", "SELLABLE"])
    damaged = None
    moves = []
    for ln in lines:
        product = await db.get(Product, ln.product_id)
        base_cost = ln.unit_cost / ln.factor
        for qty, kind in ((ln.quantity_received, "GOOD"), (ln.quantity_damaged, "DAMAGED")):
            if qty <= 0:
                continue
            if kind == "DAMAGED":
                damaged = damaged or await _location(db, g.warehouse_id, ["DAMAGED"])
            moves.append(stock.Move(product, qty * ln.factor, "PURCHASE_RECEIPT", "GRN", str(g.id), f"{ln.id}:{kind}", to_location=good if kind == "GOOD" else damaged,
                                    source_no=g.receipt_no, unit_cost=base_cost, batch_no=ln.batch_no, expiry_date=ln.expiry_date,
                                    unit_id=ln.unit_id, quantity_entered=qty, approved_by=g.approved_by_name, reason="DAMAGED_ON_ARRIVAL" if kind == "DAMAGED" else None))
    await stock.post(db, actor, moves)
    if g.po_id:
        po = await db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == g.po_id).with_for_update().execution_options(populate_existing=True))
        po_lines = {pl.id: pl for pl in await db.scalars(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id).with_for_update())}
        for ln in lines:
            if ln.po_line_id:
                po_lines[ln.po_line_id].received_base += (ln.quantity_received + ln.quantity_damaged) * ln.factor
        complete = all(pl.received_base + pl.cancelled_base >= pl.quantity_base for pl in po_lines.values())
        po.status = "RECEIVED" if complete else "PARTIALLY_RECEIVED"
        po.first_received_at = po.first_received_at or _now()
        _event(po, f"Received {g.receipt_no}", actor)
    g.status, g.posted_at, g.posted_by_name = "POSTED", _now(), actor.full_name


async def grn_action(db: AsyncSession, actor: Principal, grn_id: uuid.UUID, verb: str, body: s.DocAction) -> dict:
    g = await _locked(db, actor, GoodsReceipt, grn_id, "Goods receipt")
    flagged = False
    if verb == "post":
        actor.require("purchasing.receipt.post", "purchasing.receipt.create")
        if g.status == "POSTED":
            raise Conflict(f"{g.receipt_no} is already posted.", code="ALREADY_POSTED")  # BR-GRN-001
        _status(g, "DRAFT", action="post")
        if await _discrepancies(db, actor, g):
            g.status = "PENDING_APPROVAL"
        else:
            await _post_grn(db, actor, g)
    elif verb == "approve":
        actor.require("inventory.adjustment.approve", "purchasing.receipt.exception", "purchasing.order.approve")
        _status(g, "PENDING_APPROVAL", action="approve")
        flagged = await _not_creator(db, actor, g.created_by, "A goods receipt with discrepancies")
        g.approved_by_name = actor.full_name
        await _post_grn(db, actor, g)
    elif verb == "reject":
        actor.require("inventory.adjustment.approve", "purchasing.receipt.exception", "purchasing.order.approve")
        _status(g, "PENDING_APPROVAL", action="return to draft")
        g.status = "DRAFT"
    else:
        raise NotFound("Action")
    await record_audit(db, actor, f"GRN_{verb.upper()}", "GRN", "goods_receipt", g.id, after={"receipt_no": g.receipt_no, "status": g.status, "discrepancies": g.discrepancies},
                       branch_id=g.branch_id, flagged=flagged or (g.status == "POSTED" and g.flagged_for_review))
    await db.commit()
    return await grn_view(db, actor, g)


# Supplier invoices

def normalise_invoice_no(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


async def invoice_view(db: AsyncSession, inv: SupplierInvoice) -> dict:
    await db.refresh(inv)
    supplier = await db.get(Supplier, inv.supplier_id)
    po = await db.get(PurchaseOrder, inv.po_id) if inv.po_id else None
    payments = await db.scalars(select(SupplierPayment).where(SupplierPayment.invoice_id == inv.id).order_by(SupplierPayment.paid_at))
    return {
        **{f: getattr(inv, f) for f in ("id", "invoice_no", "supplier_id", "po_id", "invoice_date", "due_date", "amount", "paid_amount", "status", "match_notes", "created_at")},
        "supplier_name": supplier.name_en if supplier else "", "po_no": po.po_no if po else None, "created_by": await _user_name(db, inv.created_by),
        "payments": [{"id": p.id, "amount": p.amount, "reference": p.reference, "paid_at": p.paid_at, "by": p.by_name} for p in payments],
    }


async def list_invoices(db: AsyncSession, actor: Principal, supplier_id: uuid.UUID | None) -> list[dict]:
    query = select(SupplierInvoice).where(SupplierInvoice.company_id == actor.company_id)
    if supplier_id:
        query = query.where(SupplierInvoice.supplier_id == supplier_id)
    return [await invoice_view(db, x) for x in await db.scalars(query.order_by(SupplierInvoice.invoice_date.desc(), SupplierInvoice.created_at.desc()))]


async def _received_value(db: AsyncSession, po_id: uuid.UUID) -> Decimal:
    rows = await db.execute(
        select(GoodsReceiptLine.quantity_received + GoodsReceiptLine.quantity_damaged, GoodsReceiptLine.unit_cost, PurchaseOrderLine.tax_rate)
        .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.receipt_id).outerjoin(PurchaseOrderLine, PurchaseOrderLine.id == GoodsReceiptLine.po_line_id)
        .where(GoodsReceipt.po_id == po_id, GoodsReceipt.status == "POSTED")
    )
    return sum((cents(q * c * (1 + (rate or 0) / 100)) for q, c, rate in rows), Decimal(0))


async def create_invoice(db: AsyncSession, actor: Principal, data: s.InvoiceCreate) -> dict:
    await owned(db, Supplier, data.supplier_id, actor, "Supplier")
    if data.due_date < data.invoice_date:
        raise ValidationFailed("due_date", "The due date cannot be before the invoice date.")
    normalised = normalise_invoice_no(data.invoice_no)
    if not normalised:
        raise ValidationFailed("invoice_no", "Enter the supplier's invoice number.")
    if await db.scalar(select(SupplierInvoice.id).where(SupplierInvoice.supplier_id == data.supplier_id, SupplierInvoice.invoice_no_normalised == normalised)):
        raise Conflict(f"Invoice {data.invoice_no} from this supplier is already recorded.", code="DUPLICATE_INVOICE")  # BR-PUR-003
    notes, status = [], "RECORDED"
    if data.po_id:
        po = await db.scalar(select(PurchaseOrder).where(PurchaseOrder.id == data.po_id, PurchaseOrder.company_id == actor.company_id))
        if po is None or po.supplier_id != data.supplier_id:
            raise ValidationFailed("po_id", "The purchase order does not belong to this supplier.")
        received = await _received_value(db, po.id)
        tolerance = max(cents(received / 100), CENT)
        if abs(received - data.amount) <= tolerance:
            status = "MATCHED"
            notes.append(f"Matches the received value {received.normalize()}.")
        else:
            status = "MISMATCH"
            notes.append(f"Invoice {data.amount.normalize()} vs received value {received.normalize()} (difference {(data.amount - received).normalize()}).")
    near = await db.scalar(select(SupplierInvoice.invoice_no).where(SupplierInvoice.supplier_id == data.supplier_id, SupplierInvoice.amount == data.amount, SupplierInvoice.invoice_date == data.invoice_date).limit(1))
    if near:
        notes.append(f"Warning: invoice {near} has the same amount and date.")
    inv = SupplierInvoice(company_id=actor.company_id, supplier_id=data.supplier_id, invoice_no=data.invoice_no.strip(), invoice_no_normalised=normalised, po_id=data.po_id,
                          invoice_date=data.invoice_date, due_date=data.due_date, amount=data.amount, status=status, match_notes=" ".join(notes), created_by=actor.user_id)
    db.add(inv)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict(f"Invoice {data.invoice_no} from this supplier is already recorded.", code="DUPLICATE_INVOICE") from exc
    await record_audit(db, actor, "SUPPLIER_INVOICE_RECORDED", "PUR", "supplier_invoice", inv.id, after={"invoice_no": inv.invoice_no, "amount": str(inv.amount), "status": status}, flagged=status == "MISMATCH")
    await db.commit()
    return await invoice_view(db, inv)


async def pay_invoice(db: AsyncSession, actor: Principal, invoice_id: uuid.UUID, data: s.InvoicePaymentIn) -> dict:
    inv = await db.scalar(select(SupplierInvoice).where(SupplierInvoice.id == invoice_id, SupplierInvoice.company_id == actor.company_id).with_for_update())
    if inv is None:
        raise NotFound("Supplier invoice")
    outstanding = inv.amount - inv.paid_amount
    if data.amount > outstanding:
        raise ValidationFailed("amount", f"Only {outstanding.normalize()} is outstanding.")
    db.add(SupplierPayment(invoice_id=inv.id, amount=data.amount, reference=data.reference, user_id=actor.user_id, by_name=actor.full_name))
    inv.paid_amount += data.amount
    inv.status = "PAID" if inv.paid_amount >= inv.amount else "PARTIALLY_PAID"
    await record_audit(db, actor, "SUPPLIER_PAYMENT_RECORDED", "PUR", "supplier_invoice", inv.id, after={"amount": str(data.amount), "reference": data.reference})
    await db.commit()
    return await invoice_view(db, inv)


# Purchase returns

async def pr_view(db: AsyncSession, actor: Principal, pr: PurchaseReturn) -> dict:
    await db.refresh(pr)
    lines = list(await db.scalars(select(PurchaseReturnLine).where(PurchaseReturnLine.return_id == pr.id)))
    products = {p.id: p for p in await db.scalars(select(Product).where(Product.id.in_({ln.product_id for ln in lines})))} if lines else {}
    locations = {loc.id: loc for loc in await db.scalars(select(WarehouseLocation).where(WarehouseLocation.id.in_({ln.location_id for ln in lines})))} if lines else {}
    supplier = await db.get(Supplier, pr.supplier_id)
    grn = await db.get(GoodsReceipt, pr.goods_receipt_id)
    see = _sees_cost(actor)
    return {
        **{f: getattr(pr, f) for f in ("id", "return_no", "supplier_id", "goods_receipt_id", "warehouse_id", "status", "reason", "credit_note_ref", "created_at", "version")},
        "supplier_name": supplier.name_en if supplier else "", "goods_receipt_no": grn.receipt_no if grn else "", "total": pr.total if see else None,
        "created_by": await _user_name(db, pr.created_by), "created_by_id": pr.created_by, "approved_by": pr.approved_by_name,
        "lines": [{"id": ln.id, "product_id": ln.product_id, "sku": products[ln.product_id].sku, "product_name": products[ln.product_id].name_en, "location_id": ln.location_id,
                   "location_name": locations[ln.location_id].name, "quantity_base": ln.quantity_base, "unit_cost": ln.unit_cost if see else None, "total": ln.total if see else None} for ln in lines],
    }


async def list_prs(db: AsyncSession, actor: Principal) -> list[dict]:
    query = select(PurchaseReturn).where(PurchaseReturn.company_id == actor.company_id, PurchaseReturn.warehouse_id.in_(stock.visible_warehouses(actor)))
    return [await pr_view(db, actor, x) for x in await db.scalars(query.order_by(PurchaseReturn.created_at.desc()))]


async def create_pr(db: AsyncSession, actor: Principal, data: s.PrCreate) -> dict:
    grn = await db.scalar(select(GoodsReceipt).where(GoodsReceipt.id == data.goods_receipt_id, GoodsReceipt.company_id == actor.company_id))
    if grn is None:
        raise NotFound("Goods receipt")
    await stock.scoped_warehouse(db, actor, grn.warehouse_id)
    if grn.status != "POSTED":
        raise InvalidStateTransition("Only posted goods receipts can be returned.")
    received: dict[uuid.UUID, tuple[Decimal, Decimal, str]] = {}
    for ln in await db.scalars(select(GoodsReceiptLine).where(GoodsReceiptLine.receipt_id == grn.id)):
        qty, cost, batch = received.get(ln.product_id, (Decimal(0), ln.unit_cost / ln.factor, ln.batch_no))
        received[ln.product_id] = (qty + (ln.quantity_received + ln.quantity_damaged) * ln.factor, cost, batch)
    returned = dict((pid, Decimal(q)) for pid, q in await db.execute(
        select(PurchaseReturnLine.product_id, func.sum(PurchaseReturnLine.quantity_base)).join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnLine.return_id)
        .where(PurchaseReturn.goods_receipt_id == grn.id, PurchaseReturn.status != "CANCELLED").group_by(PurchaseReturnLine.product_id)))
    pr = PurchaseReturn(company_id=actor.company_id, return_no=await next_number(db, actor.company_id, "SUPPLIER_RETURN"), supplier_id=grn.supplier_id, goods_receipt_id=grn.id,
                        warehouse_id=grn.warehouse_id, reason=data.reason, created_by=actor.user_id)
    db.add(pr)
    await db.flush()
    total = Decimal(0)
    wanted: dict[uuid.UUID, Decimal] = {}
    for i, line in enumerate(data.lines, start=1):
        if line.product_id not in received:
            raise ValidationFailed(f"lines.{i}.product_id", "This product was not on the goods receipt.")
        wanted[line.product_id] = wanted.get(line.product_id, Decimal(0)) + line.quantity_base
        if wanted[line.product_id] > received[line.product_id][0] - returned.get(line.product_id, Decimal(0)):
            raise ValidationFailed(f"lines.{i}.quantity_base", "More than was received and not yet returned.")
        location = await stock.scoped_location(db, actor, line.location_id, warehouse_id=grn.warehouse_id)
        _, cost, batch = received[line.product_id]
        line_total = cents(line.quantity_base * cost)
        total += line_total
        # Stock that arrived in a batch leaves from the same batch.
        db.add(PurchaseReturnLine(return_id=pr.id, product_id=line.product_id, location_id=location.id, batch_no=batch, quantity_base=line.quantity_base, unit_cost=cost, total=line_total))
    pr.total = total
    await record_audit(db, actor, "PURCHASE_RETURN_CREATED", "PUR", "purchase_return", pr.id, after={"return_no": pr.return_no, "grn": grn.receipt_no, "total": str(total)})
    await db.commit()
    return await pr_view(db, actor, pr)


async def pr_action(db: AsyncSession, actor: Principal, pr_id: uuid.UUID, verb: str, body: s.DocAction) -> dict:
    pr = await _locked(db, actor, PurchaseReturn, pr_id, "Purchase return")
    flagged = False
    if verb == "approve":
        actor.require("purchasing.order.approve")
        _status(pr, "DRAFT", action="approve")
        flagged = await _not_creator(db, actor, pr.created_by, "A purchase return")
        pr.status, pr.approved_by_name = "APPROVED", actor.full_name
    elif verb == "dispatch":
        actor.require("purchasing.return.manage", "purchasing.order.create", "purchasing.receipt.post")
        _status(pr, "APPROVED", action="dispatch")
        moves = []
        for ln in await db.scalars(select(PurchaseReturnLine).where(PurchaseReturnLine.return_id == pr.id)):
            product = await db.get(Product, ln.product_id)
            location = await db.get(WarehouseLocation, ln.location_id)
            # Goods leave at the cost they came in at, which is taken back out of the average (BR-CST-004).
            moves.append(stock.Move(product, ln.quantity_base, "PURCHASE_RETURN", "PURCHASE_RETURN", str(pr.id), str(ln.id), from_location=location, source_no=pr.return_no,
                                    remove_cost=ln.unit_cost, batch_no=ln.batch_no, reason=pr.reason, approved_by=pr.approved_by_name))
        await stock.post(db, actor, moves)
        pr.status, pr.dispatched_at = "DISPATCHED", _now()
    elif verb == "credit":
        actor.require("purchasing.return.manage", "purchasing.invoice.manage", "purchasing.order.create")
        _status(pr, "DISPATCHED", action="record a credit note for")
        if not body.credit_note_ref:
            raise ValidationFailed("credit_note_ref", "Enter the supplier's credit note reference.")
        pr.status, pr.credit_note_ref = "CREDITED", body.credit_note_ref
    elif verb == "cancel":
        actor.require("purchasing.return.manage", "purchasing.order.create")
        _status(pr, "DRAFT", "APPROVED", action="cancel")
        pr.status = "CANCELLED"
    else:
        raise NotFound("Action")
    await record_audit(db, actor, f"PURCHASE_RETURN_{verb.upper()}", "PUR", "purchase_return", pr.id, after={"return_no": pr.return_no, "status": pr.status}, flagged=flagged)
    await db.commit()
    return await pr_view(db, actor, pr)


async def on_order(db: AsyncSession, product_ids: list[uuid.UUID], warehouse_ids) -> dict[uuid.UUID, Decimal]:
    """Open purchase order quantity in base units (BR-PUR-002)."""
    if not product_ids:
        return {}
    rows = await db.execute(
        select(PurchaseOrderLine.product_id, func.sum(PurchaseOrderLine.quantity_base - PurchaseOrderLine.received_base - PurchaseOrderLine.cancelled_base))
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.po_id)
        .where(PurchaseOrderLine.product_id.in_(product_ids), PurchaseOrder.status.in_(OPEN_PO), PurchaseOrder.warehouse_id.in_(warehouse_ids))
        .group_by(PurchaseOrderLine.product_id)
    )
    return {pid: max(Decimal(q or 0), Decimal(0)) for pid, q in rows}
