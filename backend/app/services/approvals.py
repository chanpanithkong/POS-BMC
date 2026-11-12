"""Supervisor approvals (BR-POS-004, BR-SEC-002).

A manager enters their PIN on the requester's screen. The server checks the
approver's permission, limit, branch scope and that they are a different user,
then issues a single-use token bound to the action, requester and amount. The
token expires after two minutes and is consumed by the guarded command.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Forbidden, NotAuthenticated
from app.core.security import new_opaque_token, pin_lookup, token_digest, verify_secret
from app.models import Approval, Company, User
from app.repositories.users import scope_ids
from app.services import audit
from app.services.principal import Principal, effective_rights

APPROVAL_TTL = timedelta(minutes=2)

ACTION_PERMISSION = {
    "DISCOUNT": ("pos.discount.apply", "discount_pct"),
    "PRICE_OVERRIDE": ("pos.price.override", "override_amount"),
    "CANCEL_SALE": ("pos.sale.cancel", None),
    "VOID_SALE": ("sales.sale.void", None),
    "REFUND": ("sales.return.approve", "refund_amount"),
    "SESSION_VARIANCE": ("cash.session.approve", None),
    "CASH_MOVEMENT": ("cash.session.approve", None),
}


class ApprovalRequired(AppError):
    status_code, code = 403, "APPROVAL_REQUIRED"

    def __init__(self, action: str, message: str):
        super().__init__(message, details=[{"action": action, "message": message}])


class SodViolation(AppError):
    status_code, code = 403, "SOD_VIOLATION"


class LimitExceeded(AppError):
    status_code, code = 403, "LIMIT_EXCEEDED"


async def reduced_sod(db: AsyncSession, company_id: uuid.UUID) -> bool:
    company = await db.get(Company, company_id)
    return bool(company and company.settings.get("reduced_sod_mode"))


async def verify_pin(db: AsyncSession, requester: Principal, *, pin: str, action: str, amount: Decimal) -> dict:
    permission, limit_key = ACTION_PERMISSION[action]
    approver = await db.scalar(select(User).where(User.company_id == requester.company_id, User.pin_lookup == pin_lookup(requester.company_id, pin), User.deleted_at.is_(None)))
    if approver is None or approver.status != "ACTIVE" or not verify_secret(approver.pin_hash, pin):
        raise NotAuthenticated("Incorrect supervisor PIN")
    _, perms, limits = await effective_rights(db, approver.id)
    if permission not in perms:
        raise Forbidden(f"{approver.full_name} cannot approve this action.")
    approver_branches = (await scope_ids(db, approver.id))["branch_ids"]
    if approver_branches and requester.branch_ids is not None and not set(approver_branches) & set(requester.branch_ids):
        raise Forbidden(f"{approver.full_name} is not assigned to this branch.")
    self_approved = approver.id == requester.user_id
    if self_approved and not await reduced_sod(db, requester.company_id):
        raise SodViolation("Approval must come from a different user.")
    if limit_key and amount > limits[limit_key]:
        raise LimitExceeded(f"{approver.full_name} can approve up to {limits[limit_key]} for this action.")
    token = new_opaque_token()
    expires_at = datetime.now(UTC) + APPROVAL_TTL
    db.add(Approval(company_id=requester.company_id, action=action, requester_id=requester.user_id, approver_id=approver.id, amount=amount, token_hash=token_digest(token), self_approved=self_approved, expires_at=expires_at))
    await audit.record(db, action="APPROVAL_GRANTED", module="APPROVALS", entity_type=action, entity_id=approver.id, company_id=requester.company_id, user_id=requester.user_id, user_name=requester.full_name, after={"approver": approver.full_name, "amount": str(amount)}, flagged=self_approved)
    await db.commit()
    return {"token": token, "approver_id": approver.id, "approver_name": approver.full_name, "expires_at": expires_at}


async def consume(db: AsyncSession, requester: Principal, *, token: str | None, action: str, amount: Decimal = Decimal("0"), message: str) -> Approval:
    """Used by guarded commands. Raises APPROVAL_REQUIRED when the token is missing, used, expired or too small."""
    if not token:
        raise ApprovalRequired(action, message)
    approval = await db.scalar(select(Approval).where(Approval.token_hash == token_digest(token)).with_for_update())
    now = datetime.now(UTC)
    if approval is None or approval.used_at or approval.expires_at <= now or approval.action != action or approval.company_id != requester.company_id:
        raise ApprovalRequired(action, "This approval has expired. Please request it again.")
    if approval.requester_id != requester.user_id:
        raise SodViolation("This approval belongs to a different request.")
    if amount > approval.amount:
        raise ApprovalRequired(action, "The approval does not cover this amount.")
    approval.used_at = now
    return approval
