"""Organisation and settings (Phase 3)."""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services.common import next_number
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db
API = "/api/v1"


async def test_company_profile(client: httpx.AsyncClient, world: World, login: LoginFn):
    owner = await login(await world.user("OWNER"))
    response = await client.patch(f"{API}/companies/current", headers=owner, json={"trading_name_km": "ហាង", "tax_id": "K001-123"})
    assert response.status_code == 200 and response.json()["tax_id"] == "K001-123"
    cashier = await login(await world.user("CASHIER"))
    assert (await client.get(f"{API}/companies/current", headers=cashier)).status_code == 200
    assert (await client.patch(f"{API}/companies/current", headers=cashier, json={"tax_id": "x"})).status_code == 403


async def test_settings_defaults_validation_and_flagging(client: httpx.AsyncClient, world: World, login: LoginFn):
    owner = await login(await world.user("OWNER"))
    current = (await client.get(f"{API}/settings", headers=owner)).json()
    assert current["costing_method"] == "WAC" and current["negative_stock_allowed"] is False and current["khr_cash_increment"] == "100"
    assert (await client.patch(f"{API}/settings", headers=owner, json={"costing_method": "FIFO"})).status_code == 422
    assert (await client.patch(f"{API}/settings", headers=owner, json={"made_up": 1})).status_code == 422
    changed = await client.patch(f"{API}/settings", headers=owner, json={"negative_stock_allowed": True, "return_window_days": 14})
    assert changed.status_code == 200 and changed.json()["return_window_days"] == 14
    log = await world.db.scalar(select(AuditLog).where(AuditLog.company_id == world.company.id, AuditLog.action == "SETTINGS_CHANGED"))
    assert log is not None and log.flagged and log.after == {"negative_stock_allowed": True, "return_window_days": 14}


async def test_branch_creates_store_warehouse_and_locations(client: httpx.AsyncClient, world: World, login: LoginFn):
    owner = await login(await world.user("OWNER"))
    response = await client.post(f"{API}/branches", headers=owner, json={"code": "PP2", "name_en": "Phnom Penh 2"})
    assert response.status_code == 201, response.text
    branch_id = response.json()["id"]
    warehouses = (await client.get(f"{API}/warehouses", headers=owner)).json()["items"]
    store = next(w for w in warehouses if w["branch_id"] == branch_id)
    assert store["code"] == "PP2-WH" and store["is_central"] is False
    assert all(w["code"] != "WH-SYS" for w in warehouses)  # the in-transit system warehouse is hidden
    locations = (await client.get(f"{API}/locations", headers=owner, params={"warehouse_id": store["id"]})).json()["items"]
    by_type = {loc["type"]: loc["available_to_sell"] for loc in locations}
    assert by_type == {"SELLABLE": True, "STORAGE": False, "RECEIVING": False, "DAMAGED": False, "RETURNS": False}
    assert (await client.post(f"{API}/branches", headers=owner, json={"code": "pp2", "name_en": "Dup"})).status_code == 409


async def test_branch_scope_filters_lookups(client: httpx.AsyncClient, world: World, login: LoginFn):
    scoped = await login(await world.user("CASHIER", branches=[world.branch_a]))
    branches = (await client.get(f"{API}/branches", headers=scoped)).json()["items"]
    assert [b["id"] for b in branches] == [str(world.branch_a.id)]
    terminals = (await client.get(f"{API}/terminals", headers=scoped)).json()["items"]
    assert {t["branch_id"] for t in terminals} == {str(world.branch_a.id)}


async def test_location_rules(client: httpx.AsyncClient, world: World, login: LoginFn):
    owner = await login(await world.user("OWNER"))
    warehouse = (await client.get(f"{API}/warehouses", headers=owner)).json()["items"][0]["id"]
    bad = await client.post(f"{API}/locations", headers=owner, json={"code": "D1", "name": "Damaged", "warehouse_id": warehouse, "type": "DAMAGED", "available_to_sell": True})
    assert bad.status_code == 422
    transit = await client.post(f"{API}/locations", headers=owner, json={"code": "T1", "name": "Transit", "warehouse_id": warehouse, "type": "IN_TRANSIT"})
    assert transit.status_code == 422
    ok = await client.post(f"{API}/locations", headers=owner, json={"code": "D1", "name": "Damaged", "warehouse_id": warehouse, "type": "DAMAGED"})
    assert ok.status_code == 201 and ok.json()["available_to_sell"] is False


async def test_terminal_needs_sellable_location_in_its_branch(client: httpx.AsyncClient, world: World, login: LoginFn):
    owner = await login(await world.user("OWNER"))
    cashier = await world.user("CASHIER", branches=[world.branch_a])
    other_branch = await client.post(f"{API}/terminals", headers=owner, json={"code": "T9", "name": "Till 9", "branch_id": str(world.branch_b.id), "default_location_id": str(world.terminal.default_location_id)})
    assert other_branch.status_code == 422
    created = await client.post(f"{API}/terminals", headers=owner, json={
        "code": "T2", "name": "Till 2", "branch_id": str(world.branch_a.id), "default_location_id": str(world.terminal.default_location_id), "assigned_cashier_ids": [str(cashier.user.id)],
    })
    assert created.status_code == 201, created.text
    assert created.json()["assigned_cashier_ids"] == [str(cashier.user.id)]


async def test_tax_code_rate_change_is_flagged(client: httpx.AsyncClient, world: World, login: LoginFn):
    owner = await login(await world.user("OWNER"))
    tax = await client.post(f"{API}/tax-codes", headers=owner, json={"code": "VAT", "name": "VAT", "rate": "10"})
    assert tax.status_code == 201 and Decimal(tax.json()["rate"]) == 10
    assert (await client.post(f"{API}/tax-codes", headers=owner, json={"code": "X", "name": "X", "rate": "101"})).status_code == 422
    await client.patch(f"{API}/tax-codes/{tax.json()['id']}", headers=owner, json={"rate": "12"})
    log = await world.db.scalar(select(AuditLog).where(AuditLog.company_id == world.company.id, AuditLog.action == "TAX_CODE_UPDATED"))
    assert log is not None and log.flagged


async def test_payment_methods_seeded(client: httpx.AsyncClient, world: World, login: LoginFn):
    headers = await login(await world.user("CASHIER"))
    methods = {m["code"]: m["requires_reference"] for m in (await client.get(f"{API}/payment-methods", headers=headers)).json()["items"]}
    assert methods == {"CASH": False, "CARD": True, "QR": True, "BANK_TRANSFER": True}


async def test_exchange_rates_append_only(client: httpx.AsyncClient, world: World, login: LoginFn):
    owner = await login(await world.user("OWNER"))
    assert (await client.post(f"{API}/currencies/rates", headers=owner, json={"rate": "0"})).status_code == 422
    first = await client.post(f"{API}/currencies/rates", headers=owner, json={"rate": "4100"})
    assert first.status_code == 201 and first.json()["from"] == "USD" and first.json()["to"] == "KHR"
    await client.post(f"{API}/currencies/rates", headers=owner, json={"rate": "4105.5"})
    rates = (await client.get(f"{API}/currencies/rates", headers=owner)).json()["items"]
    assert [r["rate"] for r in rates] == ["4105.50000000", "4100.00000000"]


async def test_sequences_only_move_forward(client: httpx.AsyncClient, world: World, login: LoginFn):
    owner = await login(await world.user("OWNER"))
    sequences = {s["id"]: s for s in (await client.get(f"{API}/document-sequences", headers=owner)).json()["items"]}
    assert sequences["RECEIPT"]["preview"] == "R-BR-YYYY-000001"
    raised = await client.patch(f"{API}/document-sequences/PO", headers=owner, json={"next_value": 50})
    assert raised.status_code == 200 and raised.json()["next_value"] == 50
    assert (await client.patch(f"{API}/document-sequences/PO", headers=owner, json={"next_value": 10})).status_code == 422


async def test_document_numbers_are_scoped_and_never_reused(world: World):
    first = await next_number(world.db, world.company.id, "RECEIPT", branch_code="A")
    second = await next_number(world.db, world.company.id, "RECEIPT", branch_code="A")
    other = await next_number(world.db, world.company.id, "RECEIPT", branch_code="B")
    await world.db.commit()
    year = first.split("-")[2]
    assert first == f"R-A-{year}-000001" and second == f"R-A-{year}-000002" and other == f"R-B-{year}-000001"
