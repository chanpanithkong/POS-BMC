"""Idempotency keys and the transactional outbox (SRS 13.1, 12.6)."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, SmallInteger, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    # Scope is "<company>:<terminal or user>:<route>" so keys from different clients never collide.
    scope: Mapped[str] = mapped_column(String(200), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(15), default="IN_PROGRESS")
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)

    __table_args__ = (CheckConstraint("status IN ('IN_PROGRESS','COMPLETED')", name="status"),)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    published_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (Index("ix_outbox_unpublished", "id", postgresql_where=text("published_at IS NULL")),)
