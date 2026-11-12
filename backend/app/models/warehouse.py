"""Warehouses and stock locations (ORG, SRS 5.2)."""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Authored, Base, UUIDPk


class LocationType(Base):
    """Reference list of location purposes; only sellable ones count as available to sell."""

    __tablename__ = "location_types"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    default_available_for_sale: Mapped[bool] = mapped_column(default=False)
    is_system: Mapped[bool] = mapped_column(default=False)


class Warehouse(UUIDPk, Authored, Base):
    __tablename__ = "warehouses"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    # Null for a central warehouse serving several branches.
    branch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("branches.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    is_system: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("company_id", "code"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
    )


class WarehouseLocation(UUIDPk, Authored, Base):
    __tablename__ = "warehouse_locations"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    location_type: Mapped[str] = mapped_column(ForeignKey("location_types.code"))
    is_available_for_sale: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE")

    __table_args__ = (
        UniqueConstraint("warehouse_id", "code"),
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="status"),
        # IN_TRANSIT stock is never sellable.
        CheckConstraint("NOT (location_type = 'IN_TRANSIT' AND is_available_for_sale)", name="transit_not_sellable"),
    )
