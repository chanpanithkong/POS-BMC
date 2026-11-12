"""Point of sale: sale building, pricing, payments, finalization, cancellation and voids (POS, PAY, SAL, DOC; Phase 5).

The server is the only source of amounts (BR-POS-001). Every change re-prices the sale:
  gross = unit price x quantity; line discount; order discount shared across lines by net value;
  tax per line (exclusive: added on top; inclusive: extracted from the price); grand total = sum of lines.
Money is rounded to cents (USD). Cash in KHR is rounded to the configured increment (default 100 riel)
and the difference is recorded on the payment (BR-PAY-006).

Finalization (SRS 11.9.2) runs in one transaction: lock the sale, re-price and stop if any price
changed, check payments cover the total, deduct stock (consuming any reservation) at the terminal's
sellable location, allocate the receipt number, then commit. Any failure rolls everything back.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, Forbidden, InvalidStateTransition, NotFound, ValidationFailed
from app.models import (
    Branch,
    Company,
    Customer,
    InventoryBalance,
    OutboxEvent,
    PaymentMethod,
    PosTerminal,
    Product,
    ProductBarcode,
    ProductBranchSetting,
    ReceiptTemplate,
    Refund,
    Sale,
    SaleLine,
    SalePayment,
    SalesReturn,
    StockReservation,
    TaxCode,
    Unit,
    User,
    WarehouseLocation,
)
from app.schemas import sales as s
from app.services import approvals, cash_sessions, customers, pricing, stock
from app.services.common import next_number, record_audit
from app.services.principal import Principal

CENT = Decimal("0.01")
COMPLETED = ("COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED")
EDITABLE = ("DRAFT",)
RESERVATION_MINUTES = 5
PRICE_SOURCE = {"RETAIL": "STANDARD", "BRANCH": "BRANCH", "CUSTOMER_GROUP": "CUSTOMER_GROUP", "CUSTOMER_GROUP_DISCOUNT": "CUSTOMER_GROUP"}


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def _now() -> datetime:
    return datetime.now(UTC)


async def _settings(db: AsyncSession, company_id: uuid.UUID) -> dict:
    company = await db.get(Company, company_id)
    return (company.settings or {}) if company else {}


def four(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), ROUND_HALF_UP)


def round_khr(amount: Decimal, increment: Decimal) -> Decimal:
    return (amount / increment).quantize(Decimal(1), ROUND_HALF_UP) * increment


# Loading and views

async def _lines(db: AsyncSession, sale_id: uuid.UUID, *, fresh: bool = False) -> list[SaleLine]:
    query = select(SaleLine).where(SaleLine.sale_id == sale_id).order_by(SaleLine.line_no)
    return list(await db.scalars(query.execution_options(populate_existing=True) if fresh else query))


async def _payments(db: AsyncSession, sale_id: uuid.UUID, *, fresh: bool = False) -> list[SalePayment]:
    query = select(SalePayment).where(SalePayment.sale_id == sale_id).order_by(SalePayment.created_at)
    return list(await db.scalars(query.execution_options(populate_existing=True) if fresh else query))


async def _available(db: AsyncSession, location_id: uuid.UUID | None, product_id: uuid.UUID) -> Decimal:
    if location_id is None:
        return Decimal(0)
    return Decimal(await db.scalar(select(func.coalesce(func.sum(InventoryBalance.on_hand - InventoryBalance.reserved), 0)).where(InventoryBalance.location_id == location_id, InventoryBalance.product_id == product_id)) or 0)


def payment_view(p: SalePayment) -> dict:
    return {f: getattr(p, f) for f in ("id", "sale_id", "session_id", "terminal_id", "method", "currency", "amount_tendered", "exchange_rate", "amount_applied", "change_amount",
                                       "change_currency", "rounding_amount", "status", "provider", "reference", "approval_code", "card_last4", "failure_reason", "refunded_amount",
                                       "created_at", "completed_at", "reconciled")}


async def sale_view(db: AsyncSession, actor: Principal, sale: Sale) -> dict:
    # Reload stored values so responses show the database's exact decimals, not in-memory intermediates.
    await db.refresh(sale)
    lines = await _lines(db, sale.id, fresh=True)
    terminal = await db.get(PosTerminal, sale.terminal_id)
    branch = await db.get(Branch, sale.branch_id)
    cashier = await db.get(User, sale.cashier_id)
    location = terminal.default_location_id if terminal else None
    returns = list(await db.scalars(select(SalesReturn.id).where(SalesReturn.original_sale_id == sale.id)))
    settings = await _settings(db, sale.company_id)
    increment = Decimal(str(settings.get("khr_cash_increment", "100")))
    line_views = []
    for line in lines:
        line_views.append({
            **{f: getattr(line, f) for f in ("id", "product_id", "sku", "name_en", "name_km", "unit_id", "unit_code", "factor", "quantity", "quantity_base", "allow_fraction", "precision",
                                              "unit_price", "price_source", "price_explanation", "list_price", "override_approved_by", "override_reason", "line_discount", "gross_amount",
                                              "discount_amount", "order_discount_share", "tax_code_id", "tax_code", "tax_rate", "tax_amount", "line_total", "returned_quantity", "is_service", "price_changed")},
            "promotion_name": None, "unit_cost": line.unit_cost if actor.sees_cost else None, "cost_total": line.cost_total if actor.sees_cost else None,
            "available": Decimal(0) if line.is_service else await _available(db, line.location_id or location, line.product_id),
        })
    return {
        **{f: getattr(sale, f) for f in ("id", "receipt_no", "branch_id", "terminal_id", "session_id", "cashier_id", "salesperson_id", "customer_id", "customer_name", "status", "payment_status",
                                         "fulfilment_status", "currency", "subtotal", "discount_total", "tax_total", "rounding", "grand_total", "paid_total", "refunded_total", "exchange_rate",
                                         "order_discount", "coupon_code", "hold_label", "business_date", "created_at", "finalized_at", "reprint_count", "cancel_reason", "void_reason", "voided_by",
                                         "invoice_no", "loyalty_earned", "version", "notices")},
        "branch_name": branch.name_en if branch else "", "terminal_name": terminal.name if terminal else "", "cashier_name": cashier.full_name if cashier else "",
        "balance": max(sale.grand_total - sale.paid_total, Decimal(0)) if sale.status not in ("FINALIZED", "VOIDED", "CANCELLED") else Decimal(0),
        "grand_total_khr": round_khr(sale.grand_total * sale.exchange_rate, increment) if sale.exchange_rate else None,
        "lines": line_views, "payments": [payment_view(p) for p in await _payments(db, sale.id, fresh=True)], "return_ids": returns,
    }


def _in_scope(actor: Principal, sale: Sale) -> bool:
    if not actor.has_branch(sale.branch_id):
        return False
    if actor.can("sales.sale.view_all") or sale.cashier_id == actor.user_id:
        return True
    # Held sales can be resumed by any POS user of the branch; finalized ones can be looked up for returns.
    return sale.status == "HELD" or (sale.status in ("FINALIZED", "VOIDED") and actor.can("sales.return.create"))


async def get_sale(db: AsyncSession, actor: Principal, sale_id: uuid.UUID, *, lock: bool = False) -> Sale:
    query = select(Sale).where(Sale.id == sale_id, Sale.company_id == actor.company_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    sale = await db.scalar(query)
    if sale is None or not _in_scope(actor, sale):
        raise NotFound("Sale")
    return sale


async def list_sales(db: AsyncSession, actor: Principal, *, q: str | None, status: str | None, branch_id: uuid.UUID | None, terminal_id: uuid.UUID | None, cashier_id: uuid.UUID | None,
                     date_from=None, date_to=None, limit: int, offset: int) -> tuple[list[dict], int]:
    query = select(Sale).where(Sale.company_id == actor.company_id)
    if actor.branch_ids is not None:
        query = query.where(Sale.branch_id.in_(actor.branch_ids))
    exact_receipt = bool(q) and actor.can("sales.return.create")
    if not actor.can("sales.sale.view_all"):
        # Without view_all a user sees their own sales, plus an exact receipt lookup for returns.
        query = query.where(or_(Sale.cashier_id == actor.user_id, Sale.receipt_no == q) if exact_receipt else Sale.cashier_id == actor.user_id)
    if q:
        query = query.where(or_(Sale.receipt_no.ilike(f"%{q}%"), Sale.invoice_no.ilike(f"%{q}%")))
    for column, value in ((Sale.status, status), (Sale.branch_id, branch_id), (Sale.terminal_id, terminal_id), (Sale.cashier_id, cashier_id)):
        if value is not None:
            query = query.where(column == value)
    if date_from:
        query = query.where(Sale.business_date >= date_from)
    if date_to:
        query = query.where(Sale.business_date <= date_to)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = await db.scalars(query.order_by(Sale.created_at.desc()).limit(limit).offset(offset))
    return [await sale_view(db, actor, x) for x in rows], total


async def held_sales(db: AsyncSession, actor: Principal) -> list[dict]:
    terminal = await cash_sessions.current_terminal(db, actor)
    rows = await db.scalars(select(Sale).where(Sale.company_id == actor.company_id, Sale.branch_id == terminal.branch_id, Sale.status == "HELD").order_by(Sale.updated_at.desc()))
    return [await sale_view(db, actor, x) for x in rows]


async def current_sale(db: AsyncSession, actor: Principal) -> dict | None:
    terminal = await cash_sessions.current_terminal(db, actor)
    sale = await db.scalar(select(Sale).where(Sale.terminal_id == terminal.id, Sale.cashier_id == actor.user_id, Sale.status.in_(("DRAFT", "PENDING_PAYMENT"))).order_by(Sale.created_at.desc()).limit(1))
    return await sale_view(db, actor, sale) if sale else None


# Creating and pricing

async def create_sale(db: AsyncSession, actor: Principal) -> dict:
    terminal = await cash_sessions.current_terminal(db, actor)
    await release_expired(db, actor.company_id)
    session = await cash_sessions.open_session_for(db, actor, terminal.id)
    from app.services.org import current_rate

    rate = await current_rate(db, actor.company_id)
    settings = await _settings(db, actor.company_id)
    sale = Sale(company_id=actor.company_id, branch_id=terminal.branch_id, terminal_id=terminal.id, session_id=session.id if session else None, cashier_id=actor.user_id,
                exchange_rate=rate.rate if rate else None, tax_inclusive=bool(settings.get("tax_inclusive", False)), notices=[])
    db.add(sale)
    await db.flush()
    await db.commit()
    return await sale_view(db, actor, sale)


async def _sellable(db: AsyncSession, actor: Principal, product: Product | None, branch_id: uuid.UUID) -> Product:
    if product is None or product.company_id != actor.company_id or product.deleted_at is not None:
        raise NotFound("Product")
    if product.status != "ACTIVE" or product.type == "VARIANT_PARENT":
        raise AppError(f"{product.name_en} is not available for sale.", code="PRODUCT_NOT_SELLABLE", status_code=422)
    setting = await db.get(ProductBranchSetting, (product.id, branch_id))
    if setting is not None and not setting.active:
        raise AppError(f"{product.name_en} is not sold at this branch.", code="PRODUCT_NOT_SELLABLE", status_code=422)
    return product


def _check_qty(product: Product, quantity: Decimal, unit_is_base: bool) -> None:
    places = product.precision if (product.allow_fraction and unit_is_base) else 0
    if quantity != quantity.quantize(Decimal(1).scaleb(-places)):
        raise ValidationFailed("quantity", f"{product.sku} is sold in whole units." if places == 0 else f"{product.sku} allows {places} decimal places.")


async def _new_line(db: AsyncSession, sale: Sale, product: Product, unit_id: uuid.UUID, quantity: Decimal, line_no: int, location_id: uuid.UUID | None) -> SaleLine:
    factor = await pricing.unit_factor(db, product, unit_id)
    if factor is None:
        raise ValidationFailed("unit_id", f"{product.sku} is not sold in this unit.")
    _check_qty(product, quantity, unit_id == product.base_unit_id)
    unit = await db.get(Unit, unit_id)
    assert unit is not None
    line = SaleLine(sale_id=sale.id, line_no=line_no, product_id=product.id, sku=product.sku, name_en=product.name_en, name_km=product.name_km, unit_id=unit_id, unit_code=unit.code,
                    factor=factor, quantity=quantity, quantity_base=quantity * factor, allow_fraction=product.allow_fraction, precision=product.precision,
                    is_service=product.type == "SERVICE", list_price=Decimal(0), unit_price=Decimal(0), price_source="STANDARD", location_id=None if product.type == "SERVICE" else location_id)
    db.add(line)
    return line


async def reprice(db: AsyncSession, sale: Sale, lines: list[SaleLine], *, mark_changes: bool) -> list[str]:
    """Recomputes every amount from server data. Returns notices for prices that changed."""
    notices: list[str] = []
    settings = await _settings(db, sale.company_id)
    sale.tax_inclusive = bool(settings.get("tax_inclusive", False))
    customer = await db.get(Customer, sale.customer_id) if sale.customer_id else None
    group_id = customer.group_id if customer else None
    for line in lines:
        product = await db.get(Product, line.product_id)
        assert product is not None
        resolved = await pricing.resolve(db, product, line.unit_id, branch_id=sale.branch_id, customer_group_id=group_id)
        if resolved.price is None:
            raise AppError(f"{product.name_en} has no price for {line.unit_code}.", code="NO_PRICE", status_code=422)
        base_source = (resolved.source or "RETAIL").replace("_BASE_UNIT", "")
        old_price = line.unit_price
        line.list_price = resolved.price
        if line.override_price is not None:
            line.unit_price, line.price_source, line.price_explanation = line.override_price, "OVERRIDE", f"Override of {resolved.price.normalize()}: {line.override_reason}"
        else:
            line.unit_price, line.price_source = resolved.price, PRICE_SOURCE.get(base_source, "STANDARD")
            line.price_explanation = {"BRANCH": "Branch price", "CUSTOMER_GROUP": "Customer group price"}.get(base_source, "Retail price") + (" (from base unit)" if "BASE_UNIT" in (resolved.source or "") else "")
        if mark_changes and old_price and old_price != line.unit_price:
            line.price_changed = True
            notices.append(f"{line.name_en}: price changed from {old_price.normalize()} to {line.unit_price.normalize()}")
        tax = await db.get(TaxCode, product.tax_code_id) if product.tax_code_id else None
        line.tax_code_id, line.tax_code, line.tax_rate = (tax.id, tax.code, tax.rate) if tax and tax.status == "ACTIVE" else (None, "", Decimal(0))
        line.gross_amount = cents(line.unit_price * line.quantity)
        disc = line.line_discount
        if disc:
            value = Decimal(str(disc["value"]))
            line.discount_amount = cents(line.gross_amount * value / 100) if disc["type"] == "PERCENT" else min(cents(value), line.gross_amount)
        else:
            line.discount_amount = Decimal(0)

    base = sum((ln.gross_amount - ln.discount_amount for ln in lines), Decimal(0))
    order = sale.order_discount
    order_amount = Decimal(0)
    if order and base > 0:
        value = Decimal(str(order["value"]))
        order_amount = cents(base * value / 100) if order["type"] == "PERCENT" else min(cents(value), base)
    remaining = order_amount
    shareable = [ln for ln in lines if ln.gross_amount - ln.discount_amount > 0]
    for line in lines:
        if line not in shareable or order_amount == 0:
            line.order_discount_share = Decimal(0)
            continue
        if line is shareable[-1]:
            share = remaining
        else:
            share = cents(order_amount * (line.gross_amount - line.discount_amount) / base)
        line.order_discount_share, remaining = share, remaining - share

    for line in lines:
        net = line.gross_amount - line.discount_amount - line.order_discount_share
        if sale.tax_inclusive:
            line.tax_amount = cents(net - net / (1 + line.tax_rate / 100))
            line.line_total = net
        else:
            line.tax_amount = cents(net * line.tax_rate / 100)
            line.line_total = net + line.tax_amount
    sale.subtotal = sum((ln.gross_amount for ln in lines), Decimal(0))
    sale.discount_total = sum((ln.discount_amount + ln.order_discount_share for ln in lines), Decimal(0))
    sale.tax_total = sum((ln.tax_amount for ln in lines), Decimal(0))
    sale.grand_total = sum((ln.line_total for ln in lines), Decimal(0))
    return notices


async def _below_minimum(db: AsyncSession, line: SaleLine) -> bool:
    product = await db.get(Product, line.product_id)
    if product is None or product.min_selling_price is None or line.quantity_base == 0:
        return False
    net = line.gross_amount - line.discount_amount - line.order_discount_share
    return net / line.quantity_base < product.min_selling_price


async def _approver_name(db: AsyncSession, approval) -> str | None:
    user = await db.get(User, approval.approver_id)
    return user.full_name if user else None


async def apply_ops(db: AsyncSession, actor: Principal, sale_id: uuid.UUID, data: s.SaleOps) -> dict:
    sale = await get_sale(db, actor, sale_id, lock=True)
    actor.require("pos.sale.create", "pos.sale.hold")
    lines = await _lines(db, sale.id)
    terminal = await db.get(PosTerminal, sale.terminal_id)
    location_id = terminal.default_location_id if terminal else None
    sale.notices = []
    line_ops = {"add_barcode", "add_product", "set_quantity", "set_unit", "remove_line", "line_discount", "order_discount", "override_price"}
    for op in data.ops:
        if op.type == "resume":
            if sale.status != "HELD":
                raise InvalidStateTransition("Only held sales can be resumed.")
            current = await cash_sessions.current_terminal(db, actor)
            if current.branch_id != sale.branch_id:
                raise Forbidden("Held sales can be resumed only at the same branch.")
            session = await cash_sessions.open_session_for(db, actor, current.id)
            sale.status, sale.terminal_id, sale.cashier_id, sale.session_id, sale.hold_label = "DRAFT", current.id, actor.user_id, session.id if session else None, None
            location_id = current.default_location_id
            for line in lines:
                if not line.is_service:
                    line.location_id = location_id
            sale.notices = await reprice(db, sale, lines, mark_changes=True)  # BR-POS-003
            continue
        if sale.status not in EDITABLE:
            raise InvalidStateTransition(f"A {sale.status.lower().replace('_', ' ')} sale cannot be changed.")
        if sale.cashier_id != actor.user_id:
            raise Forbidden("Only the cashier who owns this sale can change it.")
        payments = await _payments(db, sale.id)
        if op.type in line_ops and any(p.status in ("PENDING", *COMPLETED) for p in payments):
            raise AppError("Payments have started on this sale. Finish or remove them before changing items.", code="PAYMENTS_STARTED", status_code=409)

        if op.type in ("add_barcode", "add_product"):
            if op.type == "add_barcode":
                barcode = await db.scalar(select(ProductBarcode).where(ProductBarcode.company_id == actor.company_id, ProductBarcode.barcode == op.barcode.strip(), ProductBarcode.active))
                if barcode is None:
                    raise NotFound("Product for this barcode")
                product, unit_id, qty = await db.get(Product, barcode.product_id), barcode.unit_id, Decimal(1)
            else:
                product, qty = await db.get(Product, op.product_id), op.quantity
                unit_id = op.unit_id
            product = await _sellable(db, actor, product, sale.branch_id)
            if unit_id is None:
                unit_id = product.base_unit_id
            existing = next((ln for ln in lines if ln.product_id == product.id and ln.unit_id == unit_id and ln.override_price is None and not ln.line_discount), None)
            if existing is not None:  # repeated scans increase the quantity (FR-POS-001)
                new_qty = existing.quantity + qty
                _check_qty(product, new_qty, unit_id == product.base_unit_id)
                existing.quantity, existing.quantity_base = new_qty, new_qty * existing.factor
            else:
                lines.append(await _new_line(db, sale, product, unit_id, qty, max((ln.line_no for ln in lines), default=0) + 1, location_id))
        elif op.type == "set_quantity":
            line = _find(lines, op.line_id)
            product = await db.get(Product, line.product_id)
            assert product is not None
            _check_qty(product, op.quantity, line.unit_id == product.base_unit_id)
            line.quantity, line.quantity_base = op.quantity, op.quantity * line.factor
        elif op.type == "set_unit":
            line = _find(lines, op.line_id)
            product = await db.get(Product, line.product_id)
            assert product is not None
            factor = await pricing.unit_factor(db, product, op.unit_id)
            if factor is None:
                raise ValidationFailed("unit_id", f"{product.sku} is not sold in this unit.")
            unit = await db.get(Unit, op.unit_id)
            _check_qty(product, line.quantity, op.unit_id == product.base_unit_id)
            line.unit_id, line.unit_code, line.factor, line.quantity_base, line.override_price, line.override_reason, line.override_approved_by = op.unit_id, unit.code if unit else "", factor, line.quantity * factor, None, None, None
        elif op.type == "remove_line":
            line = _find(lines, op.line_id)
            lines.remove(line)
            await db.delete(line)
        elif op.type == "line_discount":
            line = _find(lines, op.line_id)
            line.line_discount = None if op.value == 0 else {"type": op.discount_type, "value": str(op.value), "reason": op.reason, "source": "MANUAL", "approved_by": None}
            await db.flush()
            await reprice(db, sale, lines, mark_changes=False)
            if line.line_discount:
                pct = line.discount_amount / line.gross_amount * 100 if line.gross_amount else Decimal(0)
                approved = await _discount_approval(db, actor, op.approval_token, pct, below_min=await _below_minimum(db, line))
                line.line_discount = {**line.line_discount, "approved_by": approved}
        elif op.type == "order_discount":
            sale.order_discount = None if op.value == 0 else {"type": op.discount_type, "value": str(op.value), "reason": op.reason, "source": "MANUAL", "approved_by": None}
            await db.flush()
            await reprice(db, sale, lines, mark_changes=False)
            if sale.order_discount:
                base = sum((ln.gross_amount - ln.discount_amount for ln in lines), Decimal(0))
                order_amount = sum((ln.order_discount_share for ln in lines), Decimal(0))
                pct = order_amount / base * 100 if base else Decimal(0)
                below = any([await _below_minimum(db, ln) for ln in lines])
                approved = await _discount_approval(db, actor, op.approval_token, pct, below_min=below)
                sale.order_discount = {**sale.order_discount, "approved_by": approved}
        elif op.type == "override_price":
            line = _find(lines, op.line_id)
            reduction = max((line.list_price or line.unit_price) - op.price, Decimal(0)) * line.quantity
            line.override_price, line.override_reason, line.override_approved_by = op.price, op.reason, None
            await db.flush()
            await reprice(db, sale, lines, mark_changes=False)
            within_own = actor.can("pos.price.override") and reduction <= actor.limits.get("override_amount", Decimal(0)) and not await _below_minimum(db, line)
            if not within_own:
                approval = await approvals.consume(db, actor, token=op.approval_token, action="PRICE_OVERRIDE", amount=cents(reduction),
                                                   message="A price override needs supervisor approval.")
                line.override_approved_by = await _approver_name(db, approval)
            else:
                line.override_approved_by = actor.full_name
        elif op.type == "set_customer":
            if op.customer_id is None:
                sale.customer_id, sale.customer_name = None, None
            else:
                customer = await db.get(Customer, op.customer_id)
                if customer is None or customer.company_id != actor.company_id or customer.status != "ACTIVE":
                    raise NotFound("Customer")
                sale.customer_id, sale.customer_name = customer.id, customer.name
        elif op.type == "apply_coupon":
            if op.code:
                raise ValidationFailed("code", "Coupons arrive with promotions (Phase 8).")
            sale.coupon_code = None
        elif op.type == "hold":
            actor.require("pos.sale.hold")
            if not lines:
                raise ValidationFailed("lines", "There is nothing to hold.")
            if any(p.status in ("PENDING", *COMPLETED) for p in payments):
                raise AppError("A sale with payments cannot be held.", code="PAYMENTS_STARTED", status_code=409)
            sale.status, sale.hold_label = "HELD", op.label or f"Held {_now():%H:%M}"
    await db.flush()
    if sale.status in ("DRAFT", "HELD"):
        await reprice(db, sale, lines, mark_changes=False)
    await db.flush()
    await db.commit()
    return await sale_view(db, actor, sale)


def _find(lines: list[SaleLine], line_id: uuid.UUID) -> SaleLine:
    for line in lines:
        if line.id == line_id:
            return line
    raise NotFound("Sale line")


async def _discount_approval(db: AsyncSession, actor: Principal, token: str | None, pct: Decimal, *, below_min: bool) -> str | None:
    """Within the user's own limit no approval is needed; above it, or below a minimum price, a supervisor approves (BR-POS-004)."""
    own_limit = actor.limits.get("discount_pct", Decimal(0)) if actor.can("pos.discount.apply") else Decimal(-1)
    if pct <= own_limit and not below_min:
        return None
    approval = await approvals.consume(db, actor, token=token, action="DISCOUNT", amount=pct.quantize(Decimal("0.01"), ROUND_HALF_UP),
                                       message="This discount is above your limit." if not below_min else "This discount takes the price below the minimum selling price.")
    return await _approver_name(db, approval)


# Payments

def _derive_payment_status(sale: Sale) -> None:
    if sale.status in ("FINALIZED", "VOIDED"):
        if sale.refunded_total > 0 and sale.refunded_total >= sale.paid_total:
            sale.payment_status = "REFUNDED"
        elif sale.refunded_total > 0:
            sale.payment_status = "PARTIALLY_REFUNDED"
        else:
            sale.payment_status = "PAID" if sale.paid_total >= sale.grand_total else "PARTIALLY_PAID"
    else:
        sale.payment_status = "UNPAID" if sale.paid_total == 0 else ("PAID" if sale.paid_total >= sale.grand_total else "PARTIALLY_PAID")


async def recalc_paid(db: AsyncSession, sale: Sale) -> None:
    payments = await _payments(db, sale.id)
    sale.paid_total = sum((p.amount_applied for p in payments if p.status in COMPLETED), Decimal(0))
    sale.rounding = sum((p.rounding_amount for p in payments if p.status in COMPLETED), Decimal(0))
    sale.refunded_total = Decimal(await db.scalar(select(func.coalesce(func.sum(Refund.amount_applied), 0)).where(Refund.sale_id == sale.id, Refund.status == "COMPLETED")) or 0)
    _derive_payment_status(sale)


async def add_payment(db: AsyncSession, actor: Principal, sale_id: uuid.UUID, data: s.PaymentIn) -> dict:
    actor.require("pos.sale.create")
    sale = await get_sale(db, actor, sale_id, lock=True)
    if sale.status not in ("DRAFT", "PENDING_PAYMENT"):
        raise InvalidStateTransition(f"A {sale.status.lower().replace('_', ' ')} sale cannot take payments.")
    if sale.cashier_id != actor.user_id:
        raise Forbidden("Only the cashier who owns this sale can take payment.")
    await release_expired(db, actor.company_id)
    lines = await _lines(db, sale.id)
    if not lines:
        raise ValidationFailed("lines", "Add items before taking payment.")
    session = await cash_sessions.require_open_session(db, actor, sale.terminal_id)
    method = await db.scalar(select(PaymentMethod).where(PaymentMethod.company_id == actor.company_id, PaymentMethod.code == data.method))
    if method is None or method.status != "ACTIVE":
        raise ValidationFailed("method", f"{data.method.replace('_', ' ').title()} payments are not enabled.")
    if data.method == "STORE_CREDIT":
        raise ValidationFailed("method", "Store credit arrives with customers (Phase 6).")
    await reprice(db, sale, lines, mark_changes=False)
    await recalc_paid(db, sale)
    balance = sale.grand_total - sale.paid_total
    if balance <= 0:
        raise Conflict("This sale is already fully paid.", code="ALREADY_PAID")
    settings = await _settings(db, actor.company_id)
    increment = Decimal(str(settings.get("khr_cash_increment", "100")))
    needs_rate = data.currency == "KHR" or (data.change_currency or data.currency) == "KHR"
    rate = sale.exchange_rate
    if needs_rate and not rate:
        raise ValidationFailed("currency", "Set a USD to KHR exchange rate before taking riel.")
    rate = rate or Decimal(1)
    tendered = data.amount_tendered
    change_currency = data.change_currency or data.currency
    applied, change, rounding = Decimal(0), Decimal(0), Decimal(0)
    status, completed_at = "COMPLETED", _now()
    reference = data.reference or None

    if data.method == "CASH":
        if data.currency == "KHR":
            due_khr = round_khr(balance * rate, increment)
            if tendered >= due_khr:
                applied, rounding, change_tender = balance, four(due_khr / rate - balance), tendered - due_khr
            else:
                applied, change_tender = min(cents(tendered / rate), balance), Decimal(0)
        else:
            applied, change_tender = min(tendered, balance), max(tendered - balance, Decimal(0))
        # Change only from cash (BR-PAY-005), in the currency the customer wants.
        if change_tender > 0 and change_currency != data.currency:
            if change_currency == "KHR":
                exact = change_tender * rate
                change = round_khr(exact, increment)
                rounding += four((exact - change) / rate)
            else:
                exact = change_tender / rate
                change = cents(exact)
                rounding += four(exact - change)
        else:
            change = change_tender
    else:
        if data.change_currency and data.change_currency != data.currency:
            raise ValidationFailed("change_currency", "Change is given only for cash.")
        in_sale_currency = tendered if data.currency == "USD" else tendered / rate
        if cents(in_sale_currency) > balance:
            raise ValidationFailed("amount_tendered", f"A {data.method.lower().replace('_', ' ')} payment cannot exceed the balance of {balance.normalize()} USD.")
        applied = min(cents(in_sale_currency), balance)
        confirmation = (data.approval_code or reference) if data.method == "CARD" else reference
        if confirmation:
            reference = reference or data.approval_code
        else:
            # No integration yet: the payment waits until the cashier confirms it with the terminal or bank reference (BR-PAY-004).
            status, completed_at = "PENDING", None
    payment = SalePayment(
        company_id=actor.company_id, sale_id=sale.id, session_id=session.id, terminal_id=sale.terminal_id, method=data.method, currency=data.currency, amount_tendered=tendered,
        exchange_rate=rate if data.currency != "USD" or change_currency != "USD" else Decimal(1), amount_applied=applied, change_amount=change, change_currency=change_currency,
        rounding_amount=rounding, status=status, provider=data.provider or (method.provider or None), reference=reference, approval_code=data.approval_code, card_last4=data.card_last4,
        business_date=stock.business_date(await db.get(Branch, sale.branch_id)), user_id=actor.user_id, completed_at=completed_at,
    )
    db.add(payment)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("This payment reference has already been used.", code="DUPLICATE_PAYMENT_REFERENCE") from exc
    if status == "PENDING" and sale.status == "DRAFT":
        sale.status = "PENDING_PAYMENT"
        await _reserve(db, actor, sale, lines)
    sale.session_id = session.id
    await recalc_paid(db, sale)
    await record_audit(db, actor, "PAYMENT_RECORDED", "PAY", "sale", sale.id, after={"method": data.method, "currency": data.currency, "tendered": str(tendered), "applied": str(applied), "status": status},
                       branch_id=sale.branch_id)
    await db.commit()
    return await sale_view(db, actor, sale)


async def resolve_payment(db: AsyncSession, actor: Principal, sale_id: uuid.UUID, payment_id: uuid.UUID, data: s.PaymentResolve) -> dict:
    actor.require("pos.sale.create")
    sale = await get_sale(db, actor, sale_id, lock=True)
    payment = await db.scalar(select(SalePayment).where(SalePayment.id == payment_id, SalePayment.sale_id == sale.id).with_for_update())
    if payment is None:
        raise NotFound("Payment")
    if payment.status != "PENDING":
        raise InvalidStateTransition("Only pending payments can be resolved.")
    if data.outcome == "COMPLETED":
        if not (data.reference or payment.reference):
            raise ValidationFailed("reference", "Enter the provider or bank reference that confirms this payment.")
        payment.reference = data.reference or payment.reference
        payment.status, payment.completed_at = "COMPLETED", _now()
    else:
        payment.status, payment.failure_reason = data.outcome, data.reason or ("Declined" if data.outcome == "FAILED" else "Cancelled before confirmation")
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("This payment reference has already been used.", code="DUPLICATE_PAYMENT_REFERENCE") from exc
    if not await db.scalar(select(SalePayment.id).where(SalePayment.sale_id == sale.id, SalePayment.status == "PENDING").limit(1)):
        await release_reservations(db, sale.id)
        if sale.status == "PENDING_PAYMENT":
            sale.status = "DRAFT"
    await recalc_paid(db, sale)
    await record_audit(db, actor, f"PAYMENT_{data.outcome}", "PAY", "sale", sale.id, after={"payment_id": str(payment.id), "reference": payment.reference, "reason": payment.failure_reason}, branch_id=sale.branch_id)
    await db.commit()
    return await sale_view(db, actor, sale)


# Reservations (BR-INV-009, D-07)

async def _reserve(db: AsyncSession, actor: Principal, sale: Sale, lines: list[SaleLine]) -> None:
    targets = [ln for ln in lines if not ln.is_service and ln.location_id]
    if not targets:
        return
    locations = {ln.location_id: await db.get(WarehouseLocation, ln.location_id) for ln in targets}
    balances = await stock.lock_balances(db, actor.company_id, [(locations[ln.location_id], ln.product_id, "") for ln in targets])
    settings = await _settings(db, actor.company_id)
    expires = _now() + timedelta(minutes=RESERVATION_MINUTES)
    for line in targets:
        balance = balances[(line.location_id, line.product_id, "")]
        if balance.on_hand - balance.reserved < line.quantity_base and not settings.get("negative_stock_allowed"):
            raise stock.InsufficientStock(f"Not enough {line.sku} to hold for this payment: {(balance.on_hand - balance.reserved).normalize()} available.",
                                          details=[{"product_id": str(line.product_id), "sku": line.sku, "available": str(balance.on_hand - balance.reserved), "requested": str(line.quantity_base)}])
        balance.reserved += line.quantity_base
        db.add(StockReservation(company_id=actor.company_id, sale_id=sale.id, sale_line_id=line.id, location_id=line.location_id, product_id=line.product_id,
                                quantity_base=line.quantity_base, expires_at=expires))
    await db.flush()


async def release_reservations(db: AsyncSession, sale_id: uuid.UUID, status: str = "RELEASED") -> None:
    reservations = list(await db.scalars(select(StockReservation).where(StockReservation.sale_id == sale_id, StockReservation.status == "ACTIVE").with_for_update()))
    for r in sorted(reservations, key=lambda r: (str(r.location_id), str(r.product_id))):
        balance = await db.scalar(select(InventoryBalance).where(InventoryBalance.location_id == r.location_id, InventoryBalance.product_id == r.product_id, InventoryBalance.batch_no == "").with_for_update())
        if balance is not None:
            balance.reserved = max(balance.reserved - r.quantity_base, Decimal(0))
        r.status = status
    await db.flush()


async def release_expired(db: AsyncSession, company_id: uuid.UUID) -> int:
    """Expired reservations stop reducing availability (BR-INV-009). Also run by the worker in Phase 8."""
    sale_ids = set(await db.scalars(select(StockReservation.sale_id).where(StockReservation.company_id == company_id, StockReservation.status == "ACTIVE", StockReservation.expires_at < _now())))
    for sale_id in sale_ids:
        await release_reservations(db, sale_id)
    return len(sale_ids)


# Finalize, cancel, void

async def finalize(db: AsyncSession, actor: Principal, sale_id: uuid.UUID) -> dict:
    actor.require("pos.sale.create")
    sale = await get_sale(db, actor, sale_id, lock=True)
    if sale.status == "FINALIZED":
        raise AppError(f"This sale is already finalized as {sale.receipt_no}.", code="ALREADY_FINALIZED", status_code=409, details=[{"receipt_no": sale.receipt_no}])
    if sale.status not in ("DRAFT", "PENDING_PAYMENT"):
        raise InvalidStateTransition(f"A {sale.status.lower().replace('_', ' ')} sale cannot be finalized.")
    if sale.cashier_id != actor.user_id:
        raise Forbidden("Only the cashier who owns this sale can finalize it.")
    session = await cash_sessions.require_open_session(db, actor, sale.terminal_id)
    lines = await _lines(db, sale.id)
    if not lines:
        raise ValidationFailed("lines", "A sale needs at least one item.")  # BR-SAL-002
    if await db.scalar(select(SalePayment.id).where(SalePayment.sale_id == sale.id, SalePayment.status == "PENDING").limit(1)):
        raise AppError("A payment is still pending. Confirm or cancel it first.", code="PAYMENT_PENDING", status_code=409)
    for line in lines:
        await _sellable(db, actor, await db.get(Product, line.product_id), sale.branch_id)
    previous = {ln.id: ln.unit_price for ln in lines}
    before_total = sale.grand_total
    notices = await reprice(db, sale, lines, mark_changes=True)
    if any(previous[ln.id] != ln.unit_price for ln in lines) or sale.grand_total != before_total:
        sale.notices = notices or ["Totals were recalculated."]
        await db.commit()  # the re-priced sale is saved so the cashier sees the new total
        raise AppError("Prices changed since the items were added. Review the new total.", code="PRICES_CHANGED", status_code=409, details=[{"message": n} for n in sale.notices])
    await recalc_paid(db, sale)
    if sale.paid_total < sale.grand_total:
        raise AppError(f"{(sale.grand_total - sale.paid_total).normalize()} USD is still due.", code="BALANCE_DUE", status_code=409)  # partial payments are off (D-11)

    await release_reservations(db, sale.id, status="CONSUMED")
    moves = []
    for line in lines:
        if line.is_service:
            continue
        product = await db.get(Product, line.product_id)
        location = await db.get(WarehouseLocation, line.location_id) if line.location_id else None
        if location is None:
            raise AppError("This terminal has no sellable location.", code="CONFIGURATION_ERROR", status_code=422)
        moves.append(stock.Move(product, line.quantity_base, "SALE", "SALE", str(sale.id), str(line.id), from_location=location, unit_id=line.unit_id, quantity_entered=line.quantity))
    movements = await stock.post(db, actor, moves)
    by_line = {m.source_line_id: m for m in movements}
    for line in lines:
        movement = by_line.get(str(line.id))
        line.unit_cost = movement.unit_cost if movement else Decimal(0)
        line.cost_total = movement.total_cost if movement else Decimal(0)
    branch = await db.get(Branch, sale.branch_id)
    sale.receipt_no = await next_number(db, actor.company_id, "RECEIPT", branch_code=branch.code if branch else None)
    sale.status, sale.finalized_at, sale.session_id, sale.notices = "FINALIZED", _now(), session.id, []
    sale.business_date = stock.business_date(branch)
    if sale.customer_id:
        sale.loyalty_earned = await customers.record_purchase(db, sale.customer_id, sale.grand_total, await _settings(db, actor.company_id))
    _derive_payment_status(sale)
    db.add(OutboxEvent(event_type="SALE_FINALIZED", payload={"sale_id": str(sale.id), "receipt_no": sale.receipt_no, "terminal_id": str(sale.terminal_id)}))
    await record_audit(db, actor, "SALE_FINALIZED", "SAL", "sale", sale.id, after={"receipt_no": sale.receipt_no, "total": str(sale.grand_total), "lines": len(lines)}, branch_id=sale.branch_id)
    await db.commit()
    return await sale_view(db, actor, sale)


async def cancel(db: AsyncSession, actor: Principal, sale_id: uuid.UUID, data: s.SaleCancel) -> dict:
    sale = await get_sale(db, actor, sale_id, lock=True)
    if sale.status not in ("DRAFT", "HELD", "PENDING_PAYMENT"):
        raise InvalidStateTransition(f"A {sale.status.lower()} sale cannot be cancelled. Use void or return.")
    lines = await _lines(db, sale.id)
    approved_by = None
    if lines:
        # Cancelling a sale with items needs a different authorised user (BR-POS-004).
        approval = await approvals.consume(db, actor, token=data.approval_token, action="CANCEL_SALE", amount=sale.grand_total, message="Cancelling a sale with items needs supervisor approval.")
        approved_by = await _approver_name(db, approval)
    payments = await _payments(db, sale.id)
    if any(p.status in COMPLETED and p.method != "CASH" for p in payments):
        raise AppError("Refund the completed card, QR or transfer payments through the provider first.", code="PAYMENT_REFUND_REQUIRED", status_code=409)
    branch = await db.get(Branch, sale.branch_id)
    increment = Decimal(str((await _settings(db, actor.company_id)).get("khr_cash_increment", "100")))
    for payment in payments:
        if payment.status == "PENDING":
            payment.status, payment.failure_reason = "CANCELLED", "Sale cancelled"
        elif payment.status in COMPLETED and payment.method == "CASH":
            # Cash taken before cancelling goes back to the customer from the same drawer, in the currency it was paid in.
            amount = payment.amount_applied if payment.currency == "USD" else round_khr(payment.amount_applied * payment.exchange_rate, increment)
            db.add(Refund(company_id=actor.company_id, sale_id=sale.id, sale_payment_id=payment.id, kind="CANCEL", method="CASH", currency=payment.currency, amount=amount,
                          amount_applied=payment.amount_applied, status="COMPLETED", session_id=payment.session_id, user_id=actor.user_id, business_date=stock.business_date(branch), completed_at=_now()))
            payment.status, payment.refunded_amount = "REFUNDED", payment.amount_applied
    await release_reservations(db, sale.id)
    sale.status, sale.cancel_reason = "CANCELLED", data.reason
    await db.flush()
    await recalc_paid(db, sale)
    await record_audit(db, actor, "SALE_CANCELLED", "SAL", "sale", sale.id, after={"reason": data.reason, "approved_by": approved_by, "lines": len(lines)}, branch_id=sale.branch_id, flagged=bool(lines))
    await db.commit()
    return await sale_view(db, actor, sale)


async def void(db: AsyncSession, actor: Principal, sale_id: uuid.UUID, data: s.SaleCancel) -> dict:
    sale = await get_sale(db, actor, sale_id, lock=True)
    if sale.status != "FINALIZED":
        raise InvalidStateTransition("Only finalized sales can be voided.")
    session = await db.get(cash_sessions.CashierSession, sale.session_id) if sale.session_id else None
    if session is None or session.status != "OPEN":
        raise AppError("Voids are allowed only while the sale's cashier session is open. Use a return instead.", code="SESSION_CLOSED", status_code=409)  # BR-SAL-003
    if await db.scalar(select(SalesReturn.id).where(SalesReturn.original_sale_id == sale.id).limit(1)):
        raise Conflict("This sale has returns; it cannot be voided.", code="HAS_RETURNS")
    approval = await approvals.consume(db, actor, token=data.approval_token, action="VOID_SALE", amount=sale.grand_total, message="Voiding a sale needs approval from another authorised user.")
    approved_by = await _approver_name(db, approval)
    lines = await _lines(db, sale.id)
    moves = []
    for line in lines:
        if line.is_service or line.location_id is None:
            continue
        product = await db.get(Product, line.product_id)
        location = await db.get(WarehouseLocation, line.location_id)
        moves.append(stock.Move(product, line.quantity_base, "SALE_VOID", "SALE_VOID", str(sale.id), str(line.id), to_location=location, unit_cost=line.unit_cost or Decimal(0),
                                source_no=sale.receipt_no or "", reason=data.reason, approved_by=approved_by, unit_id=line.unit_id, quantity_entered=line.quantity))
    await stock.post(db, actor, moves)
    branch = await db.get(Branch, sale.branch_id)
    settings = await _settings(db, actor.company_id)
    increment = Decimal(str(settings.get("khr_cash_increment", "100")))
    for payment in await _payments(db, sale.id):
        if payment.status not in COMPLETED or payment.amount_applied <= payment.refunded_amount:
            continue
        remaining = payment.amount_applied - payment.refunded_amount
        amount = remaining if payment.currency == "USD" else round_khr(remaining * payment.exchange_rate, increment)
        cash = payment.method == "CASH"
        db.add(Refund(company_id=actor.company_id, sale_id=sale.id, sale_payment_id=payment.id, kind="VOID", method=payment.method, currency=payment.currency, amount=amount,
                      amount_applied=remaining, status="COMPLETED" if cash else "PENDING", session_id=session.id if cash else None, user_id=actor.user_id,
                      business_date=stock.business_date(branch), completed_at=_now() if cash else None))
        if cash:
            payment.refunded_amount, payment.status = payment.amount_applied, "REFUNDED"
    sale.status, sale.void_reason, sale.voided_by, sale.voided_at = "VOIDED", data.reason, approved_by, _now()
    await db.flush()
    await recalc_paid(db, sale)
    await record_audit(db, actor, "SALE_VOIDED", "SAL", "sale", sale.id, after={"receipt_no": sale.receipt_no, "reason": data.reason, "approved_by": approved_by, "total": str(sale.grand_total)},
                       flagged=True, branch_id=sale.branch_id)
    await db.commit()
    return await sale_view(db, actor, sale)


# Receipts and invoices

async def receipt(db: AsyncSession, actor: Principal, sale_id: uuid.UUID) -> dict:
    sale = await get_sale(db, actor, sale_id)
    if sale.receipt_no is None or sale.finalized_at is None:
        raise Conflict("Only finalized sales have receipts.", code="NOT_FINALIZED")
    company = await db.get(Company, sale.company_id)
    branch = await db.get(Branch, sale.branch_id)
    terminal = await db.get(PosTerminal, sale.terminal_id)
    cashier = await db.get(User, sale.cashier_id)
    template = await db.scalar(select(ReceiptTemplate).where(ReceiptTemplate.company_id == sale.company_id, or_(ReceiptTemplate.branch_id == sale.branch_id, ReceiptTemplate.branch_id.is_(None)))
                               .order_by(ReceiptTemplate.branch_id.is_(None)).limit(1))
    view = await sale_view(db, actor, sale)
    return {
        "copy_label": "COPY / ច្បាប់ចម្លង" if sale.reprint_count else None, "reprint_count": sale.reprint_count,
        "company_name_en": company.trading_name_en if company else "", "company_name_km": company.trading_name_km if company else "", "tax_id": company.tax_id if company else "",
        "branch_name": branch.name_en if branch else "", "branch_address": branch.address if branch else "", "branch_phone": branch.phone if branch else "",
        "header": (template.header if template else "") or (branch.receipt_header if branch else ""), "footer": template.footer if template else "",
        "receipt_no": sale.receipt_no, "invoice_no": sale.invoice_no, "business_date": sale.business_date, "finalized_at": sale.finalized_at,
        "cashier_name": cashier.full_name if cashier else "", "terminal_name": terminal.name if terminal else "", "customer_name": sale.customer_name,
        "lines": [{"name_en": ln["name_en"], "name_km": ln["name_km"], "quantity": ln["quantity"], "unit_code": ln["unit_code"], "unit_price": ln["unit_price"],
                   "discount": ln["discount_amount"] + ln["order_discount_share"], "tax_code": ln["tax_code"], "amount": ln["line_total"]} for ln in view["lines"]],
        "subtotal": sale.subtotal, "discount_total": sale.discount_total, "tax_total": sale.tax_total, "tax_inclusive": sale.tax_inclusive, "rounding": sale.rounding,
        "grand_total": sale.grand_total, "exchange_rate": sale.exchange_rate, "grand_total_khr": view["grand_total_khr"],
        "payments": [{"method": p["method"], "currency": p["currency"], "tendered": p["amount_tendered"], "applied": p["amount_applied"], "change": p["change_amount"],
                      "change_currency": p["change_currency"], "reference": p["reference"]} for p in view["payments"] if p["status"] in COMPLETED],
        "status": sale.status,
    }


async def reprint(db: AsyncSession, actor: Principal, sale_id: uuid.UUID) -> dict:
    sale = await get_sale(db, actor, sale_id, lock=True)
    if sale.receipt_no is None:
        raise Conflict("Only finalized sales can be reprinted.", code="NOT_FINALIZED")
    sale.reprint_count += 1  # reprints are marked COPY (BR-DOC-002)
    db.add(OutboxEvent(event_type="RECEIPT_REPRINT", payload={"sale_id": str(sale.id), "receipt_no": sale.receipt_no, "copy": sale.reprint_count}))
    await record_audit(db, actor, "RECEIPT_REPRINTED", "DOC", "sale", sale.id, after={"receipt_no": sale.receipt_no, "copy": sale.reprint_count}, branch_id=sale.branch_id)
    await db.commit()
    return await sale_view(db, actor, sale)


async def invoice(db: AsyncSession, actor: Principal, sale_id: uuid.UUID) -> dict:
    sale = await get_sale(db, actor, sale_id, lock=True)
    if sale.status != "FINALIZED":
        raise Conflict("Invoices are issued for finalized sales.", code="NOT_FINALIZED")
    if sale.invoice_no is None:
        branch = await db.get(Branch, sale.branch_id)
        sale.invoice_no = await next_number(db, actor.company_id, "INVOICE", branch_code=branch.code if branch else None)
        await record_audit(db, actor, "INVOICE_ISSUED", "DOC", "sale", sale.id, after={"invoice_no": sale.invoice_no}, branch_id=sale.branch_id)
        await db.commit()
    return await sale_view(db, actor, sale)


# Payments administration

async def list_payments(db: AsyncSession, actor: Principal, *, method: str | None, status: str | None, reconciled: bool | None, date_from=None, date_to=None, limit: int, offset: int) -> list[dict]:
    query = select(SalePayment, Sale.receipt_no, Branch.name_en).join(Sale, Sale.id == SalePayment.sale_id).join(Branch, Branch.id == Sale.branch_id).where(SalePayment.company_id == actor.company_id)
    if actor.branch_ids is not None:
        query = query.where(Sale.branch_id.in_(actor.branch_ids))
    for column, value in ((SalePayment.method, method), (SalePayment.status, status), (SalePayment.reconciled, reconciled)):
        if value is not None:
            query = query.where(column == value)
    if date_from:
        query = query.where(SalePayment.business_date >= date_from)
    if date_to:
        query = query.where(SalePayment.business_date <= date_to)
    rows = await db.execute(query.order_by(SalePayment.created_at.desc()).limit(limit).offset(offset))
    return [{**payment_view(p), "receipt_no": receipt_no, "branch_name": branch, "business_date": p.business_date} for p, receipt_no, branch in rows]


async def reconcile_payment(db: AsyncSession, actor: Principal, payment_id: uuid.UUID, reconciled: bool) -> dict:
    payment = await db.scalar(select(SalePayment).where(SalePayment.id == payment_id, SalePayment.company_id == actor.company_id).with_for_update())
    if payment is None:
        raise NotFound("Payment")
    sale = await db.get(Sale, payment.sale_id)
    if sale is None or not actor.has_branch(sale.branch_id):
        raise NotFound("Payment")
    payment.reconciled = reconciled
    await record_audit(db, actor, "PAYMENT_RECONCILED" if reconciled else "PAYMENT_UNRECONCILED", "PAY", "sale_payment", payment.id, after={"reconciled": reconciled}, branch_id=sale.branch_id)
    await db.commit()
    return payment_view(payment)
