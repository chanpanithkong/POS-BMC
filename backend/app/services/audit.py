"""Append-only audit log with a per-company hash chain (BR-AUD-001, NFR-SEC-011).

Entries are written in the same transaction as the change they describe. A
transaction-level advisory lock serialises writers per company so the chain
has no forks; the lock is released at commit or rollback.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import correlation_id
from app.models import AuditLog

GENESIS = "0" * 64


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(fields)).encode()).hexdigest()


async def record(
    session: AsyncSession,
    *,
    action: str,
    module: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    company_id: uuid.UUID | None,
    user_id: uuid.UUID | None = None,
    user_name: str = "System",
    branch_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    flagged: bool = False,
    ip_address: str | None = None,
) -> AuditLog:
    lock_key = str(company_id or "global")
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"audit:{lock_key}"})
    prev = await session.scalar(
        select(AuditLog.hash).where(AuditLog.company_id.is_(None) if company_id is None else AuditLog.company_id == company_id).order_by(AuditLog.id.desc()).limit(1)
    )
    occurred_at = await session.scalar(select(func.now())) or datetime.now(UTC)
    fields = {
        "company_id": str(company_id) if company_id else None,
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "user_id": str(user_id) if user_id else None,
        "action": action,
        "module": module,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "before": before,
        "after": after,
        "flagged": flagged,
    }
    prev_hash = prev or GENESIS
    entry = AuditLog(
        company_id=company_id, occurred_at=occurred_at, user_id=user_id, user_name=user_name, action=action, module=module,
        entity_type=entity_type, entity_id=str(entity_id), branch_id=branch_id, before=before, after=after, flagged=flagged,
        ip_address=ip_address, correlation_id=correlation_id.get(), prev_hash=prev_hash, hash=compute_hash(prev_hash, fields),
    )
    session.add(entry)
    await session.flush()
    return entry


async def verify_chain(session: AsyncSession, company_id: uuid.UUID) -> tuple[bool, int | None]:
    """Recomputes the chain. Returns (intact, first broken entry id)."""
    prev_hash = GENESIS
    rows = await session.scalars(select(AuditLog).where(AuditLog.company_id == company_id).order_by(AuditLog.id))
    for entry in rows:
        fields = {
            "company_id": str(entry.company_id) if entry.company_id else None,
            "occurred_at": entry.occurred_at.astimezone(UTC).isoformat(),
            "user_id": str(entry.user_id) if entry.user_id else None,
            "action": entry.action,
            "module": entry.module,
            "entity_type": entry.entity_type,
            "entity_id": entry.entity_id,
            "before": entry.before,
            "after": entry.after,
            "flagged": entry.flagged,
        }
        if entry.prev_hash != prev_hash or entry.hash != compute_hash(prev_hash, fields):
            return False, entry.id
        prev_hash = entry.hash
    return True, None
