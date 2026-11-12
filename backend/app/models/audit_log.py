"""Append-only audit trail with a hash chain (BR-AUD-001, NFR-SEC-011).

A database trigger (migration 0001) rejects UPDATE and DELETE on this table.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    user_name: Mapped[str] = mapped_column(String(200), default="System")
    action: Mapped[str] = mapped_column(String(60))
    module: Mapped[str] = mapped_column(String(20))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    branch_id: Mapped[uuid.UUID | None]
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    flagged: Mapped[bool] = mapped_column(default=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_user_time", "user_id", "occurred_at"),
        Index("ix_audit_logs_company_time", "company_id", "occurred_at"),
    )
