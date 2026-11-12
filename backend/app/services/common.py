"""Small helpers shared by master-data services: scoped lookup, uniqueness, audited updates, numbering."""

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFound
from app.models import DocumentSequence
from app.services import audit
from app.services.principal import Principal

M = TypeVar("M")


async def owned(db: AsyncSession, model: type[M], record_id: uuid.UUID, actor: Principal, what: str, *, lock: bool = False) -> M:
    """Loads a company record; anything outside the caller's company looks missing (BR-SEC-001)."""
    query = select(model).where(model.id == record_id, model.company_id == actor.company_id)  # type: ignore[attr-defined]
    if hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))  # type: ignore[attr-defined]
    if lock:
        query = query.with_for_update()
    record = await db.scalar(query)
    if record is None:
        raise NotFound(what)
    return record


async def ensure_unique(db: AsyncSession, model: type, actor: Principal, field: str, value: str | None, *, exclude: uuid.UUID | None = None, case_insensitive: bool = True) -> None:
    if value is None:
        return
    column = getattr(model, field)
    query = select(model.id).where(model.company_id == actor.company_id, func.lower(column) == value.lower() if case_insensitive else column == value)
    if hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))
    if exclude:
        query = query.where(model.id != exclude)
    if await db.scalar(query.limit(1)):
        label = field.replace("_", " ").capitalize()
        raise AppError(f"{label} '{value}' already exists.", code="DUPLICATE", status_code=409, details=[{"field": field, "message": f"{label} already exists."}])


def num(value: Decimal) -> str:
    """A quantity or amount for messages: 50, 2.5, 0.75 (never 5E+1 or 2.5000)."""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID | Decimal | datetime | date | time):
        return str(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


def apply_changes(record: Any, changes: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Sets attributes and returns (before, after) for the fields that actually changed."""
    before, after = {}, {}
    for field, value in changes.items():
        old = getattr(record, field)
        if old != value:
            before[field], after[field] = plain(old), plain(value)
            setattr(record, field, value)
    return before, after


async def record_audit(db: AsyncSession, actor: Principal, action: str, module: str, entity_type: str, entity_id: Any, *, before: dict | None = None, after: dict | None = None, flagged: bool = False, branch_id: uuid.UUID | None = None) -> None:
    await audit.record(
        db, action=action, module=module, entity_type=entity_type, entity_id=entity_id, company_id=actor.company_id,
        user_id=actor.user_id, user_name=actor.full_name, branch_id=branch_id, before=before, after=after, flagged=flagged,
    )


async def next_number(db: AsyncSession, company_id: uuid.UUID, doc_type: str, *, branch_code: str | None = None, on: date | None = None) -> str:
    template, parts, value = await allocate(db, company_id, doc_type, branch_code=branch_code, on=on)
    return "-".join([template.prefix, *parts, str(value).zfill(template.padding)]) if template.prefix else str(value).zfill(template.padding)


async def allocate(db: AsyncSession, company_id: uuid.UUID, doc_type: str, *, branch_code: str | None = None, on: date | None = None) -> tuple[DocumentSequence, list[str], int]:
    """Allocates the next document number under a row lock; numbers are never reused (BR-DOC-001).

    The row with scope_key '' holds the format. When the format includes the branch or year,
    each branch/year gets its own counter row, which starts at the template's next_value.
    """
    template = await db.scalar(select(DocumentSequence).where(DocumentSequence.company_id == company_id, DocumentSequence.doc_type == doc_type, DocumentSequence.scope_key == "").with_for_update())
    if template is None:
        raise AppError(f"No numbering is configured for {doc_type}.", code="CONFIGURATION_ERROR", status_code=500)
    year = (on or datetime.now(UTC).date()).year
    parts = [p for p in ((branch_code or "") if template.include_branch else "", str(year) if template.include_year else "") if p]
    scope_key = "|".join(parts)
    counter = template
    if scope_key:
        await db.execute(
            insert(DocumentSequence)
            .values(company_id=company_id, doc_type=doc_type, scope_key=scope_key, prefix=template.prefix, next_value=template.next_value, padding=template.padding,
                    include_branch=template.include_branch, include_year=template.include_year)
            .on_conflict_do_nothing()
        )
        counter = await db.scalar(select(DocumentSequence).where(DocumentSequence.company_id == company_id, DocumentSequence.doc_type == doc_type, DocumentSequence.scope_key == scope_key).with_for_update())
        assert counter is not None
    value = counter.next_value
    counter.next_value = value + 1
    return template, parts, value
