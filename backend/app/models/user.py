"""Users, access scope, employees, sessions and approvals (AUTH)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, SoftDelete, UUIDPk


class Employee(UUIDPk, Authored, Base):
    __tablename__ = "employees"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(30))
    name_en: Mapped[str] = mapped_column(String(200))
    name_km: Mapped[str] = mapped_column(String(200), default="")
    position: Mapped[str] = mapped_column(String(100), default="")
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"))
    phone: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        Index("uq_employees_company_code", "company_id", "code", unique=True),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )


class User(UUIDPk, Authored, SoftDelete, Base):
    __tablename__ = "users"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    username: Mapped[str] = mapped_column(String(60))
    email: Mapped[str] = mapped_column(String(254))
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(50), default="")
    language: Mapped[str] = mapped_column(String(2), default="en")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    # Lets the PIN be found without exposing it: HMAC of the PIN with the server secret, scoped per company.
    pin_lookup: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")
    mfa_enabled: Mapped[bool] = mapped_column(default=False)
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    first_failed_at: Mapped[datetime | None]
    locked_until: Mapped[datetime | None]
    last_login_at: Mapped[datetime | None]
    password_changed_at: Mapped[datetime | None]
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))

    __table_args__ = (
        Index("uq_users_username", text("lower(username)"), unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("uq_users_email", text("lower(email)"), unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("uq_users_employee", "employee_id", unique=True, postgresql_where=text("employee_id IS NOT NULL")),
        Index("ix_users_pin_lookup", "company_id", "pin_lookup"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
        CheckConstraint("language IN ('en','km')", name="language"),
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class UserBranchAccess(Base):
    """No rows for a user means access to every branch of the company (FR-AUTH-012)."""

    __tablename__ = "user_branch_access"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True)


class UserWarehouseAccess(Base):
    __tablename__ = "user_warehouse_access"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), primary_key=True)


class UserSession(UUIDPk, Base):
    """Server-side session behind the rotating refresh token (FR-AUTH-001, FR-AUTH-007)."""

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    # Current refresh token hash; rotated on every refresh. Reuse of an old token revokes the session.
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    previous_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    device: Mapped[str] = mapped_column(String(200), default="")
    ip_address: Mapped[str | None] = mapped_column(String(64))
    terminal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_terminals.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    absolute_expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoke_reason: Mapped[str | None] = mapped_column(String(50))


class PasswordResetToken(UUIDPk, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class LoginAttempt(Base):
    """Attempt log used for per-IP and per-terminal rate limiting (FR-AUTH-008, NFR-SEC-008)."""

    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(254))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    terminal_id: Mapped[uuid.UUID | None]
    method: Mapped[str] = mapped_column(String(10))
    succeeded: Mapped[bool]
    attempted_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)


class Approval(UUIDPk, Base):
    """Single-use supervisor approval bound to one action and requester (BR-POS-004, BR-SEC-002)."""

    __tablename__ = "approvals"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    action: Mapped[str] = mapped_column(String(30))
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), default=Decimal("0"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    self_approved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]

    __table_args__ = (CheckConstraint("self_approved OR approver_id <> requester_id", name="separation_of_duties"),)
