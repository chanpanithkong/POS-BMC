"""Import every model so Alembic and the metadata see all tables."""

from app.models.audit_log import AuditLog
from app.models.branch import Branch, PosTerminal, TerminalCashier
from app.models.company import Company, Currency, DocumentSequence, ExchangeRate, TaxCode
from app.models.platform import IdempotencyKey, OutboxEvent
from app.models.role import Permission, Role, RolePermission
from app.models.user import (
    Approval,
    Employee,
    LoginAttempt,
    PasswordResetToken,
    User,
    UserBranchAccess,
    UserRole,
    UserSession,
    UserWarehouseAccess,
)
from app.models.warehouse import LocationType, Warehouse, WarehouseLocation

__all__ = [
    "Approval", "AuditLog", "Branch", "Company", "Currency", "DocumentSequence", "Employee", "ExchangeRate", "IdempotencyKey",
    "LocationType", "LoginAttempt", "OutboxEvent", "PasswordResetToken", "Permission", "PosTerminal", "Role", "RolePermission",
    "TaxCode", "TerminalCashier", "User", "UserBranchAccess", "UserRole", "UserSession", "UserWarehouseAccess", "Warehouse",
    "WarehouseLocation",
]
