"""Returns, refunds and exchanges (RET; Phase 5).

Refunds are calculated from the original line snapshots, including the line's share of
the order discount and its tax, pro rata to the quantity returned (BR-RET-005). Each
returned line has a condition that decides where the stock goes (BR-RET-003):
  RESALABLE -> the original sellable location; DAMAGED -> a DAMAGED location;
  EXPIRED -> an EXPIRED location (or DAMAGED); NON_RETURNABLE -> DAMAGED, only with approval.
Approval by a different user is needed above the cashier's refund limit, for cash refunds
above the threshold, outside the return window, and for non-returnable items (BR-RET-002, BR-RET-004).
An exchange is a return plus a new finalized sale paid first by the returned value.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, InvalidStateTransition, NotFound, ValidationFailed
from app.models import (
    Branch,
    Category,
    Customer,
    OutboxEvent,
    PosTerminal,
    Product,
    Refund,
    Sale,
    SaleLine,
    SalePayment,
    SalesReturn,
    SalesReturnLine,
    WarehouseLocation,
)
from app.schemas import sales as s
from app.services import approvals, cash_sessions, customers, pricing, stock
from app.services.common import next_number, record_audit
from app.services.principal import Principal
from app.services.sales import COMPLETED, _approver_name, _lines, _new_line, _payments, _sellable, _settings, apply_line_costs, cents, recalc_paid, reprice, round_khr, sale_line_moves

ELECTRONIC = ("CARD", "QR", "BANK_TRANSFER")


def _now() -> datetime:
    return datetime.now(UTC)


async def _quote(db: AsyncSession, actor: Principal, sale: Sale, data: s.ReturnIn) -> dict:
    if sale.status != "FINALIZED":
        raise InvalidStateTransition("Only finalized sales can be returned.")
    lines = {ln.id: ln for ln in await _lines(db, sale.id)}
    settings = await _settings(db, actor.company_id)
    company_window = int(settings.get("return_window_days", 7))
    reasons: list[str] = []
    window_expired = False
    out, seen = [], set()
    for item in data.lines:
        line = lines.get(item.sale_line_id)
        if line is None:
            raise ValidationFailed("lines", "A returned line does not belong to this sale.")
        if line.id in seen:
            raise ValidationFailed("lines", f"{line.sku} is listed twice.")
        seen.add(line.id)
        if item.quantity > line.quantity - line.returned_quantity:
            raise ValidationFailed("lines", f"Only {(line.quantity - line.returned_quantity).normalize()} {line.unit_code} of {line.sku} can still be returned.")  # BR-RET-001
        if item.quantity != item.quantity.quantize(Decimal(1).scaleb(-line.precision if line.allow_fraction and line.factor == 1 else 0)):
            raise ValidationFailed("lines", f"{line.sku} is returned in whole units.")
        product = await db.get(Product, line.product_id)
        category = await db.get(Category, product.category_id) if product else None
        window = category.return_window_days if category else company_window
        if sale.finalized_at and _now() - sale.finalized_at > timedelta(days=window):
            window_expired = True
        if category is not None and not category.returnable:
            reasons.append(f"{line.sku} is in a non-returnable category")
        if item.condition == "NON_RETURNABLE":
            reasons.append(f"{line.sku} is marked non-returnable")
        ratio = item.quantity / line.quantity
        refund = cents(line.line_total * ratio)
        tax = cents(line.tax_amount * ratio)
        out.append({"line": line, "item": item, "sale_line_id": line.id, "quantity": item.quantity, "net_amount": refund - tax, "tax_amount": tax, "refund_amount": refund})
    if window_expired:
        reasons.append("outside the return window")
    refund_total = sum((x["refund_amount"] for x in out), Decimal(0))
    tax_total = sum((x["tax_amount"] for x in out), Decimal(0))
    if refund_total > actor.limits.get("refund_amount", Decimal(0)):
        reasons.append(f"refund above your limit of {actor.limits.get('refund_amount', Decimal(0)).normalize()}")
    cash_threshold = Decimal(str(settings.get("refund_cash_approval_threshold", "20")))
    if data.refund_method == "CASH" and refund_total > cash_threshold:
        reasons.append(f"cash refund above {cash_threshold.normalize()}")

    replacement_total = Decimal(0)
    if data.replacement_lines:
        for r in data.replacement_lines:
            product = await _sellable(db, actor, await db.get(Product, r.product_id), sale.branch_id)
            unit_id = r.unit_id or product.base_unit_id
            resolved = await pricing.resolve(db, product, unit_id, branch_id=sale.branch_id)
            if resolved.price is None:
                raise AppError(f"{product.name_en} has no price.", code="NO_PRICE", status_code=422)
            replacement_total += cents(resolved.price * r.quantity)  # estimate before tax; the exchange sale is fully re-priced
    return {"lines": out, "refund_total": refund_total, "net_total": refund_total - tax_total, "tax_total": tax_total, "window_expired": window_expired,
            "approval_reasons": list(dict.fromkeys(reasons)), "replacement_total": replacement_total, "difference": replacement_total - refund_total}


async def quote(db: AsyncSession, actor: Principal, sale_id: uuid.UUID, data: s.ReturnIn) -> dict:
    from app.services.sales import get_sale

    sale = await get_sale(db, actor, sale_id)
    q = await _quote(db, actor, sale, data)
    four = Decimal("0.0001")
    fmt = lambda v: v.quantize(four) if isinstance(v, Decimal) else v  # noqa: E731  same precision as stored amounts
    return {**{k: fmt(v) for k, v in q.items() if k != "lines"}, "lines": [{k: fmt(x[k]) for k in ("sale_line_id", "quantity", "net_amount", "tax_amount", "refund_amount")} for x in q["lines"]]}


async def _destination(db: AsyncSession, line: SaleLine, condition: str) -> WarehouseLocation | None:
    if line.is_service:
        return None
    original = await db.get(WarehouseLocation, line.location_id) if line.location_id else None
    if original is None:
        return None
    if condition == "RESALABLE":
        return original
    preference = ["EXPIRED", "DAMAGED"] if condition == "EXPIRED" else ["DAMAGED"]
    for kind in preference:
        loc = await db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == original.warehouse_id, WarehouseLocation.location_type == kind, WarehouseLocation.status == "ACTIVE").limit(1))
        if loc:
            return loc
    raise ValidationFailed("lines", f"This branch needs an active {' or '.join(preference).lower()} location for {condition.lower()} returns.")


async def create_return(db: AsyncSession, actor: Principal, sale_id: uuid.UUID, data: s.ReturnIn) -> dict:
    from app.services.sales import get_sale

    actor.require("sales.return.create")
    sale = await get_sale(db, actor, sale_id, lock=True)
    terminal = await cash_sessions.current_terminal(db, actor)
    if terminal.branch_id != sale.branch_id and not actor.can("sales.sale.view_all"):
        raise AppError("Returns are processed at the branch that made the sale.", code="WRONG_BRANCH", status_code=403)
    if data.refund_method == "STORE_CREDIT" and sale.customer_id is None:
        raise ValidationFailed("refund_method", "Store credit needs a customer on the original sale.")
    if data.settlement_method == "STORE_CREDIT":
        raise ValidationFailed("settlement_method", "Pay the exchange difference in cash or by card, QR or transfer.")
    q = await _quote(db, actor, sale, data)
    approved_by = None
    if q["approval_reasons"]:
        approval = await approvals.consume(db, actor, token=data.approval_token, action="REFUND", amount=q["refund_total"],
                                           message="This return needs approval: " + "; ".join(q["approval_reasons"]) + ".")
        approved_by = await _approver_name(db, approval)
    session = await cash_sessions.open_session_for(db, actor, terminal.id, lock=True)
    exchange = bool(data.replacement_lines)
    refund_due = q["refund_total"]
    if (data.refund_method == "CASH" and refund_due > 0 and not exchange) or exchange:
        if session is None:
            raise AppError("Open a cashier session on this terminal first.", code="SESSION_REQUIRED", status_code=409)  # FR-RET-009
    branch = await db.get(Branch, sale.branch_id)
    today = stock.business_date(branch)
    ret = SalesReturn(company_id=actor.company_id, return_no=await next_number(db, actor.company_id, "RETURN", branch_code=branch.code if branch else None), original_sale_id=sale.id,
                      branch_id=sale.branch_id, terminal_id=terminal.id, session_id=session.id if session else None, type="EXCHANGE" if exchange else "RETURN", refund_method=data.refund_method,
                      net_total=q["net_total"], tax_total=q["tax_total"], refund_total=q["refund_total"], reference=data.reference, override_window=q["window_expired"], approved_by=approved_by,
                      created_by=actor.user_id, created_by_name=actor.full_name, business_date=today)
    db.add(ret)
    await db.flush()

    moves = []
    for x in q["lines"]:
        line, item = x["line"], x["item"]
        destination = await _destination(db, line, "DAMAGED" if item.condition == "NON_RETURNABLE" else item.condition)
        rl = SalesReturnLine(return_id=ret.id, sale_line_id=line.id, product_id=line.product_id, sku=line.sku, name=line.name_en, quantity=item.quantity, quantity_base=item.quantity * line.factor,
                             condition=item.condition, reason=item.reason, net_amount=x["net_amount"], tax_amount=x["tax_amount"], refund_amount=x["refund_amount"], unit_cost=line.unit_cost,
                             destination_location_id=destination.id if destination else None)
        db.add(rl)
        line.returned_quantity += item.quantity
        if destination is not None:
            product = await db.get(Product, line.product_id)
            # Returned goods go back into the batches the sale took, so their expiry dates stay known.
            parts = stock.take_from(await stock.sold_batches(db, actor.company_id, line.id), rl.quantity_base)
            split = len(parts) > 1 or parts[0][0] != ""
            for batch, qty in parts:
                suffix = f":{batch or '-'}" if split else ""
                moves.append(stock.Move(product, qty, "SALE_RETURN", "SALE_RETURN", str(ret.id), f"{line.id}:{ret.id}{suffix}", to_location=destination,
                                        unit_cost=line.unit_cost or Decimal(0), source_no=ret.return_no, reason=f"{item.condition}: {item.reason}", approved_by=approved_by,
                                        unit_id=line.unit_id, quantity_entered=item.quantity if not split else qty / line.factor, batch_no=batch))
    await db.flush()
    await stock.post(db, actor, moves)

    exchange_sale = None
    if exchange:
        exchange_sale = await _exchange_sale(db, actor, sale, ret, terminal, session, data)
        credit_used = min(refund_due, exchange_sale.grand_total)
        refund_due -= credit_used
        ret.difference_paid = max(exchange_sale.grand_total - credit_used, Decimal(0))
        ret.exchange_sale_id = exchange_sale.id
    if refund_due > 0:
        await _refund(db, actor, sale, ret, data.refund_method, refund_due, data.reference, session, today)
    else:
        ret.refund_status = "COMPLETED"
    if exchange_sale is not None and refund_due == 0 and not await db.scalar(select(Refund.id).where(Refund.return_id == ret.id, Refund.status == "PENDING").limit(1)):
        ret.refund_status = "COMPLETED"
    await db.flush()
    await recalc_paid(db, sale)
    db.add(OutboxEvent(event_type="RETURN_CREATED", payload={"return_id": str(ret.id), "return_no": ret.return_no, "original_receipt_no": sale.receipt_no}))
    await record_audit(db, actor, "RETURN_CREATED", "RET", "sales_return", ret.id,
                       after={"return_no": ret.return_no, "receipt_no": sale.receipt_no, "refund": str(ret.refund_total), "method": data.refund_method, "approved_by": approved_by, "type": ret.type},
                       flagged=bool(q["approval_reasons"]), branch_id=sale.branch_id)
    await db.commit()
    return await return_view(db, actor, ret)


async def _refund(db: AsyncSession, actor: Principal, sale: Sale, ret: SalesReturn, method: str, amount: Decimal, reference: str | None, session, today) -> None:
    """Cash refunds come from the open session; electronic refunds go back to the original payment and wait for the provider reference."""
    actor.require("sales.return.create", "sales.refund.process")
    payments = [p for p in await _payments(db, sale.id) if p.status in COMPLETED]
    settings = await _settings(db, actor.company_id)
    increment = Decimal(str(settings.get("khr_cash_increment", "100")))
    if method == "CASH":
        if session is None:
            raise AppError("Open a cashier session on this terminal first.", code="SESSION_REQUIRED", status_code=409)
        source = next((p for p in payments if p.method == "CASH"), payments[0] if payments else None)
        db.add(Refund(company_id=actor.company_id, sale_id=sale.id, return_id=ret.id, sale_payment_id=source.id if source else None, kind="RETURN", method="CASH", currency="USD",
                      amount=amount, amount_applied=amount, status="COMPLETED", session_id=session.id, user_id=actor.user_id, business_date=today, completed_at=_now()))
        if source is not None:
            _mark_refunded(source, amount)
        ret.refund_status = "COMPLETED"
        return
    if method == "STORE_CREDIT":
        customer = await db.scalar(select(Customer).where(Customer.id == sale.customer_id).with_for_update())
        await customers.change_credit(db, actor, customer, amount, f"Refund for {ret.return_no}", sale_id=sale.id, return_id=ret.id)
        db.add(Refund(company_id=actor.company_id, sale_id=sale.id, return_id=ret.id, kind="RETURN", method="STORE_CREDIT", currency="USD", amount=amount, amount_applied=amount,
                      status="COMPLETED", user_id=actor.user_id, business_date=today, completed_at=_now()))
        ret.refund_status = "COMPLETED"
        return
    if method not in ELECTRONIC:
        raise ValidationFailed("refund_method", "Choose cash, store credit or the original payment method.")
    remaining = amount
    for p in [p for p in payments if p.method == method]:
        room = p.amount_applied - p.refunded_amount
        take = min(room, remaining)
        if take <= 0:
            continue
        refund_amount = take if p.currency == "USD" else round_khr(take * p.exchange_rate, increment)
        db.add(Refund(company_id=actor.company_id, sale_id=sale.id, return_id=ret.id, sale_payment_id=p.id, kind="RETURN", method=method, currency=p.currency, amount=refund_amount,
                      amount_applied=take, status="COMPLETED" if reference else "PENDING", reference=reference, user_id=actor.user_id, business_date=today,
                      completed_at=_now() if reference else None))
        if reference:
            _mark_refunded(p, take)
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        raise ValidationFailed("refund_method", f"Only {(amount - remaining).normalize()} was paid by {method.lower().replace('_', ' ')}; refund the rest in cash.")
    ret.refund_status = "COMPLETED" if reference else "PENDING"


def _mark_refunded(payment: SalePayment, amount: Decimal) -> None:
    payment.refunded_amount = min(payment.refunded_amount + amount, payment.amount_applied)
    payment.status = "REFUNDED" if payment.refunded_amount >= payment.amount_applied else "PARTIALLY_REFUNDED"


async def _exchange_sale(db: AsyncSession, actor: Principal, original: Sale, ret: SalesReturn, terminal: PosTerminal, session, data: s.ReturnIn) -> Sale:
    """Creates and finalizes the replacement sale, paid first by the returned value, then by the settlement method."""
    from app.services.org import current_rate
    from app.services.sales import _derive_payment_status

    rate = await current_rate(db, actor.company_id)
    new = Sale(company_id=actor.company_id, branch_id=original.branch_id, terminal_id=terminal.id, session_id=session.id, cashier_id=actor.user_id, exchange_rate=rate.rate if rate else None,
               exchange_return_id=ret.id, notices=[])
    db.add(new)
    await db.flush()
    lines = []
    for i, r in enumerate(data.replacement_lines or [], start=1):
        product = await _sellable(db, actor, await db.get(Product, r.product_id), new.branch_id)
        lines.append(await _new_line(db, new, product, r.unit_id or product.base_unit_id, r.quantity, i, terminal.default_location_id))
    await db.flush()
    await reprice(db, new, lines, mark_changes=False)
    credit = min(ret.refund_total, new.grand_total)
    branch = await db.get(Branch, new.branch_id)
    today = stock.business_date(branch)
    if credit > 0:
        db.add(SalePayment(company_id=actor.company_id, sale_id=new.id, session_id=session.id, terminal_id=terminal.id, method="EXCHANGE_CREDIT", currency="USD", amount_tendered=credit,
                           amount_applied=credit, change_currency="USD", status="COMPLETED", reference=ret.return_no, business_date=today, user_id=actor.user_id, completed_at=_now()))
    difference = new.grand_total - credit
    if difference > 0:
        method = data.settlement_method or "CASH"
        if method in ELECTRONIC and not data.settlement_reference:
            raise ValidationFailed("settlement_reference", "Enter the reference for the payment of the difference.")
        db.add(SalePayment(company_id=actor.company_id, sale_id=new.id, session_id=session.id, terminal_id=terminal.id, method=method, currency="USD", amount_tendered=difference,
                           amount_applied=difference, change_currency="USD", status="COMPLETED", reference=data.settlement_reference if method != "CASH" else None,
                           business_date=today, user_id=actor.user_id, completed_at=_now()))
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("This payment reference has already been used.", code="DUPLICATE_PAYMENT_REFERENCE") from exc
    moves = []
    usable_on = stock.business_date(branch)
    for line in lines:
        if line.is_service:
            continue
        product = await db.get(Product, line.product_id)
        location = await db.get(WarehouseLocation, line.location_id)
        moves += await sale_line_moves(db, line, product, location, str(new.id), usable_on, source_no=ret.return_no)
    apply_line_costs(lines, await stock.post(db, actor, moves))
    new.receipt_no = await next_number(db, actor.company_id, "RECEIPT", branch_code=branch.code if branch else None)
    new.status, new.finalized_at, new.business_date = "FINALIZED", _now(), today
    await recalc_paid(db, new)
    _derive_payment_status(new)
    return new


async def return_view(db: AsyncSession, actor: Principal, ret: SalesReturn) -> dict:
    await db.refresh(ret)
    sale = await db.get(Sale, ret.original_sale_id)
    branch = await db.get(Branch, ret.branch_id)
    lines = list(await db.scalars(select(SalesReturnLine).where(SalesReturnLine.return_id == ret.id)))
    return {
        **{f: getattr(ret, f) for f in ("id", "return_no", "original_sale_id", "branch_id", "terminal_id", "session_id", "type", "refund_method", "refund_total", "net_total", "tax_total",
                                        "refund_status", "reference", "exchange_sale_id", "difference_paid", "approved_by", "override_window", "created_at", "business_date")},
        "original_receipt_no": sale.receipt_no if sale else "", "branch_name": branch.name_en if branch else "", "customer_name": sale.customer_name if sale else None, "created_by": ret.created_by_name,
        "lines": [{**{f: getattr(rl, f) for f in ("sale_line_id", "product_id", "sku", "name", "quantity", "condition", "reason", "net_amount", "tax_amount", "refund_amount", "destination_location_id")},
                   "unit_cost": rl.unit_cost if actor.sees_cost else None} for rl in lines],
    }


async def list_returns(db: AsyncSession, actor: Principal, limit: int, offset: int) -> list[dict]:
    query = select(SalesReturn).where(SalesReturn.company_id == actor.company_id)
    if actor.branch_ids is not None:
        query = query.where(SalesReturn.branch_id.in_(actor.branch_ids))
    if not actor.can("sales.sale.view_all"):
        query = query.where(SalesReturn.created_by == actor.user_id)
    return [await return_view(db, actor, r) for r in await db.scalars(query.order_by(SalesReturn.created_at.desc()).limit(limit).offset(offset))]


def refund_view(r: Refund) -> dict:
    return {f: getattr(r, f) for f in ("id", "return_id", "sale_id", "sale_payment_id", "kind", "method", "amount", "currency", "status", "reference", "session_id", "created_at", "business_date")}


async def list_refunds(db: AsyncSession, actor: Principal, status: str | None, limit: int, offset: int) -> list[dict]:
    query = select(Refund).join(Sale, Sale.id == Refund.sale_id).where(Refund.company_id == actor.company_id)
    if actor.branch_ids is not None:
        query = query.where(Sale.branch_id.in_(actor.branch_ids))
    if status:
        query = query.where(Refund.status == status)
    return [refund_view(r) for r in await db.scalars(query.order_by(Refund.created_at.desc()).limit(limit).offset(offset))]


async def confirm_refunds(db: AsyncSession, actor: Principal, *, return_id: uuid.UUID | None = None, refund_id: uuid.UUID | None = None, reference: str) -> None:
    """Records the provider or bank reference that confirms an electronic refund (FR-RET-009)."""
    actor.require("sales.refund.process", "sales.return.create")
    query = select(Refund).where(Refund.company_id == actor.company_id, Refund.status == "PENDING").with_for_update()
    query = query.where(Refund.return_id == return_id) if return_id else query.where(Refund.id == refund_id)
    refunds = list(await db.scalars(query))
    if not refunds:
        raise NotFound("Pending refund")
    for refund in refunds:
        sale = await db.get(Sale, refund.sale_id)
        if sale is None or not actor.has_branch(sale.branch_id):
            raise NotFound("Pending refund")
        refund.status, refund.reference, refund.completed_at = "COMPLETED", reference, _now()
        if refund.sale_payment_id:
            payment = await db.get(SalePayment, refund.sale_payment_id)
            if payment is not None:
                _mark_refunded(payment, refund.amount_applied)
        await db.flush()
        await recalc_paid(db, sale)
        await record_audit(db, actor, "REFUND_CONFIRMED", "RET", "refund", refund.id, after={"reference": reference, "amount": str(refund.amount), "method": refund.method}, branch_id=sale.branch_id)
    if return_id:
        ret = await db.get(SalesReturn, return_id)
        if ret is not None:
            ret.refund_status, ret.reference = "COMPLETED", reference
    await db.commit()


async def get_return(db: AsyncSession, actor: Principal, return_id: uuid.UUID) -> SalesReturn:
    ret = await db.scalar(select(SalesReturn).where(SalesReturn.id == return_id, SalesReturn.company_id == actor.company_id))
    if ret is None or not actor.has_branch(ret.branch_id):
        raise NotFound("Return")
    return ret

