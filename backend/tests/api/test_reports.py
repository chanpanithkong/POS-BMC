"""Reports and dashboard (Phase 7)."""

import io
from datetime import date

import httpx
import pytest
from openpyxl import load_workbook

from app.core.permissions import DEFAULT_ROLES
from app.services.reports import REPORTS
from tests.api.test_sales import Shop, approval, ik, new_sale, pay, shop  # noqa: F401  (shop is a fixture)
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db
API = "/api/v1"
TODAY = date.today().isoformat()
RANGE = {"dateFrom": TODAY, "dateTo": TODAY}


async def trade(client: httpx.AsyncClient, shop: Shop) -> dict:  # noqa: F811
    """Two sales (5 and 2 units at 2.00 + 10% VAT), one unit returned, one sale voided."""
    first = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "5"})
    await pay(client, shop, first["id"], amount_tendered="20")
    first = (await client.post(f"{API}/sales/{first['id']}/finalize", headers=ik(shop.cashier))).json()
    voided = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "2"})
    await pay(client, shop, voided["id"], amount_tendered="4.40")
    voided = (await client.post(f"{API}/sales/{voided['id']}/finalize", headers=ik(shop.cashier))).json()
    await client.post(f"{API}/sales/{voided['id']}/void", headers=ik(shop.cashier), json={"reason": "Wrong item", "approval_token": await approval(client, shop, "VOID_SALE")})
    ret = await client.post(f"{API}/sales/{first['id']}/returns", headers=ik(shop.cashier),
                            json={"lines": [{"sale_line_id": first["lines"][0]["id"], "quantity": "1", "condition": "RESALABLE", "reason": "Changed mind"}], "refund_method": "CASH"})
    assert ret.status_code == 201, ret.text
    return first


async def run(client: httpx.AsyncClient, headers: dict, report: str, **params) -> httpx.Response:
    return await client.get(f"{API}/reports/{report}", headers=headers, params={**RANGE, **params})


async def test_every_report_runs_for_the_owner(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    await trade(client, shop)
    catalogue = (await client.get(f"{API}/reports", headers=shop.owner)).json()["items"]
    assert len(catalogue) == 34
    for definition in REPORTS:
        r = await run(client, shop.owner, definition.id)
        assert r.status_code == 200, f"{definition.id}: {r.text}"
        body = r.json()
        keys = {c["key"] for c in body["columns"]}
        assert all(set(row) <= keys for row in body["rows"]), definition.id
        assert all(c["passed"] for c in body["checks"]), f"{definition.id}: {body['checks']}"


async def test_daily_sales_figures(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    await trade(client, shop)
    body = (await run(client, shop.owner, "RPT-01")).json()
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    # 5 x 2.00 sold, 1 x 2.00 returned; the voided sale is excluded.
    assert (row["gross"], row["returns"], row["netSales"], row["tax"], row["transactions"]) == (10.0, 2.0, 8.0, 0.8, 1)
    assert body["checks"][0]["passed"]  # net sales + tax = payments received - refunds


async def test_gross_profit_uses_sale_line_cost(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    await trade(client, shop)
    await client.post(f"{API}/inventory/opening-balances", headers=ik(shop.owner), json={"product_id": shop.product, "location_id": shop.shelf, "quantity": "1", "unit_cost": "9"})
    row = (await run(client, shop.owner, "RPT-13")).json()["rows"][0]
    # Cost 1.00 per unit stored at sale time: 4 net units -> COGS 4.00 even though later stock costs more.
    assert (row["netSales"], row["cogs"], row["grossProfit"], row["margin"]) == (8.0, 4.0, 4.0, 50.0)


async def test_void_and_refund_reports(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    await trade(client, shop)
    voids = (await run(client, shop.owner, "RPT-11")).json()["rows"]
    assert [(v["status"], v["amount"], v["reason"]) for v in voids] == [("VOIDED", 4.4, "Wrong item")]
    refunds = (await run(client, shop.owner, "RPT-10")).json()["rows"]
    assert [(r["method"], r["amount"]) for r in refunds] == [("CASH", 2.2)]
    tax = (await run(client, shop.owner, "RPT-12")).json()["rows"]
    assert [(t["code"], t["netSales"], t["tax"]) for t in tax] == [("VAT", 8.0, 0.8)]
    exceptions = {r["event"] for r in (await run(client, shop.owner, "RPT-34")).json()["rows"]}
    assert "SALE_VOIDED" in exceptions


async def test_cost_rules(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    await trade(client, shop)
    role = next(code for code, r in DEFAULT_ROLES.items() if "reports.sales.view" in r.permissions and "inventory.cost.view" not in r.permissions)
    user = await login(await world.user(role))
    names = {d["id"] for d in (await client.get(f"{API}/reports", headers=user)).json()["items"]}
    assert "RPT-03" in names and "RPT-13" not in names
    assert (await run(client, user, "RPT-13")).status_code == 403
    columns = {c["key"] for c in (await run(client, user, "RPT-03")).json()["columns"]}
    assert "netSales" in columns and not columns & {"cogs", "grossProfit", "margin"}


async def test_report_permission_and_branch_scope(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    assert (await run(client, shop.cashier, "RPT-01")).status_code == 403  # cashiers have no report access
    assert (await client.get(f"{API}/reports/RPT-99", headers=shop.owner)).status_code == 404
    role = next(code for code, r in DEFAULT_ROLES.items() if "reports.sales.view" in r.permissions and code not in ("OWNER",))
    scoped = await login(await world.user(role, branches=[world.branch_a]))
    assert (await run(client, scoped, "RPT-01", branchId=str(world.branch_b.id))).status_code == 404


async def test_valuation_as_of_and_stock_reconciliation(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    await trade(client, shop)
    current = (await run(client, shop.owner, "RPT-15")).json()
    assert [(r["qty"], r["value"]) for r in current["rows"]] == [(6.0, 6.0)]  # 10 - 5 + 1 returned
    yesterday = (await run(client, shop.owner, "RPT-15", asOf="2000-01-01")).json()
    assert yesterday["rows"] == []
    stock = (await run(client, shop.owner, "RPT-14")).json()
    assert stock["checks"][0]["passed"] and stock["totals"]["onHand"] == 6.0


async def test_csv_and_xlsx_exports(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    await trade(client, shop)
    csv_file = await run(client, shop.owner, "RPT-03", format="csv")
    assert csv_file.status_code == 200 and csv_file.headers["content-type"].startswith("text/csv")
    text = csv_file.content.decode("utf-8")
    assert text.startswith("﻿RPT-03 Sales by product") and "Cola" in text and "Total" in text
    xlsx = await run(client, shop.owner, "RPT-01", format="xlsx")
    sheet = load_workbook(io.BytesIO(xlsx.content)).active
    assert sheet["A1"].value == "RPT-01 Daily sales" and sheet["A3"].value == "Business date" and sheet["F4"].value == 8.0
    audit = (await client.get(f"{API}/audit-logs", headers=shop.owner, params={"action": "REPORT_EXPORTED"})).json()
    assert audit["total"] == 2
    assert (await client.post(f"{API}/exports/audit", headers=shop.owner, json={"name": "RPT-02", "format": "pdf", "rows": 3})).status_code == 204


async def test_aliases(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    for alias, report in (("sales", "RPT-01"), ("inventory", "RPT-14"), ("gross-profit", "RPT-13"), ("cashier-sessions", "RPT-30")):
        assert (await run(client, shop.owner, alias)).json()["definition"]["id"] == report


async def test_dashboard_matches_reports(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    await trade(client, shop)
    owner = (await client.get(f"{API}/dashboard", headers=shop.owner, params=RANGE)).json()
    assert owner["variant"] == "OWNER"
    kpis = {k["key"]: k["value"] for k in owner["kpis"]}
    assert (kpis["net"], kpis["gp"], kpis["margin"]) == (8.0, 4.0, 50.0)
    assert owner["top_products"][0]["sku"] == "COLA" and owner["by_payment"] == [{"name": "CASH", "amount": 11.0}]
    assert [s["label"] for s in owner["summaries"]] == ["Today", "Last 7 days", "Last 30 days"]
    manager = (await client.get(f"{API}/dashboard", headers=await login(await world.user("BRMGR", branches=[world.branch_a])), params=RANGE)).json()
    manager_kpis = {k["key"]: k["value"] for k in manager["kpis"]}
    assert manager["variant"] == "MANAGER" and manager_kpis["voids"] == 1 and manager_kpis["refunds"] == 2.0
    cashier = (await client.get(f"{API}/dashboard", headers=shop.cashier, params=RANGE)).json()
    assert cashier["variant"] == "CASHIER" and cashier["kpis"] == [] and cashier["cashier"]["sales_completed"] == 1  # the second sale was voided
    assert all("gross_profit" not in row for row in cashier["trend"])  # cashiers do not see cost-based figures


async def test_dashboard_lists_pending_approvals(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    clerk = await login(await world.user("WHSTAFF"))  # adjustment limit 0: every adjustment needs approval
    warehouse = (await client.get(f"{API}/warehouses", headers=shop.owner)).json()["items"][0]["id"]
    adj = (await client.post(f"{API}/inventory/adjustments", headers=clerk, json={"warehouse_id": warehouse, "lines": [{"product_id": shop.product, "location_id": shop.shelf, "quantity": "-2", "reason": "LOST"}]})).json()
    assert (await client.post(f"{API}/inventory/adjustments/{adj['id']}/submit", headers=ik(clerk))).json()["status"] == "SUBMITTED"
    manager = await login(await world.user("STOREMGR"))
    approvals = (await client.get(f"{API}/dashboard", headers=manager)).json()["approvals"]
    assert [(a["kind"], a["label"]) for a in approvals] == [("Adjustment", adj["adjustment_no"])]
    assert (await client.get(f"{API}/dashboard", headers=clerk)).json()["approvals"] == []  # nothing for the person who asked
