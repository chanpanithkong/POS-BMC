import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import EmailStr, Field

from app.schemas.common import Command, Out


class UserOut(Out):
    id: uuid.UUID
    username: str
    email: str
    full_name: str
    phone: str
    language: str
    status: str
    role_ids: list[uuid.UUID]
    branch_ids: list[uuid.UUID]
    warehouse_ids: list[uuid.UUID]
    terminal_ids: list[uuid.UUID]
    employee_id: uuid.UUID | None
    has_pin: bool
    mfa_enabled: bool
    last_login_at: datetime | None
    locked_until: datetime | None
    created_at: datetime


class UserCreate(Command):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(default="", max_length=50)
    language: str = Field(default="en", pattern="^(en|km)$")
    password: str = Field(max_length=256, description="Initial password; the user should change it after first sign-in.")
    role_ids: list[uuid.UUID] = []
    branch_ids: list[uuid.UUID] = []
    warehouse_ids: list[uuid.UUID] = []
    employee_id: uuid.UUID | None = None


class UserUpdate(Command):
    username: str | None = Field(default=None, min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._-]+$")
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    language: str | None = Field(default=None, pattern="^(en|km)$")
    role_ids: list[uuid.UUID] | None = None
    branch_ids: list[uuid.UUID] | None = None
    warehouse_ids: list[uuid.UUID] | None = None
    employee_id: uuid.UUID | None = None
    password: str | None = Field(default=None, max_length=256, description="Administrator password reset")


class StatusUpdate(Command):
    status: str = Field(pattern="^(ACTIVE|INACTIVE)$")


class PinUpdate(Command):
    pin: str = Field(min_length=4, max_length=6)


class RoleLimitsModel(Command):
    discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    override_amount: Decimal = Field(default=Decimal("0"), ge=0)
    refund_amount: Decimal = Field(default=Decimal("0"), ge=0)
    adjustment_value: Decimal = Field(default=Decimal("0"), ge=0)
    po_approval_limit: Decimal = Field(default=Decimal("0"), ge=0)


class RoleOut(Out):
    id: uuid.UUID
    code: str
    name: str
    description: str
    is_system: bool
    permissions: list[str]
    limits: dict[str, Decimal]
    sod_conflicts: list[str]


class RoleCreate(Command):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = []
    limits: RoleLimitsModel = RoleLimitsModel()


class RoleUpdate(Command):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None
    limits: RoleLimitsModel | None = None


class PermissionOut(Out):
    code: str
    module: str
    description: str


class EmployeeOut(Out):
    id: uuid.UUID
    code: str
    name_en: str
    name_km: str
    position: str
    branch_id: uuid.UUID | None
    phone: str
    status: str


class EmployeeCreate(Command):
    code: str = Field(min_length=1, max_length=30)
    name_en: str = Field(min_length=1, max_length=200)
    name_km: str = Field(default="", max_length=200)
    position: str = Field(default="", max_length=100)
    branch_id: uuid.UUID | None = None
    phone: str = Field(default="", max_length=50)
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|INACTIVE)$")


class EmployeeUpdate(Command):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name_en: str | None = Field(default=None, min_length=1, max_length=200)
    name_km: str | None = Field(default=None, max_length=200)
    position: str | None = Field(default=None, max_length=100)
    branch_id: uuid.UUID | None = None
    phone: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE)$")


class AuditLogOut(Out):
    id: int
    occurred_at: datetime
    user_id: uuid.UUID | None
    user_name: str
    action: str
    module: str
    entity_type: str
    entity_id: str
    branch_id: uuid.UUID | None
    before: dict | None
    after: dict | None
    flagged: bool
    correlation_id: str | None
