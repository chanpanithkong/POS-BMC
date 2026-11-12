"""Roles and permissions (FR-AUTH-006, SRS 4.2)."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, UUIDPk


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    module: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text, default="")


class Role(UUIDPk, Authored, Base):
    __tablename__ = "roles"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    is_system: Mapped[bool] = mapped_column(default=False)
    # Decimal strings: discount_pct, override_amount, refund_amount, adjustment_value, po_approval_limit.
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (UniqueConstraint("company_id", "code"),)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True)
