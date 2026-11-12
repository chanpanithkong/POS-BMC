"""Read helpers for users and their access scope."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PosTerminal, TerminalCashier, User, UserBranchAccess, UserRole, UserWarehouseAccess


async def find_by_login(db: AsyncSession, login: str) -> User | None:
    value = login.strip().lower()
    return await db.scalar(select(User).where(or_(func.lower(User.username) == value, func.lower(User.email) == value), User.deleted_at.is_(None)))


async def scope_ids(db: AsyncSession, user_id: uuid.UUID) -> dict[str, list[uuid.UUID]]:
    roles = list(await db.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id)))
    branches = list(await db.scalars(select(UserBranchAccess.branch_id).where(UserBranchAccess.user_id == user_id)))
    warehouses = list(await db.scalars(select(UserWarehouseAccess.warehouse_id).where(UserWarehouseAccess.user_id == user_id)))
    terminals = list(await db.scalars(select(TerminalCashier.terminal_id).where(TerminalCashier.user_id == user_id)))
    return {"role_ids": roles, "branch_ids": branches, "warehouse_ids": warehouses, "terminal_ids": terminals}


async def user_view(db: AsyncSession, user: User) -> dict:
    return {
        "id": user.id, "company_id": user.company_id, "username": user.username, "email": user.email, "full_name": user.full_name,
        "phone": user.phone, "language": user.language, "status": user.status, "employee_id": user.employee_id,
        "has_pin": user.pin_hash is not None, "mfa_enabled": user.mfa_enabled, "last_login_at": user.last_login_at,
        "locked_until": user.locked_until, "created_at": user.created_at, **await scope_ids(db, user.id),
    }


async def terminal_for_company(db: AsyncSession, terminal_id: uuid.UUID, company_id: uuid.UUID | None = None) -> PosTerminal | None:
    terminal = await db.get(PosTerminal, terminal_id)
    if terminal is None or (company_id and terminal.company_id != company_id):
        return None
    return terminal
