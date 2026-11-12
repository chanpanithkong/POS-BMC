"""Permissions (403), company scope (404), self-permission guard, separation of duties and approvals."""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, Role
from app.services import approvals
from app.services.bootstrap import create_company
from app.services.principal import load_principal
from tests.conftest import LoginFn, World, new_password

pytestmark = pytest.mark.db


async def test_missing_permission_is_403(client: httpx.AsyncClient, world: World, login: LoginFn):
    cashier = await world.user("CASHIER", branches=[world.branch_a])
    headers = await login(cashier)
    response = await client.get("/api/v1/users", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert (await client.get("/api/v1/audit-logs", headers=headers)).status_code == 403


async def test_other_company_records_are_404(client: httpx.AsyncClient, world: World, login: LoginFn, db):
    headers = await login(await world.user("SYSADMIN"))
    other = await create_company(db, legal_name="Other Co", trading_name="Other")
    await db.commit()
    roles = {r.code: r for r in await db.scalars(select(Role).where(Role.company_id == other.id))}
    stranger = await World(other, world.branch_a, world.branch_b, roles, world.terminal, db).user("READONLY")
    response = await client.get(f"/api/v1/users/{stranger.user.id}", headers=headers)
    assert response.status_code == 404
    listing = await client.get("/api/v1/users", headers=headers)
    assert str(stranger.user.id) not in {u["id"] for u in listing.json()["items"]}


async def test_admin_creates_user_with_scope(client: httpx.AsyncClient, world: World, login: LoginFn):
    headers = await login(await world.user("SYSADMIN"))
    body = {
        "username": "new.cashier." + world.company.id.hex[:6], "email": f"nc{world.company.id.hex[:6]}@example.test", "full_name": "New Cashier",
        "password": new_password(), "role_ids": [str(world.roles["CASHIER"].id)], "branch_ids": [str(world.branch_a.id)],
    }
    created = await client.post("/api/v1/users", headers=headers, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["branch_ids"] == [str(world.branch_a.id)]
    assert "password" not in created.json() and "password_hash" not in created.json()
    duplicate = await client.post("/api/v1/users", headers=headers, json=body)
    assert duplicate.status_code == 409


async def test_cannot_change_own_permissions(client: httpx.AsyncClient, world: World, login: LoginFn):
    admin = await world.user("SYSADMIN")
    headers = await login(admin)
    response = await client.patch(f"/api/v1/users/{admin.user.id}", headers=headers, json={"role_ids": [str(world.roles["OWNER"].id)]})
    assert response.status_code == 403
    event = await world.db.scalar(select(AuditLog).where(AuditLog.action == "SELF_PERMISSION_ATTEMPT", AuditLog.entity_id == str(admin.user.id)))
    assert event is not None and event.flagged


async def test_role_with_sod_conflict_is_flagged(client: httpx.AsyncClient, world: World, login: LoginFn):
    headers = await login(await world.user("SYSADMIN"))
    response = await client.post("/api/v1/roles", headers=headers, json={"code": "PO_ALL", "name": "PO all", "permissions": ["purchasing.order.create", "purchasing.order.approve"]})
    assert response.status_code == 201
    assert response.json()["sod_conflicts"] == ["create PO and approve PO"]
    unknown = await client.post("/api/v1/roles", headers=headers, json={"code": "BAD", "name": "Bad", "permissions": ["nope.nope.nope"]})
    assert unknown.status_code == 422


async def test_supervisor_pin_approval(client: httpx.AsyncClient, world: World, login: LoginFn):
    cashier = await world.user("CASHIER", branches=[world.branch_a])
    manager = await world.user("BRMGR", branches=[world.branch_a], pin="5839")
    headers = await login(cashier)
    granted = await client.post("/api/v1/auth/approvals/verify", headers=headers, json={"pin": "5839", "action": "DISCOUNT", "amount": "15"})
    assert granted.status_code == 200
    assert granted.json()["approver_id"] == str(manager.user.id)
    over_limit = await client.post("/api/v1/auth/approvals/verify", headers=headers, json={"pin": "5839", "action": "DISCOUNT", "amount": "25"})
    assert over_limit.status_code == 403 and over_limit.json()["error"]["code"] == "LIMIT_EXCEEDED"
    wrong_pin = await client.post("/api/v1/auth/approvals/verify", headers=headers, json={"pin": "5830", "action": "DISCOUNT", "amount": "1"})
    assert wrong_pin.status_code == 401


async def test_approver_needs_the_permission(client: httpx.AsyncClient, world: World, login: LoginFn):
    cashier = await world.user("CASHIER", branches=[world.branch_a])
    await world.user("CASHIER", branches=[world.branch_a], pin="6150")
    response = await client.post("/api/v1/auth/approvals/verify", headers=await login(cashier), json={"pin": "6150", "action": "VOID_SALE"})
    assert response.status_code == 403


async def test_self_approval_is_blocked_by_default(client: httpx.AsyncClient, world: World, login: LoginFn):
    manager = await world.user("BRMGR", branches=[world.branch_a], pin="7046")
    response = await client.post("/api/v1/auth/approvals/verify", headers=await login(manager), json={"pin": "7046", "action": "DISCOUNT", "amount": "10"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SOD_VIOLATION"


async def test_approval_token_is_single_use_and_bound(world: World, db):
    cashier = await world.user("CASHIER", branches=[world.branch_a])
    other = await world.user("CASHIER", branches=[world.branch_a])
    await world.user("BRMGR", branches=[world.branch_a], pin="3917")
    principal = await load_principal(db, cashier.user.id, cashier.user.id)
    grant = await approvals.verify_pin(db, principal, pin="3917", action="DISCOUNT", amount=Decimal("10"))

    other_principal = await load_principal(db, other.user.id, other.user.id)
    with pytest.raises(approvals.SodViolation):
        await approvals.consume(db, other_principal, token=grant["token"], action="DISCOUNT", amount=Decimal("10"), message="m")
    await db.rollback()
    with pytest.raises(approvals.ApprovalRequired):
        await approvals.consume(db, principal, token=grant["token"], action="DISCOUNT", amount=Decimal("11"), message="m")
    await db.rollback()
    await approvals.consume(db, principal, token=grant["token"], action="DISCOUNT", amount=Decimal("10"), message="m")
    await db.commit()
    with pytest.raises(approvals.ApprovalRequired):
        await approvals.consume(db, principal, token=grant["token"], action="DISCOUNT", amount=Decimal("10"), message="m")
    with pytest.raises(approvals.ApprovalRequired):
        await approvals.consume(db, principal, token=None, action="DISCOUNT", message="Manager approval needed")
