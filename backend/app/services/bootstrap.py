"""Company bootstrap: default roles, system in-transit location and numbering sequences."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import DEFAULT_ROLES
from app.models import Company, DocumentSequence, Role, RolePermission, Warehouse, WarehouseLocation

DEFAULT_SEQUENCES = [
    # (doc_type, prefix, include_branch, include_year, padding) — formats configurable (BR-DOC-001, V-02).
    ("RECEIPT", "R", True, True, 6), ("INVOICE", "INV", True, True, 6), ("RETURN", "RET", True, True, 6),
    ("PO", "PO", False, True, 5), ("GRN", "GRN", False, True, 5), ("TRANSFER", "TRF", False, True, 5),
    ("ADJUSTMENT", "ADJ", False, True, 5), ("COUNT", "CNT", False, True, 5), ("SUPPLIER_RETURN", "PRT", False, True, 5),
    ("EXPENSE", "EXP", True, True, 5), ("SESSION", "S", False, False, 5),
]

# Proposed defaults from the SRS (labelled illustrative or proposed); every value is changeable.
DEFAULT_COMPANY_SETTINGS = {
    "tax_inclusive": False,
    "negative_stock_allowed": False,
    "reduced_sod_mode": False,
    "return_window_days": 7,
    "session_variance_tolerance_usd": "1.00",
    "session_variance_tolerance_khr": "4000",
    "over_delivery_tolerance_pct": "5",
    "pos_idle_lock_minutes": 2,
    "costing_method": "WAC",
    "costing_scope": "COMPANY",
}


async def ensure_default_roles(session: AsyncSession, company_id: uuid.UUID) -> dict[str, Role]:
    existing = {r.code: r for r in await session.scalars(select(Role).where(Role.company_id == company_id))}
    for code, definition in DEFAULT_ROLES.items():
        if code in existing:
            continue
        role = Role(
            company_id=company_id, code=code, name=definition.name, description=definition.description, is_system=True,
            limits={k: v for k, v in definition.limits.__dict__.items()},
        )
        session.add(role)
        await session.flush()
        session.add_all(RolePermission(role_id=role.id, permission_code=p) for p in sorted(definition.permissions))
        existing[code] = role
    await session.flush()
    return existing


async def ensure_system_locations(session: AsyncSession, company_id: uuid.UUID) -> WarehouseLocation:
    """One system IN_TRANSIT location per company for stock between warehouses (BR-TRF-001)."""
    warehouse = await session.scalar(select(Warehouse).where(Warehouse.company_id == company_id, Warehouse.is_system.is_(True)))
    if warehouse is None:
        warehouse = Warehouse(company_id=company_id, code="SYS-TRANSIT", name="In transit (system)", is_system=True)
        session.add(warehouse)
        await session.flush()
    location = await session.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == warehouse.id, WarehouseLocation.location_type == "IN_TRANSIT"))
    if location is None:
        location = WarehouseLocation(company_id=company_id, warehouse_id=warehouse.id, code="IN-TRANSIT", name="In transit", location_type="IN_TRANSIT")
        session.add(location)
        await session.flush()
    return location


async def ensure_sequences(session: AsyncSession, company_id: uuid.UUID) -> None:
    existing = set(await session.scalars(select(DocumentSequence.doc_type).where(DocumentSequence.company_id == company_id, DocumentSequence.scope_key == "")))
    for doc_type, prefix, include_branch, include_year, padding in DEFAULT_SEQUENCES:
        if doc_type not in existing:
            session.add(DocumentSequence(company_id=company_id, doc_type=doc_type, scope_key="", prefix=prefix, include_branch=include_branch, include_year=include_year, padding=padding))
    await session.flush()


async def create_company(session: AsyncSession, *, legal_name: str, trading_name: str) -> Company:
    company = Company(legal_name_en=legal_name, trading_name_en=trading_name, base_currency="USD", settings=dict(DEFAULT_COMPANY_SETTINGS))
    session.add(company)
    await session.flush()
    await ensure_default_roles(session, company.id)
    await ensure_system_locations(session, company.id)
    await ensure_sequences(session, company.id)
    return company
