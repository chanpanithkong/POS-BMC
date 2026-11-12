"""Declarative base, naming conventions and shared column mixins."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from sqlalchemy import DateTime, ForeignKey, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.utils.ids import uuid7

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Exact decimal types (NFR-INT-010). Never use Float for money or quantities.
Money = Annotated[Decimal, mapped_column(Numeric(19, 4))]
Quantity = Annotated[Decimal, mapped_column(Numeric(19, 4))]
Rate = Annotated[Decimal, mapped_column(Numeric(20, 8))]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {datetime: DateTime(timezone=True), uuid.UUID: UUID(as_uuid=True)}


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)


class Timestamps:
    # Load server-generated values (created_at, updated_at) with RETURNING, so async code never lazy-loads them.
    __mapper_args__ = {"eager_defaults": True}

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Authored(Timestamps):
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", use_alter=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", use_alter=True))


class SoftDelete:
    deleted_at: Mapped[datetime | None]
