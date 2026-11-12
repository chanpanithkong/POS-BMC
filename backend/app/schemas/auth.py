import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import Command, Out


class LoginRequest(Command):
    username: str = Field(min_length=1, max_length=254, description="Username or email")
    password: str = Field(min_length=1, max_length=256)


class PinLoginRequest(Command):
    pin: str = Field(min_length=4, max_length=6)
    terminal_id: uuid.UUID


class RoleRef(Out):
    id: uuid.UUID
    code: str
    name: str


class SessionUser(Out):
    """Current user with effective rights. Shape matches the frontend `SessionUser` type."""

    id: uuid.UUID
    company_id: uuid.UUID
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
    roles: list[RoleRef]
    permissions: list[str]
    limits: dict[str, Decimal]
    home_path: str


class AuthResponse(Out):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: SessionUser


class UpdateMeRequest(Command):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    language: str | None = Field(default=None, pattern="^(en|km)$")


class ChangePasswordRequest(Command):
    current_password: str
    new_password: str = Field(max_length=256)


class ForgotPasswordRequest(Command):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordRequest(Command):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(max_length=256)


class MessageResponse(Out):
    message: str


class SessionOut(Out):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    device: str
    ip_address: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


class ApprovalRequest(Command):
    pin: str = Field(min_length=4, max_length=6)
    action: str = Field(pattern="^(DISCOUNT|PRICE_OVERRIDE|CANCEL_SALE|VOID_SALE|REFUND|SESSION_VARIANCE|CASH_MOVEMENT)$")
    amount: Decimal = Field(default=Decimal("0"), ge=0)


class ApprovalGrant(Out):
    token: str
    approver_id: uuid.UUID
    approver_name: str
    expires_at: datetime
