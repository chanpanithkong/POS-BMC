"""Expenses and expense categories (EXP; Phase 8).

Expenses are operating costs and never touch inventory value or COGS (FR-EXP-006).
An expense up to the approval threshold is approved automatically; above it another
user with expenses.expense.approve must approve (BR-SEC-002). A supporting document
is required above the attachment threshold. Paid-outs from a cashier drawer create an
approved expense linked to the session and cash movement (FR-EXP-004).
"""

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, InvalidStateTransition, NotFound, ValidationFailed
from app.models import Branch, CashierSession, CashMovement, Company, Expense, ExpenseCategory
from app.schemas import extras as s
from app.services import files, notifications, stock
from app.services.approvals import SodViolation
from app.services.common import apply_changes, ensure_unique, next_number, owned, plain, record_audit
from app.services.principal import Principal

CENT = Decimal("0.01")


async def _settings(db: AsyncSession, company_id: uuid.UUID) -> dict:
    company = await db.get(Company, company_id)
    return (company.settings or {}) if company else {}


# Categories

async def list_categories(db: AsyncSession, actor: Principal) -> list[ExpenseCategory]:
    return list(await db.scalars(select(ExpenseCategory).where(ExpenseCategory.company_id == actor.company_id).order_by(ExpenseCategory.name)))


async def create_category(db: AsyncSession, actor: Principal, data: s.ExpenseCategoryIn) -> ExpenseCategory:
    if not data.code or not data.name:
        raise ValidationFailed("code", "Code and name are required.")
    await ensure_unique(db, ExpenseCategory, actor, "code", data.code)
    row = ExpenseCategory(company_id=actor.company_id, code=data.code, name=data.name, status=data.status or "ACTIVE", created_by=actor.user_id)
    db.add(row)
    await db.flush()
    await record_audit(db, actor, "EXPENSE_CATEGORY_CREATED", "EXP", "expense_category", row.id, after={"code": row.code})
    await db.commit()
    await db.refresh(row)
    return row


async def update_category(db: AsyncSession, actor: Principal, category_id: uuid.UUID, data: s.ExpenseCategoryIn) -> ExpenseCategory:
    row = await owned(db, ExpenseCategory, category_id, actor, "Expense category")
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    await ensure_unique(db, ExpenseCategory, actor, "code", changes.get("code"), exclude=row.id)
    before, after = apply_changes(row, changes)
    if after:
        await record_audit(db, actor, "EXPENSE_CATEGORY_UPDATED", "EXP", "expense_category", row.id, before=before, after=after)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_category(db: AsyncSession, actor: Principal, category_id: uuid.UUID) -> None:
    row = await owned(db, ExpenseCategory, category_id, actor, "Expense category")
    if await db.scalar(select(Expense.id).where(Expense.category_id == row.id).limit(1)):
        raise Conflict("Expenses use this category. Deactivate it instead.", code="IN_USE")
    await db.delete(row)
    await record_audit(db, actor, "EXPENSE_CATEGORY_DELETED", "EXP", "expense_category", category_id, before={"code": row.code})
    await db.commit()


# Expenses

async def expense_view(db: AsyncSession, e: Expense) -> dict:
    await db.refresh(e)
    category = await db.get(ExpenseCategory, e.category_id)
    branch = await db.get(Branch, e.branch_id)
    return {
        **{f: getattr(e, f) for f in ("id", "expense_no", "date", "category_id", "description", "amount", "currency", "amount_base", "payment_method", "branch_id", "status", "reject_reason",
                                      "session_id", "created_at")},
        "category_name": category.name if category else "", "branch_name": branch.name_en if branch else "", "attachment": e.attachment_url,
        "created_by": await stock.user_name(db, e.created_by), "created_by_id": e.created_by,
        "approved_by": "Auto-approved within limit" if e.auto_approved else e.approved_by_name,
    }


async def list_expenses(db: AsyncSession, actor: Principal, *, status: str | None, branch_id: uuid.UUID | None, date_from=None, date_to=None) -> list[dict]:
    query = select(Expense).where(Expense.company_id == actor.company_id)
    if actor.branch_ids is not None:
        query = query.where(Expense.branch_id.in_(actor.branch_ids))
    if branch_id:
        query = query.where(Expense.branch_id == branch_id)
    if status:
        query = query.where(Expense.status == status)
    if date_from:
        query = query.where(Expense.date >= date_from)
    if date_to:
        query = query.where(Expense.date <= date_to)
    return [await expense_view(db, e) for e in await db.scalars(query.order_by(Expense.date.desc(), Expense.created_at.desc()).limit(500))]


async def _get(db: AsyncSession, actor: Principal, expense_id: uuid.UUID) -> Expense:
    e = await db.scalar(select(Expense).where(Expense.id == expense_id, Expense.company_id == actor.company_id).with_for_update())
    if e is None or not actor.has_branch(e.branch_id):
        raise NotFound("Expense")
    return e


async def _validate(db: AsyncSession, actor: Principal, values: dict) -> tuple[Decimal, Decimal]:
    for field in ("date", "category_id", "description", "amount", "currency", "payment_method", "branch_id"):
        if values.get(field) in (None, ""):
            raise ValidationFailed(field, "This field is required.")
    category = await owned(db, ExpenseCategory, values["category_id"], actor, "Expense category")
    if category.status != "ACTIVE":
        raise ValidationFailed("category_id", "This category is inactive.")
    branch = await owned(db, Branch, values["branch_id"], actor, "Branch")
    actor.assert_branch(branch.id)
    rate = Decimal(1)
    if values["currency"] == "KHR":
        from app.services.org import current_rate

        current = await current_rate(db, actor.company_id)
        if current is None:
            raise ValidationFailed("currency", "Set a USD to KHR exchange rate first.")
        rate = current.rate
    base = (Decimal(values["amount"]) / rate).quantize(CENT, ROUND_HALF_UP)
    threshold = Decimal(str((await _settings(db, actor.company_id)).get("expense_attachment_threshold", "50")))
    if base > threshold and not values.get("attachment_url"):
        raise ValidationFailed("attachment", f"A supporting document is required above {threshold.normalize()} USD.")
    return base, rate


def _attachment(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("data:"):
        return files.store_data_url("expenses", value, field="attachment", allowed=("jpg", "png", "webp", "pdf"))
    if value.startswith("/api/v1/files/expenses/") or value.startswith("https://"):
        return value
    raise ValidationFailed("attachment", "Upload the document or give an https:// link.")


async def _approval_state(db: AsyncSession, actor: Principal, e: Expense) -> None:
    threshold = Decimal(str((await _settings(db, actor.company_id)).get("expense_approval_threshold", "100")))
    if e.amount_base <= threshold:
        e.status, e.auto_approved, e.approved_by_name = "APPROVED", True, None
    else:
        e.status, e.auto_approved, e.approved_by_name = "SUBMITTED", False, None
        notifications.notify(db, actor.company_id, "APPROVAL", "Expense awaiting approval", f"{e.expense_no}: {e.amount_base} USD", link="/expenses",
                             permission="expenses.expense.approve", branch_id=e.branch_id)


async def create_expense(db: AsyncSession, actor: Principal, data: s.ExpenseIn) -> dict:
    values = data.model_dump()
    values["attachment_url"] = _attachment(values.pop("attachment"))
    base, rate = await _validate(db, actor, values)
    branch = await db.get(Branch, values["branch_id"])
    e = Expense(company_id=actor.company_id, expense_no=await next_number(db, actor.company_id, "EXPENSE", branch_code=branch.code if branch else None), date=values["date"],
                category_id=values["category_id"], description=values["description"], amount=values["amount"], currency=values["currency"], exchange_rate=rate, amount_base=base,
                payment_method=values["payment_method"], branch_id=values["branch_id"], attachment_url=values["attachment_url"], created_by=actor.user_id)
    db.add(e)
    await db.flush()
    await _approval_state(db, actor, e)
    await record_audit(db, actor, "EXPENSE_RECORDED", "EXP", "expense", e.id, after={"no": e.expense_no, "amount": str(base), "status": e.status}, branch_id=e.branch_id)
    await db.commit()
    return await expense_view(db, e)


async def update_expense(db: AsyncSession, actor: Principal, expense_id: uuid.UUID, data: s.ExpenseIn) -> dict:
    e = await _get(db, actor, expense_id)
    if e.status == "APPROVED" and not e.auto_approved:
        raise InvalidStateTransition("An approved expense cannot be edited.")
    if e.cash_movement_id:
        raise InvalidStateTransition("A drawer paid-out is corrected with a cash movement, not by editing the expense.")
    changes = data.model_dump(exclude_unset=True)
    if "attachment" in changes:
        changes["attachment_url"] = _attachment(changes.pop("attachment"))
    values = {f: getattr(e, f) for f in ("date", "category_id", "description", "amount", "currency", "payment_method", "branch_id", "attachment_url")} | {k: v for k, v in changes.items() if v is not None or k == "attachment_url"}
    base, rate = await _validate(db, actor, values)
    before, after = apply_changes(e, {**values, "amount_base": base, "exchange_rate": rate})
    e.reject_reason, e.updated_by = None, actor.user_id
    await _approval_state(db, actor, e)
    await record_audit(db, actor, "EXPENSE_UPDATED", "EXP", "expense", e.id, before=before, after=after, branch_id=e.branch_id)
    await db.commit()
    return await expense_view(db, e)


async def action(db: AsyncSession, actor: Principal, expense_id: uuid.UUID, verb: str, reason: str | None) -> dict:
    e = await _get(db, actor, expense_id)
    flagged = False
    if verb == "approve":
        actor.require("expenses.expense.approve")
        if e.status != "SUBMITTED":
            raise InvalidStateTransition("Only a submitted expense can be approved.")
        if e.created_by == actor.user_id:
            if not (await _settings(db, actor.company_id)).get("reduced_sod_mode"):
                raise SodViolation("You cannot approve your own expense.")
            flagged = True
        e.status, e.approved_by_name = "APPROVED", actor.full_name
    elif verb == "reject":
        actor.require("expenses.expense.approve")
        if e.status != "SUBMITTED":
            raise InvalidStateTransition("Only a submitted expense can be rejected.")
        if not reason or not reason.strip():
            raise ValidationFailed("reason", "A rejection reason is required.")
        e.status, e.reject_reason = "REJECTED", reason.strip()
    else:
        raise NotFound("Action")
    await record_audit(db, actor, f"EXPENSE_{verb.upper()}D" if verb == "approve" else "EXPENSE_REJECTED", "EXP", "expense", e.id, after={"no": e.expense_no, "reason": reason},
                       branch_id=e.branch_id, flagged=flagged)
    await db.commit()
    return await expense_view(db, e)


async def delete_expense(db: AsyncSession, actor: Principal, expense_id: uuid.UUID) -> None:
    e = await _get(db, actor, expense_id)
    if e.status == "APPROVED" or e.cash_movement_id:
        raise InvalidStateTransition("Only unapproved expenses can be deleted.")
    await db.delete(e)
    await record_audit(db, actor, "EXPENSE_DELETED", "EXP", "expense", expense_id, before={"no": e.expense_no}, branch_id=e.branch_id)
    await db.commit()


async def record_paid_out(db: AsyncSession, actor: Principal, session: CashierSession, movement: CashMovement, category_id: uuid.UUID) -> Expense:
    """A paid-out from the drawer becomes an approved expense (the cash movement approval covers it)."""
    category = await owned(db, ExpenseCategory, category_id, actor, "Expense category")
    if category.status != "ACTIVE":
        raise ValidationFailed("expense_category_id", "This category is inactive.")
    rate = Decimal(1)
    if movement.currency == "KHR":
        from app.services.org import current_rate

        current = await current_rate(db, actor.company_id)
        rate = current.rate if current else Decimal(1)
    branch = await db.get(Branch, session.branch_id)
    e = Expense(company_id=actor.company_id, expense_no=await next_number(db, actor.company_id, "EXPENSE", branch_code=branch.code if branch else None),
                date=datetime.now(UTC).date(), category_id=category.id, description=movement.reason, amount=movement.amount, currency=movement.currency, exchange_rate=rate,
                amount_base=(movement.amount / rate).quantize(CENT, ROUND_HALF_UP), payment_method="CASH_DRAWER", branch_id=session.branch_id, status="APPROVED",
                approved_by_name=movement.approved_by or "Within cash movement limit", session_id=session.id, cash_movement_id=movement.id, created_by=actor.user_id)
    db.add(e)
    await db.flush()
    movement.expense_id = e.id
    await record_audit(db, actor, "EXPENSE_RECORDED", "EXP", "expense", e.id, after={"no": e.expense_no, "paid_out": True, "amount": plain(e.amount_base)}, branch_id=e.branch_id)
    return e
