"""Cashier sessions and the cash drawer (CSH; Phase 5).

Expected closing cash, per currency (SRS 6.7, BR-CSH-001):
  opening + cash tendered - change given + cash in - cash refunds - cash out - paid out - drops.
Change given in another currency reduces that currency. Card, QR, transfer and other
non-cash amounts are reported separately and never affect expected cash.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, Forbidden, InvalidStateTransition, NotAuthenticated, NotFound, ValidationFailed
from app.models import Branch, CashierSession, CashMovement, Company, PosTerminal, Refund, Sale, SalePayment, TerminalCashier, User
from app.schemas import sales as s
from app.services import approvals
from app.services.common import next_number, record_audit
from app.services.principal import Principal
from app.services.stock import business_date

CURRENCIES = ("USD", "KHR")
OUTFLOWS = {"CASH_OUT", "PAID_OUT", "DROP"}


def _now() -> datetime:
    return datetime.now(UTC)


async def current_terminal(db: AsyncSession, actor: Principal) -> PosTerminal:
    """The registered terminal sent in X-Terminal-Id, checked against the caller's branch and cashier assignment."""
    if actor.terminal_id is None:
        raise NotAuthenticated("This device is not registered as a POS terminal. Send X-Terminal-Id.", code="TERMINAL_NOT_REGISTERED")
    terminal = await db.get(PosTerminal, actor.terminal_id)
    if terminal is None or terminal.company_id != actor.company_id or terminal.status != "ACTIVE":
        raise NotAuthenticated("This device is not registered as a POS terminal.", code="TERMINAL_NOT_REGISTERED")
    if not actor.has_branch(terminal.branch_id):
        raise Forbidden("You are not assigned to this terminal's branch.")
    assigned = set(await db.scalars(select(TerminalCashier.user_id).where(TerminalCashier.terminal_id == terminal.id)))
    if assigned and actor.user_id not in assigned and not actor.can("cash.session.approve"):
        raise Forbidden("You are not assigned to this terminal.")
    return terminal


async def open_session_for(db: AsyncSession, actor: Principal, terminal_id: uuid.UUID, *, lock: bool = False) -> CashierSession | None:
    query = select(CashierSession).where(CashierSession.terminal_id == terminal_id, CashierSession.cashier_id == actor.user_id, CashierSession.status == "OPEN")
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)


async def require_open_session(db: AsyncSession, actor: Principal, terminal_id: uuid.UUID) -> CashierSession:
    session = await open_session_for(db, actor, terminal_id, lock=True)
    if session is None:
        raise AppError("Open a cashier session on this terminal first.", code="SESSION_REQUIRED", status_code=409)
    return session


async def cash_flows(db: AsyncSession, session_id: uuid.UUID) -> dict:
    """Cash sales, refunds and movements per currency for a session."""
    sales = {c: Decimal(0) for c in CURRENCIES}
    for currency, tendered in await db.execute(
        select(SalePayment.currency, func.sum(SalePayment.amount_tendered)).where(SalePayment.session_id == session_id, SalePayment.method == "CASH", SalePayment.status.in_(("COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED"))).group_by(SalePayment.currency)
    ):
        sales[currency] += Decimal(tendered)
    for currency, change in await db.execute(
        select(SalePayment.change_currency, func.sum(SalePayment.change_amount)).where(SalePayment.session_id == session_id, SalePayment.method == "CASH", SalePayment.status.in_(("COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED"))).group_by(SalePayment.change_currency)
    ):
        sales[currency] -= Decimal(change)
    refunds = {c: Decimal(0) for c in CURRENCIES}
    for currency, amount in await db.execute(
        select(Refund.currency, func.sum(Refund.amount)).where(Refund.session_id == session_id, Refund.method == "CASH", Refund.status == "COMPLETED").group_by(Refund.currency)
    ):
        refunds[currency] += Decimal(amount)
    movements = {k: {c: Decimal(0) for c in CURRENCIES} for k in ("CASH_IN", "CASH_OUT", "PAID_OUT", "DROP")}
    for kind, currency, amount in await db.execute(select(CashMovement.kind, CashMovement.currency, func.sum(CashMovement.amount)).where(CashMovement.session_id == session_id).group_by(CashMovement.kind, CashMovement.currency)):
        movements[kind][currency] += Decimal(amount)
    return {"cash_sales": sales, "cash_refunds": refunds, "movement_totals": movements}


def expected_from(session: CashierSession, flows: dict) -> dict[str, Decimal]:
    opening = {"USD": session.opening_usd, "KHR": session.opening_khr}
    m = flows["movement_totals"]
    return {
        c: opening[c] + flows["cash_sales"][c] + m["CASH_IN"][c] - flows["cash_refunds"][c] - m["CASH_OUT"][c] - m["PAID_OUT"][c] - m["DROP"][c]
        for c in CURRENCIES
    }


async def session_view(db: AsyncSession, actor: Principal, session: CashierSession) -> dict:
    terminal = await db.get(PosTerminal, session.terminal_id)
    cashier = await db.get(User, session.cashier_id)
    # Blind count: the cashier sees expected cash only after submitting the count (FR-CSH-007).
    reveal = session.status != "OPEN" or (actor.can("cash.session.approve") and actor.user_id != session.cashier_id)
    pair = lambda usd, khr: None if usd is None else {"USD": usd, "KHR": khr}  # noqa: E731
    return {
        "id": session.id, "session_no": session.session_no, "terminal_id": session.terminal_id, "terminal_name": terminal.name if terminal else "", "branch_id": session.branch_id,
        "cashier_id": session.cashier_id, "cashier_name": cashier.full_name if cashier else "", "status": session.status, "opened_at": session.opened_at, "closed_at": session.closed_at,
        "opening": {"USD": session.opening_usd, "KHR": session.opening_khr}, "witness": session.witness, "counted": pair(session.counted_usd, session.counted_khr),
        "denominations": session.denominations,
        "expected": pair(session.expected_usd, session.expected_khr) if reveal and session.expected_usd is not None else (expected_from(session, await cash_flows(db, session.id)) if reveal else None),
        "variance": pair(session.variance_usd, session.variance_khr) if reveal else None, "variance_reason": session.variance_reason, "reviewed_by": session.reviewed_by,
        "needs_approval": session.needs_approval, "business_date": session.business_date, "version": session.version,
    }


async def _get(db: AsyncSession, actor: Principal, session_id: uuid.UUID, *, lock: bool = False) -> CashierSession:
    query = select(CashierSession).where(CashierSession.id == session_id, CashierSession.company_id == actor.company_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    session = await db.scalar(query)
    if session is None or not actor.has_branch(session.branch_id):
        raise NotFound("Cashier session")
    if session.cashier_id != actor.user_id and not actor.can("cash.session.view_all", "cash.session.approve"):
        raise NotFound("Cashier session")
    return session


async def list_sessions(db: AsyncSession, actor: Principal, *, status: str | None, terminal_id: uuid.UUID | None, limit: int, offset: int) -> list[dict]:
    query = select(CashierSession).where(CashierSession.company_id == actor.company_id)
    if actor.branch_ids is not None:
        query = query.where(CashierSession.branch_id.in_(actor.branch_ids))
    if not actor.can("cash.session.view_all"):
        query = query.where(CashierSession.cashier_id == actor.user_id)
    if status:
        query = query.where(CashierSession.status == status)
    if terminal_id:
        query = query.where(CashierSession.terminal_id == terminal_id)
    return [await session_view(db, actor, x) for x in await db.scalars(query.order_by(CashierSession.opened_at.desc()).limit(limit).offset(offset))]


async def current(db: AsyncSession, actor: Principal) -> dict | None:
    query = select(CashierSession).where(CashierSession.cashier_id == actor.user_id, CashierSession.status.in_(("OPEN", "CLOSING")))
    if actor.terminal_id:
        query = query.where(CashierSession.terminal_id == actor.terminal_id)
    session = await db.scalar(query)
    return await session_view(db, actor, session) if session else None


async def open_session(db: AsyncSession, actor: Principal, data: s.SessionOpen) -> dict:
    terminal = await current_terminal(db, actor)
    branch = await db.get(Branch, terminal.branch_id)
    session = CashierSession(
        company_id=actor.company_id, session_no=await next_number(db, actor.company_id, "SESSION", branch_code=branch.code if branch else None), terminal_id=terminal.id,
        branch_id=terminal.branch_id, cashier_id=actor.user_id, business_date=business_date(branch), opening_usd=data.opening.USD, opening_khr=data.opening.KHR, witness=data.witness,
    )
    db.add(session)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("A session is already open on this terminal or for this cashier.", code="SESSION_ALREADY_OPEN") from exc
    await record_audit(db, actor, "SESSION_OPENED", "CSH", "cashier_session", session.id, after={"no": session.session_no, "opening": {"USD": str(data.opening.USD), "KHR": str(data.opening.KHR)}}, branch_id=session.branch_id)
    await db.commit()
    return await session_view(db, actor, session)


async def summary(db: AsyncSession, actor: Principal, session_id: uuid.UUID) -> dict:
    session = await _get(db, actor, session_id)
    view = await session_view(db, actor, session)
    reveal = view["expected"] is not None
    flows = await cash_flows(db, session.id)
    movements = list(await db.scalars(select(CashMovement).where(CashMovement.session_id == session.id).order_by(CashMovement.at)))
    non_cash = {m: Decimal(v) for m, v in await db.execute(
        select(SalePayment.method, func.sum(SalePayment.amount_applied)).where(SalePayment.session_id == session.id, SalePayment.method != "CASH", SalePayment.status.in_(("COMPLETED", "PARTIALLY_REFUNDED", "REFUNDED"))).group_by(SalePayment.method))}
    sales_count, sales_total = (await db.execute(select(func.count(), func.coalesce(func.sum(Sale.grand_total), 0)).where(Sale.session_id == session.id, Sale.status == "FINALIZED"))).one()
    pending = await db.scalar(select(func.count()).select_from(SalePayment).where(SalePayment.session_id == session.id, SalePayment.status == "PENDING"))
    return {
        "session": view, "movements": [movement_view(m) for m in movements],
        "cash_sales": flows["cash_sales"] if reveal else None, "cash_refunds": flows["cash_refunds"] if reveal else None,
        "movement_totals": flows["movement_totals"] if reveal else None, "non_cash_totals": non_cash, "sales_count": sales_count, "sales_total": Decimal(sales_total), "pending_payments": pending or 0,
    }


def movement_view(m: CashMovement) -> dict:
    return {"id": m.id, "session_id": m.session_id, "kind": m.kind, "currency": m.currency, "amount": m.amount, "reason": m.reason, "witness": m.witness,
            "approved_by": m.approved_by, "expense_id": m.expense_id, "at": m.at, "by": m.by_name}


async def _settings(db: AsyncSession, actor: Principal) -> dict:
    company = await db.get(Company, actor.company_id)
    return (company.settings or {}) if company else {}


async def _usd(db: AsyncSession, actor: Principal, currency: str, amount: Decimal) -> Decimal:
    if currency == "USD":
        return amount
    from app.services.org import current_rate

    rate = await current_rate(db, actor.company_id)
    return amount / rate.rate if rate else amount


async def add_movement(db: AsyncSession, actor: Principal, session_id: uuid.UUID, data: s.CashMovementIn) -> dict:
    session = await _get(db, actor, session_id, lock=True)
    if session.status != "OPEN":
        raise InvalidStateTransition("Cash can only be moved in an open session.")
    if session.cashier_id != actor.user_id and not actor.can("cash.session.approve"):
        raise Forbidden("Only the session's cashier or a manager can record cash movements.")
    if data.kind == "PAID_OUT" and data.expense_category_id:
        raise ValidationFailed("expense_category_id", "Linking paid-outs to expenses arrives with the expense module (Phase 8).")
    threshold = Decimal(str((await _settings(db, actor)).get("cash_movement_approval_threshold", "50")))
    approved_by = None
    usd_value = await _usd(db, actor, data.currency, data.amount)
    if usd_value > threshold:
        approval = await approvals.consume(db, actor, token=data.approval_token, action="CASH_MOVEMENT", amount=usd_value,
                                           message=f"Cash movements above {threshold} USD need manager approval.")
        approver = await db.get(User, approval.approver_id)
        approved_by = approver.full_name if approver else None
    if data.kind in OUTFLOWS:
        expected = expected_from(session, await cash_flows(db, session.id))
        if data.amount > expected[data.currency]:
            raise ValidationFailed("amount", f"Only {expected[data.currency].normalize()} {data.currency} is expected in the drawer.")
    movement = CashMovement(session_id=session.id, kind=data.kind, currency=data.currency, amount=data.amount, reason=data.reason, witness=data.witness,
                            approved_by=approved_by, user_id=actor.user_id, by_name=actor.full_name)
    db.add(movement)
    await db.flush()
    await record_audit(db, actor, f"CASH_{data.kind}", "CSH", "cashier_session", session.id, after={"currency": data.currency, "amount": str(data.amount), "reason": data.reason, "approved_by": approved_by}, branch_id=session.branch_id)
    await db.commit()
    return movement_view(movement)


async def _pending_payments(db: AsyncSession, session: CashierSession) -> int:
    return int(await db.scalar(
        select(func.count()).select_from(SalePayment).join(Sale, Sale.id == SalePayment.sale_id)
        .where(SalePayment.status == "PENDING", Sale.terminal_id == session.terminal_id, Sale.cashier_id == session.cashier_id)
    ) or 0)


async def close(db: AsyncSession, actor: Principal, session_id: uuid.UUID, data: s.SessionClose) -> dict:
    session = await _get(db, actor, session_id, lock=True)
    if session.cashier_id != actor.user_id:
        raise Forbidden("Only the session's cashier counts and closes it; a manager can force-close.")
    if session.status != "OPEN":
        raise InvalidStateTransition("This session is not open.")
    if await _pending_payments(db, session):
        raise AppError("Resolve the pending electronic payments before closing.", code="PENDING_PAYMENTS", status_code=409)
    open_sales = await db.scalar(select(func.count()).select_from(Sale).where(Sale.session_id == session.id, Sale.status == "PENDING_PAYMENT"))
    if open_sales:
        raise AppError("Finish or cancel the sales waiting for payment first.", code="PENDING_PAYMENTS", status_code=409)
    expected = expected_from(session, await cash_flows(db, session.id))
    session.counted_usd, session.counted_khr, session.denominations = data.counted.USD, data.counted.KHR, data.denominations
    session.expected_usd, session.expected_khr = expected["USD"], expected["KHR"]
    session.variance_usd, session.variance_khr = data.counted.USD - expected["USD"], data.counted.KHR - expected["KHR"]
    settings = await _settings(db, actor)
    tolerance = {"USD": Decimal(str(settings.get("session_variance_tolerance_usd", "1.00"))), "KHR": Decimal(str(settings.get("session_variance_tolerance_khr", "4000")))}
    session.needs_approval = abs(session.variance_usd) > tolerance["USD"] or abs(session.variance_khr) > tolerance["KHR"]
    if data.variance_reason:
        session.variance_reason = data.variance_reason
    if session.needs_approval:
        session.status = "CLOSING"
    else:
        session.status, session.closed_at = "CLOSED", _now()
    await record_audit(db, actor, "SESSION_COUNTED", "CSH", "cashier_session", session.id,
                       after={"counted": {"USD": str(data.counted.USD), "KHR": str(data.counted.KHR)}, "variance": {"USD": str(session.variance_usd), "KHR": str(session.variance_khr)}, "status": session.status},
                       flagged=session.needs_approval, branch_id=session.branch_id)
    await db.commit()
    return await session_view(db, actor, session)


async def approve(db: AsyncSession, actor: Principal, session_id: uuid.UUID, reason: str) -> dict:
    session = await _get(db, actor, session_id, lock=True)
    actor.require("cash.session.approve")
    if session.status != "CLOSING":
        raise InvalidStateTransition("Only a counted session waiting for review can be approved.")
    if session.cashier_id == actor.user_id:
        raise approvals.SodViolation("A cashier cannot approve their own variance.")
    session.status, session.closed_at, session.variance_reason = "CLOSED", _now(), reason
    session.reviewed_by, session.reviewed_by_id = actor.full_name, actor.user_id
    await record_audit(db, actor, "SESSION_VARIANCE_APPROVED", "CSH", "cashier_session", session.id, after={"reason": reason, "variance": {"USD": str(session.variance_usd), "KHR": str(session.variance_khr)}}, flagged=True, branch_id=session.branch_id)
    await db.commit()
    return await session_view(db, actor, session)


async def force_close(db: AsyncSession, actor: Principal, session_id: uuid.UUID, reason: str) -> dict:
    session = await _get(db, actor, session_id, lock=True)
    actor.require("cash.session.approve")
    if session.status not in ("OPEN", "CLOSING"):
        raise InvalidStateTransition("This session is already closed.")
    if session.cashier_id == actor.user_id:
        raise approvals.SodViolation("Ask another manager to force-close your own session.")
    expected = expected_from(session, await cash_flows(db, session.id))
    session.expected_usd, session.expected_khr = expected["USD"], expected["KHR"]
    session.status, session.closed_at, session.variance_reason, session.reviewed_by, session.reviewed_by_id = "FORCE_CLOSED", _now(), reason, actor.full_name, actor.user_id
    await record_audit(db, actor, "SESSION_FORCE_CLOSED", "CSH", "cashier_session", session.id, after={"reason": reason}, flagged=True, branch_id=session.branch_id)
    await db.commit()
    return await session_view(db, actor, session)
