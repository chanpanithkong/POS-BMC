"""Database-level guarantees: migrations, append-only audit log, hash chain."""

import httpx
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog
from app.services import audit
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db


async def test_schema_matches_models(migrated: str):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.db.base import Base

    engine = create_engine(migrated)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
        tables = set(inspect(conn).get_table_names())
    engine.dispose()
    assert diff == []
    assert {"users", "roles", "audit_logs", "user_sessions", "idempotency_keys", "outbox_events"} <= tables


@pytest.mark.parametrize("statement", ["UPDATE audit_logs SET action = 'X'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"])
async def test_audit_log_is_append_only(world: World, statement: str):
    await audit.record(world.db, action="TEST", module="TEST", entity_type="t", entity_id="1", company_id=world.company.id)
    await world.db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        await world.db.execute(text(statement))
    await world.db.rollback()


async def test_audit_chain_verifies(client: httpx.AsyncClient, world: World, login: LoginFn):
    auditor = await world.user("AUDITOR")
    headers = await login(auditor)
    for i in range(3):
        await audit.record(world.db, action="TEST", module="TEST", entity_type="t", entity_id=str(i), company_id=world.company.id, after={"n": i})
    await world.db.commit()
    result = await client.get("/api/v1/audit-logs/verify", headers=headers)
    assert result.json() == {"intact": True, "first_broken_id": None}
    page = await client.get("/api/v1/audit-logs", headers=headers, params={"module": "TEST"})
    assert page.json()["total"] == 3


async def test_audit_chain_detects_tampering(world: World):
    for i in range(3):
        await audit.record(world.db, action="TEST", module="TEST", entity_type="t", entity_id=str(i), company_id=world.company.id)
    await world.db.commit()
    entries = list(await world.db.scalars(select(AuditLog.id).where(AuditLog.company_id == world.company.id).order_by(AuditLog.id)))
    middle = entries[1]
    # Simulate tampering by a superuser who disabled the trigger.
    await world.db.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_logs_append_only"))
    await world.db.execute(text("UPDATE audit_logs SET entity_id = 'forged' WHERE id = :id"), {"id": middle})
    await world.db.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_logs_append_only"))
    await world.db.commit()
    assert await audit.verify_chain(world.db, world.company.id) == (False, middle)
