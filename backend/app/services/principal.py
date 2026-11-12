"""The signed-in user's effective permissions, limits and data scope."""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Forbidden, NotFound
from app.models import Role, RolePermission, User, UserBranchAccess, UserRole, UserWarehouseAccess

LIMIT_KEYS = ("discount_pct", "override_amount", "refund_amount", "adjustment_value", "po_approval_limit")


@dataclass
class Principal:
    user_id: uuid.UUID
    company_id: uuid.UUID
    session_id: uuid.UUID
    username: str
    full_name: str
    permissions: frozenset[str]
    limits: dict[str, Decimal]
    role_codes: list[str]
    # None means every branch or warehouse of the company (FR-AUTH-012).
    branch_ids: frozenset[uuid.UUID] | None
    warehouse_ids: frozenset[uuid.UUID] | None
    terminal_id: uuid.UUID | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def can(self, *any_of: str) -> bool:
        return any(code in self.permissions for code in any_of)

    def require(self, *any_of: str) -> None:
        if not self.can(*any_of):
            raise Forbidden("You do not have permission to do this.")

    @property
    def sees_cost(self) -> bool:
        return "inventory.cost.view" in self.permissions

    def has_branch(self, branch_id: uuid.UUID | None) -> bool:
        return branch_id is None or self.branch_ids is None or branch_id in self.branch_ids

    def assert_branch(self, branch_id: uuid.UUID | None) -> None:
        """Out-of-scope records look missing, so their existence is not revealed (BR-SEC-001)."""
        if not self.has_branch(branch_id):
            raise NotFound()

    def assert_company(self, company_id: uuid.UUID) -> None:
        if company_id != self.company_id:
            raise NotFound()


async def effective_rights(db: AsyncSession, user_id: uuid.UUID) -> tuple[list[Role], frozenset[str], dict[str, Decimal]]:
    roles = list(await db.scalars(select(Role).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id).order_by(Role.name)))
    perms = frozenset(await db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id.in_([r.id for r in roles])))) if roles else frozenset()
    limits = {key: max((Decimal(str(r.limits.get(key, "0"))) for r in roles), default=Decimal("0")) for key in LIMIT_KEYS}
    return roles, perms, limits


async def load_principal(db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, terminal_id: uuid.UUID | None = None) -> Principal | None:
    user = await db.get(User, user_id)
    if user is None or user.status != "ACTIVE" or user.deleted_at is not None:
        return None
    roles, perms, limits = await effective_rights(db, user.id)
    branches = frozenset(await db.scalars(select(UserBranchAccess.branch_id).where(UserBranchAccess.user_id == user.id)))
    warehouses = frozenset(await db.scalars(select(UserWarehouseAccess.warehouse_id).where(UserWarehouseAccess.user_id == user.id)))
    return Principal(
        user_id=user.id, company_id=user.company_id, session_id=session_id, username=user.username, full_name=user.full_name,
        permissions=perms, limits=limits, role_codes=[r.code for r in roles],
        branch_ids=branches or None, warehouse_ids=warehouses or None, terminal_id=terminal_id,
    )
