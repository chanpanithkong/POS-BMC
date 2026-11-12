"""Branches and POS terminals (ORG, BRN)."""

import uuid
from datetime import time

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, UUIDPk


class Branch(UUIDPk, Authored, Base):
    __tablename__ = "branches"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(200))
    name_km: Mapped[str] = mapped_column(String(200), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    receipt_header: Mapped[str] = mapped_column(String(200), default="")
    open_time: Mapped[time | None] = mapped_column(Time)
    close_time: Mapped[time | None] = mapped_column(Time)
    # Sales before this time belong to the previous business date (BR-SAL-008).
    day_cutoff: Mapped[time] = mapped_column(Time, default=time(0, 0))
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Phnom_Penh")
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )


class PosTerminal(UUIDPk, Authored, Base):
    __tablename__ = "pos_terminals"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    branch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("branches.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    default_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse_locations.id"))
    printer_profile: Mapped[str] = mapped_column(String(10), default="80mm")
    cash_drawer: Mapped[bool] = mapped_column(default=True)
    # Hash of the device token issued at registration; requests send X-Terminal-Id (FR-ORG-005).
    device_token_hash: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("printer_profile IN ('58mm','80mm')", name="printer_profile"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )


class TerminalCashier(Base):
    """Cashiers allowed on a terminal. No rows means any permitted cashier (FR-ORG-006)."""

    __tablename__ = "terminal_cashiers"

    terminal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pos_terminals.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
