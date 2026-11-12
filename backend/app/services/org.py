"""Company, settings, branches, warehouses, locations, terminals, tax codes, payment methods,
exchange rates, numbering and receipt templates (ORG, BRN; Phase 3)."""

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, NotFound, ValidationFailed
from app.models import (
    Branch,
    Company,
    DocumentSequence,
    ExchangeRate,
    LocationType,
    PosTerminal,
    ReceiptTemplate,
    TerminalCashier,
    User,
    Warehouse,
    WarehouseLocation,
)
from app.schemas import org as s
from app.services.common import apply_changes, ensure_unique, owned, plain, record_audit
from app.services.principal import Principal

MODULE = "ORG"
STORE_LOCATIONS = [("SHELF", "Sales floor", "SELLABLE"), ("STORE", "Back store", "STORAGE"), ("RECV", "Receiving", "RECEIVING"), ("DMG", "Damaged", "DAMAGED"), ("RET", "Returns", "RETURNS")]


# Company and settings

def company_view(c: Company) -> dict:
    return {**{f: getattr(c, f) for f in ("id", "legal_name_en", "legal_name_km", "trading_name_en", "trading_name_km", "address", "phone", "tax_id", "base_currency", "fiscal_year_start_month")}, "logo": c.logo_url}


async def get_company(db: AsyncSession, actor: Principal) -> Company:
    company = await db.get(Company, actor.company_id)
    assert company is not None
    return company


async def update_company(db: AsyncSession, actor: Principal, data: s.CompanyUpdate) -> dict:
    company = await get_company(db, actor)
    changes = data.model_dump(exclude_unset=True)
    if "logo" in changes:
        changes["logo_url"] = changes.pop("logo")
    before, after = apply_changes(company, changes)
    if after:
        await record_audit(db, actor, "COMPANY_UPDATED", MODULE, "company", company.id, before=before, after=after)
    await db.commit()
    return company_view(company)


def settings_view(company: Company) -> s.SystemSettings:
    known = {k: v for k, v in (company.settings or {}).items() if k in s.SystemSettings.model_fields}
    return s.SystemSettings.model_validate(known)


async def get_company_settings(db: AsyncSession, actor: Principal) -> s.SystemSettings:
    return settings_view(await get_company(db, actor))


async def update_company_settings(db: AsyncSession, actor: Principal, changes: dict[str, Any]) -> s.SystemSettings:
    company = await db.scalar(select(Company).where(Company.id == actor.company_id).with_for_update())
    assert company is not None
    current = settings_view(company)
    try:
        updated = s.SystemSettings.model_validate({**current.model_dump(), **changes})
    except ValidationError as exc:
        details = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        raise AppError("Invalid settings", code="VALIDATION_ERROR", status_code=422, details=details) from exc
    old, new = plain(current.model_dump()), plain(updated.model_dump())
    before = {k: old[k] for k in new if old[k] != new[k]}
    after = {k: new[k] for k in before}
    company.settings = {**(company.settings or {}), **new}
    if after:
        # Relaxing stock or approval controls is flagged for review (BR-SEC-002, D-06, D-13).
        risky = bool({"negative_stock_allowed", "reduced_sod_mode"} & set(after))
        await record_audit(db, actor, "SETTINGS_CHANGED", MODULE, "company", company.id, before=before, after=after, flagged=risky)
    await db.commit()
    return updated


# Branches

async def list_branches(db: AsyncSession, actor: Principal) -> list[Branch]:
    query = select(Branch).where(Branch.company_id == actor.company_id)
    if actor.branch_ids is not None:
        query = query.where(Branch.id.in_(actor.branch_ids))
    return list(await db.scalars(query.order_by(Branch.code)))


async def create_branch(db: AsyncSession, actor: Principal, data: s.BranchCreate) -> Branch:
    await ensure_unique(db, Branch, actor, "code", data.code)
    branch = Branch(company_id=actor.company_id, created_by=actor.user_id, **data.model_dump(exclude={"create_store_warehouse"}))
    db.add(branch)
    await db.flush()
    if data.create_store_warehouse:
        code = f"{data.code}-WH"[:20]
        await ensure_unique(db, Warehouse, actor, "code", code)
        warehouse = Warehouse(company_id=actor.company_id, branch_id=branch.id, code=code, name=f"{data.name_en} store"[:100], created_by=actor.user_id)
        db.add(warehouse)
        await db.flush()
        defaults = await _location_type_defaults(db)
        db.add_all(
            WarehouseLocation(company_id=actor.company_id, warehouse_id=warehouse.id, code=c, name=n, location_type=t, is_available_for_sale=defaults[t], created_by=actor.user_id)
            for c, n, t in STORE_LOCATIONS
        )
    await record_audit(db, actor, "BRANCH_CREATED", MODULE, "branch", branch.id, after=plain(data.model_dump()), branch_id=branch.id)
    await db.commit()
    return branch


async def update_branch(db: AsyncSession, actor: Principal, branch_id: uuid.UUID, data: s.BranchUpdate) -> Branch:
    branch = await owned(db, Branch, branch_id, actor, "Branch")
    actor.assert_branch(branch.id)
    changes = data.model_dump(exclude_unset=True)
    await ensure_unique(db, Branch, actor, "code", changes.get("code"), exclude=branch.id)
    before, after = apply_changes(branch, changes)
    branch.updated_by = actor.user_id
    if after:
        await record_audit(db, actor, "BRANCH_UPDATED", MODULE, "branch", branch.id, before=before, after=after, branch_id=branch.id)
    await db.commit()
    return branch


# Warehouses and locations

def warehouse_view(w: Warehouse) -> dict:
    return {"id": w.id, "code": w.code, "name": w.name, "branch_id": w.branch_id, "is_central": w.branch_id is None, "status": w.status}


def _visible_warehouses(actor: Principal):
    query = select(Warehouse).where(Warehouse.company_id == actor.company_id, Warehouse.is_system.is_(False))
    if actor.warehouse_ids is not None:
        query = query.where(Warehouse.id.in_(actor.warehouse_ids))
    elif actor.branch_ids is not None:
        query = query.where(Warehouse.branch_id.in_(actor.branch_ids) | Warehouse.branch_id.is_(None))
    return query


async def list_warehouses(db: AsyncSession, actor: Principal) -> list[dict]:
    return [warehouse_view(w) for w in await db.scalars(_visible_warehouses(actor).order_by(Warehouse.code))]


async def _branch(db: AsyncSession, actor: Principal, branch_id: uuid.UUID | None) -> None:
    if branch_id is not None:
        await owned(db, Branch, branch_id, actor, "Branch")
        actor.assert_branch(branch_id)


async def _editable_warehouse(db: AsyncSession, actor: Principal, warehouse_id: uuid.UUID) -> Warehouse:
    warehouse = await owned(db, Warehouse, warehouse_id, actor, "Warehouse")
    if warehouse.is_system:
        raise NotFound("Warehouse")
    if actor.warehouse_ids is not None and warehouse.id not in actor.warehouse_ids:
        raise NotFound("Warehouse")
    return warehouse


async def create_warehouse(db: AsyncSession, actor: Principal, data: s.WarehouseCreate) -> dict:
    await ensure_unique(db, Warehouse, actor, "code", data.code)
    await _branch(db, actor, data.branch_id)
    warehouse = Warehouse(company_id=actor.company_id, created_by=actor.user_id, **data.model_dump())
    db.add(warehouse)
    await db.flush()
    await record_audit(db, actor, "WAREHOUSE_CREATED", MODULE, "warehouse", warehouse.id, after=plain(data.model_dump()), branch_id=data.branch_id)
    await db.commit()
    return warehouse_view(warehouse)


async def update_warehouse(db: AsyncSession, actor: Principal, warehouse_id: uuid.UUID, data: s.WarehouseUpdate) -> dict:
    warehouse = await _editable_warehouse(db, actor, warehouse_id)
    changes = data.model_dump(exclude_unset=True)
    await ensure_unique(db, Warehouse, actor, "code", changes.get("code"), exclude=warehouse.id)
    if "branch_id" in changes:
        await _branch(db, actor, changes["branch_id"])
    before, after = apply_changes(warehouse, changes)
    warehouse.updated_by = actor.user_id
    if after:
        await record_audit(db, actor, "WAREHOUSE_UPDATED", MODULE, "warehouse", warehouse.id, before=before, after=after, branch_id=warehouse.branch_id)
    await db.commit()
    return warehouse_view(warehouse)


def location_view(loc: WarehouseLocation) -> dict:
    return {"id": loc.id, "code": loc.code, "name": loc.name, "warehouse_id": loc.warehouse_id, "type": loc.location_type, "available_to_sell": loc.is_available_for_sale, "status": loc.status}


async def _location_type_defaults(db: AsyncSession) -> dict[str, bool]:
    return {t.code: t.default_available_for_sale for t in await db.scalars(select(LocationType))}


async def list_locations(db: AsyncSession, actor: Principal, warehouse_id: uuid.UUID | None = None) -> list[dict]:
    visible = _visible_warehouses(actor).with_only_columns(Warehouse.id)
    query = select(WarehouseLocation).where(WarehouseLocation.company_id == actor.company_id, WarehouseLocation.warehouse_id.in_(visible))
    if warehouse_id:
        query = query.where(WarehouseLocation.warehouse_id == warehouse_id)
    return [location_view(loc) for loc in await db.scalars(query.order_by(WarehouseLocation.code))]


def _check_sellable(location_type: str, available: bool) -> None:
    if available and location_type in ("DAMAGED", "EXPIRED", "QUARANTINE", "RECEIVING", "RETURNS"):
        raise ValidationFailed("available_to_sell", f"{location_type} locations cannot be available for sale.")


async def create_location(db: AsyncSession, actor: Principal, data: s.LocationCreate) -> dict:
    warehouse = await _editable_warehouse(db, actor, data.warehouse_id)
    if await db.scalar(select(WarehouseLocation.id).where(WarehouseLocation.warehouse_id == warehouse.id, WarehouseLocation.code == data.code)):
        raise Conflict("A location with this code already exists in the warehouse.", code="DUPLICATE")
    available = data.available_to_sell if data.available_to_sell is not None else (await _location_type_defaults(db))[data.type]
    _check_sellable(data.type, available)
    location = WarehouseLocation(company_id=actor.company_id, warehouse_id=warehouse.id, code=data.code, name=data.name, location_type=data.type, is_available_for_sale=available, status=data.status, created_by=actor.user_id)
    db.add(location)
    await db.flush()
    await record_audit(db, actor, "LOCATION_CREATED", MODULE, "location", location.id, after=plain(data.model_dump()), branch_id=warehouse.branch_id)
    await db.commit()
    return location_view(location)


async def update_location(db: AsyncSession, actor: Principal, location_id: uuid.UUID, data: s.LocationUpdate) -> dict:
    location = await owned(db, WarehouseLocation, location_id, actor, "Location")
    warehouse = await _editable_warehouse(db, actor, location.warehouse_id)
    changes = data.model_dump(exclude_unset=True)
    if "type" in changes:
        changes["location_type"] = changes.pop("type")
    if "available_to_sell" in changes:
        changes["is_available_for_sale"] = changes.pop("available_to_sell")
    if changes.get("code") and await db.scalar(select(WarehouseLocation.id).where(WarehouseLocation.warehouse_id == warehouse.id, WarehouseLocation.code == changes["code"], WarehouseLocation.id != location.id)):
        raise Conflict("A location with this code already exists in the warehouse.", code="DUPLICATE")
    _check_sellable(changes.get("location_type", location.location_type), changes.get("is_available_for_sale", location.is_available_for_sale))
    before, after = apply_changes(location, changes)
    location.updated_by = actor.user_id
    if after:
        await record_audit(db, actor, "LOCATION_UPDATED", MODULE, "location", location.id, before=before, after=after, branch_id=warehouse.branch_id)
    await db.commit()
    return location_view(location)


# Terminals

async def terminal_view(db: AsyncSession, t: PosTerminal) -> dict:
    cashiers = list(await db.scalars(select(TerminalCashier.user_id).where(TerminalCashier.terminal_id == t.id)))
    return {**{f: getattr(t, f) for f in ("id", "code", "name", "branch_id", "default_location_id", "printer_profile", "cash_drawer", "status")}, "assigned_cashier_ids": cashiers}


async def list_terminals(db: AsyncSession, actor: Principal) -> list[dict]:
    query = select(PosTerminal).where(PosTerminal.company_id == actor.company_id)
    if actor.branch_ids is not None:
        query = query.where(PosTerminal.branch_id.in_(actor.branch_ids))
    return [await terminal_view(db, t) for t in await db.scalars(query.order_by(PosTerminal.code))]


async def _check_terminal_location(db: AsyncSession, actor: Principal, branch_id: uuid.UUID, location_id: uuid.UUID) -> None:
    location = await owned(db, WarehouseLocation, location_id, actor, "Location")
    warehouse = await db.get(Warehouse, location.warehouse_id)
    if warehouse is None or warehouse.branch_id != branch_id or not location.is_available_for_sale:
        raise ValidationFailed("default_location_id", "The default location must be a sellable location in the terminal's branch.")


async def _set_cashiers(db: AsyncSession, actor: Principal, terminal_id: uuid.UUID, user_ids: list[uuid.UUID]) -> None:
    ids = list(dict.fromkeys(user_ids))
    if ids:
        found = set(await db.scalars(select(User.id).where(User.id.in_(ids), User.company_id == actor.company_id, User.deleted_at.is_(None))))
        if found != set(ids):
            raise ValidationFailed("assigned_cashier_ids", "One or more users do not exist.")
    await db.execute(delete(TerminalCashier).where(TerminalCashier.terminal_id == terminal_id))
    db.add_all(TerminalCashier(terminal_id=terminal_id, user_id=u) for u in ids)


async def create_terminal(db: AsyncSession, actor: Principal, data: s.TerminalCreate) -> dict:
    await ensure_unique(db, PosTerminal, actor, "code", data.code)
    await _branch(db, actor, data.branch_id)
    await _check_terminal_location(db, actor, data.branch_id, data.default_location_id)
    terminal = PosTerminal(company_id=actor.company_id, created_by=actor.user_id, **data.model_dump(exclude={"assigned_cashier_ids"}))
    db.add(terminal)
    await db.flush()
    await _set_cashiers(db, actor, terminal.id, data.assigned_cashier_ids)
    await db.flush()
    await record_audit(db, actor, "TERMINAL_REGISTERED", MODULE, "terminal", terminal.id, after=plain(data.model_dump()), branch_id=terminal.branch_id)
    await db.commit()
    return await terminal_view(db, terminal)


async def update_terminal(db: AsyncSession, actor: Principal, terminal_id: uuid.UUID, data: s.TerminalUpdate) -> dict:
    terminal = await owned(db, PosTerminal, terminal_id, actor, "Terminal")
    actor.assert_branch(terminal.branch_id)
    changes = data.model_dump(exclude_unset=True)
    cashiers = changes.pop("assigned_cashier_ids", None)
    await ensure_unique(db, PosTerminal, actor, "code", changes.get("code"), exclude=terminal.id)
    if changes.get("default_location_id"):
        await _check_terminal_location(db, actor, terminal.branch_id, changes["default_location_id"])
    before, after = apply_changes(terminal, changes)
    if cashiers is not None:
        old = (await terminal_view(db, terminal))["assigned_cashier_ids"]
        await _set_cashiers(db, actor, terminal.id, cashiers)
        if set(old) != set(cashiers):
            before["assigned_cashier_ids"], after["assigned_cashier_ids"] = plain(old), plain(cashiers)
    terminal.updated_by = actor.user_id
    await db.flush()
    if after:
        await record_audit(db, actor, "TERMINAL_UPDATED", MODULE, "terminal", terminal.id, before=before, after=after, branch_id=terminal.branch_id)
    await db.commit()
    return await terminal_view(db, terminal)


# Simple company-level records: tax codes, payment methods, receipt templates

async def list_records(db: AsyncSession, actor: Principal, model: type, order: Any) -> list:
    return list(await db.scalars(select(model).where(model.company_id == actor.company_id).order_by(order)))


async def create_record(db: AsyncSession, actor: Principal, model: type, data: Any, entity: str, *, unique: str | None = "code") -> Any:
    if unique:
        await ensure_unique(db, model, actor, unique, getattr(data, unique))
    values = data.model_dump()
    if values.get("branch_id"):
        await _branch(db, actor, values["branch_id"])
    record = model(company_id=actor.company_id, created_by=actor.user_id, **values)
    db.add(record)
    await db.flush()
    await record_audit(db, actor, f"{entity.upper()}_CREATED", MODULE, entity, record.id, after=plain(values))
    await db.commit()
    return record


async def update_record(db: AsyncSession, actor: Principal, model: type, record_id: uuid.UUID, data: Any, entity: str, what: str, *, unique: str | None = "code") -> Any:
    record = await owned(db, model, record_id, actor, what)
    changes = data.model_dump(exclude_unset=True)
    if unique:
        await ensure_unique(db, model, actor, unique, changes.get(unique), exclude=record.id)
    if changes.get("branch_id"):
        await _branch(db, actor, changes["branch_id"])
    before, after = apply_changes(record, changes)
    record.updated_by = actor.user_id
    if after:
        await record_audit(db, actor, f"{entity.upper()}_UPDATED", MODULE, entity, record.id, before=before, after=after, flagged=entity == "tax_code" and "rate" in after)
    await db.commit()
    return record


async def delete_receipt_template(db: AsyncSession, actor: Principal, template_id: uuid.UUID) -> None:
    template = await owned(db, ReceiptTemplate, template_id, actor, "Receipt template")
    await db.delete(template)
    await record_audit(db, actor, "RECEIPT_TEMPLATE_DELETED", MODULE, "receipt_template", template_id, before={"name": template.name})
    await db.commit()


# Exchange rates

async def list_rates(db: AsyncSession, actor: Principal, limit: int = 100) -> list[dict]:
    rows = await db.execute(
        select(ExchangeRate, User.full_name).outerjoin(User, User.id == ExchangeRate.created_by).where(ExchangeRate.company_id == actor.company_id).order_by(ExchangeRate.effective_at.desc()).limit(limit)
    )
    return [{"id": r.id, "from_": r.from_currency, "to": r.to_currency, "rate": r.rate, "effective_at": r.effective_at, "created_by": name or "System"} for r, name in rows]


async def current_rate(db: AsyncSession, company_id: uuid.UUID, from_currency: str = "USD", to_currency: str = "KHR") -> ExchangeRate | None:
    return await db.scalar(
        select(ExchangeRate).where(ExchangeRate.company_id == company_id, ExchangeRate.from_currency == from_currency, ExchangeRate.to_currency == to_currency).order_by(ExchangeRate.effective_at.desc()).limit(1)
    )


async def create_rate(db: AsyncSession, actor: Principal, data: s.ExchangeRateCreate) -> dict:
    """Rates are append-only: a new rate applies to new sales; finalized sales keep the rate they used (BR-PAY-002)."""
    previous = await current_rate(db, actor.company_id, data.from_, data.to)
    rate = ExchangeRate(company_id=actor.company_id, from_currency=data.from_, to_currency=data.to, rate=data.rate, created_by=actor.user_id)
    db.add(rate)
    await db.flush()
    await db.refresh(rate)
    await record_audit(db, actor, "EXCHANGE_RATE_SET", MODULE, "exchange_rate", rate.id, before={"rate": str(previous.rate)} if previous else None, after={"pair": f"{data.from_}/{data.to}", "rate": str(data.rate)})
    await db.commit()
    return {"id": rate.id, "from_": rate.from_currency, "to": rate.to_currency, "rate": rate.rate, "effective_at": rate.effective_at, "created_by": actor.full_name}


# Numbering

def sequence_view(seq: DocumentSequence) -> dict:
    parts = [p for p in ("BR" if seq.include_branch else "", "YYYY" if seq.include_year else "") if p]
    number = str(seq.next_value).zfill(seq.padding)
    preview = "-".join([seq.prefix, *parts, number]) if seq.prefix else number
    return {"id": seq.doc_type, "doc_type": seq.doc_type, "prefix": seq.prefix, "next_value": seq.next_value, "padding": seq.padding, "include_branch": seq.include_branch, "include_year": seq.include_year, "preview": preview}


async def list_sequences(db: AsyncSession, actor: Principal) -> list[dict]:
    rows = await db.scalars(select(DocumentSequence).where(DocumentSequence.company_id == actor.company_id, DocumentSequence.scope_key == "").order_by(DocumentSequence.doc_type))
    return [sequence_view(r) for r in rows]


async def update_sequence(db: AsyncSession, actor: Principal, doc_type: str, data: s.SequenceUpdate) -> dict:
    seq = await db.scalar(select(DocumentSequence).where(DocumentSequence.company_id == actor.company_id, DocumentSequence.doc_type == doc_type, DocumentSequence.scope_key == "").with_for_update())
    if seq is None:
        raise NotFound("Document sequence")
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "next_value" in changes and changes["next_value"] < seq.next_value:
        # Lowering the counter could reissue a number already printed (BR-DOC-001).
        raise ValidationFailed("next_value", f"Next value cannot go below {seq.next_value}; document numbers are never reused.")
    before, after = apply_changes(seq, changes)
    if after:
        await record_audit(db, actor, "SEQUENCE_UPDATED", MODULE, "document_sequence", doc_type, before=before, after=after, flagged=True)
    await db.commit()
    return sequence_view(seq)
