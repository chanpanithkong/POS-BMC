"""Expenses, promotions and coupons, notifications, imports and the worker (Phase 8)."""

import base64
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select, text

from app.models import OutboxEvent
from app.workers import run as worker
from tests.api.test_sales import Shop, ik, new_sale, pay, shop  # noqa: F401  (shop is a fixture)
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db
API = "/api/v1"
TODAY = date.today().isoformat()
PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 receipt").decode()


async def category(client: httpx.AsyncClient, shop: Shop) -> str:  # noqa: F811
    r = await client.post(f"{API}/expense-categories", headers=shop.owner, json={"code": "UTIL", "name": "Utilities"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def expense_body(shop: Shop, cat: str, amount: str, **extra) -> dict:  # noqa: F811
    return {"date": TODAY, "category_id": cat, "description": "Electricity", "amount": amount, "currency": "USD", "payment_method": "BANK_TRANSFER",
            "branch_id": str(shop.world.branch_a.id), **extra}


# Expenses

async def test_expense_thresholds_and_approval(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    cat = await category(client, shop)
    small = (await client.post(f"{API}/expenses", headers=shop.owner, json=expense_body(shop, cat, "20"))).json()
    assert (small["status"], small["approved_by"]) == ("APPROVED", "Auto-approved within limit")
    no_doc = await client.post(f"{API}/expenses", headers=shop.owner, json=expense_body(shop, cat, "150"))
    assert no_doc.status_code == 422 and no_doc.json()["error"]["details"][0]["field"] == "attachment"
    big = (await client.post(f"{API}/expenses", headers=shop.owner, json=expense_body(shop, cat, "150", attachment=PDF))).json()
    assert big["status"] == "SUBMITTED" and big["attachment"].startswith("/api/v1/files/expenses/")
    assert (await client.get(big["attachment"], headers=shop.owner)).content.startswith(b"%PDF")
    own = await client.post(f"{API}/expenses/{big['id']}/approve", headers=shop.owner, json={})
    assert own.json()["error"]["code"] == "SOD_VIOLATION"
    accountant = await login(await world.user("ACCT"))
    assert (await client.post(f"{API}/expenses/{big['id']}/reject", headers=accountant, json={})).status_code == 422
    approved = (await client.post(f"{API}/expenses/{big['id']}/approve", headers=accountant, json={})).json()
    assert approved["status"] == "APPROVED" and approved["approved_by"]
    perf = (await client.get(f"{API}/reports/RPT-33", headers=shop.owner, params={"dateFrom": TODAY, "dateTo": TODAY})).json()
    assert perf["rows"][0]["expenses"] == 170.0  # approved operating expenses feed the indicative result


async def test_paid_out_creates_linked_expense(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    cat = await category(client, shop)
    session = (await client.get(f"{API}/cashier-sessions/current", headers=shop.cashier)).json()
    moved = await client.post(f"{API}/cashier-sessions/{session['id']}/movements", headers=shop.cashier,
                              json={"kind": "PAID_OUT", "currency": "USD", "amount": "12", "reason": "Ice delivery", "expense_category_id": cat})
    assert moved.status_code == 201, moved.text
    expense = (await client.get(f"{API}/expenses", headers=shop.owner)).json()["items"][0]
    assert (expense["description"], expense["amount_base"], expense["status"], expense["session_id"]) == ("Ice delivery", "12.0000", "APPROVED", session["id"])
    assert moved.json()["expense_id"] == expense["id"]


# Promotions and coupons

async def make_promo(client: httpx.AsyncClient, shop: Shop, approver: dict, **body) -> dict:  # noqa: F811
    base = {"code": "P1", "name": "Cola 25% off", "type": "PRODUCT", "discount_pct": "25", "product_ids": [shop.product], "start_date": TODAY,
            "end_date": (date.today() + timedelta(days=7)).isoformat(), "priority": 1}
    promo = (await client.post(f"{API}/promotions", headers=shop.owner, json={**base, **body})).json()
    assert promo["status"] == "PENDING_APPROVAL", promo
    return (await client.post(f"{API}/promotions/{promo['id']}/approve", headers=approver)).json()


async def test_price_promotion_needs_approval_and_counts_usage(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    pending = (await client.post(f"{API}/promotions", headers=shop.owner, json={"code": "P0", "name": "Not yet", "type": "PRODUCT", "discount_pct": "50", "product_ids": [shop.product],
                                                                              "start_date": TODAY, "end_date": TODAY})).json()
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "2"})
    assert sale["lines"][0]["unit_price"] == "2.0000"  # pending promotions never apply
    assert (await client.post(f"{API}/promotions/{pending['id']}/approve", headers=shop.owner)).json()["error"]["code"] == "SOD_VIOLATION"
    await client.post(f"{API}/promotions/{pending['id']}/disable", headers=shop.owner)
    manager = await login(await world.user("STOREMGR"))
    promo = await make_promo(client, shop, manager, usage_limit=1)
    assert promo["status"] == "ACTIVE" and promo["approved_by"]
    line = (await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "set_quantity", "line_id": sale["lines"][0]["id"], "quantity": "2"}]})).json()["lines"][0]
    assert (line["unit_price"], line["price_source"], line["promotion_name"]) == ("1.5000", "PROMOTION", "Cola 25% off")
    await pay(client, shop, sale["id"], amount_tendered="5")
    assert (await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))).json()["status"] == "FINALIZED"
    promos = {p["code"]: p for p in (await client.get(f"{API}/promotions", headers=shop.owner)).json()["items"]}
    assert promos["P1"]["usage_count"] == 1
    after_limit = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})
    assert after_limit["lines"][0]["price_source"] == "STANDARD"  # limit of 1 reached


async def test_bogo_and_manual_discount_priority(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    await make_promo(client, shop, await login(await world.user("STOREMGR")), code="BOGO", name="Buy one get one", type="BOGO", discount_pct="0")
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "3"})
    line = sale["lines"][0]
    assert (line["discount_amount"], line["line_discount"]["source"], line["promotion_name"]) == ("2.0000", "PROMOTION", "Buy one get one")
    manual = (await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "line_discount", "line_id": line["id"], "discount_type": "PERCENT", "value": "5", "reason": "Loyal"}]})).json()
    assert manual["lines"][0]["line_discount"]["source"] == "MANUAL" and manual["lines"][0]["discount_amount"] == "0.3000"


async def test_coupons(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    end = (date.today() + timedelta(days=5)).isoformat()
    coupon = await client.post(f"{API}/coupons", headers=shop.owner, json={"code": "welcome2", "description": "2 off over 5", "discount_amount": "2", "min_spend": "5",
                                                                           "start_date": TODAY, "end_date": end, "usage_limit": 1})
    assert coupon.status_code == 201 and coupon.json()["code"] == "WELCOME2"
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})
    too_small = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "apply_coupon", "code": "WELCOME2"}]})
    assert too_small.status_code == 422
    bogus = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "apply_coupon", "code": "NOPE"}]})
    assert bogus.status_code == 422
    ok = (await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "set_quantity", "line_id": sale["lines"][0]["id"], "quantity": "3"},
                                                                                              {"type": "apply_coupon", "code": "welcome2"}]})).json()
    assert ok["coupon_code"] == "WELCOME2" and ok["order_discount"]["source"] == "COUPON" and ok["discount_total"] == "2.0000"
    await pay(client, shop, sale["id"], amount_tendered="10")
    assert (await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))).json()["status"] == "FINALIZED"
    assert (await client.get(f"{API}/coupons", headers=shop.owner)).json()["items"][0]["usage_count"] == 1
    second = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "3"})
    used_up = await client.patch(f"{API}/sales/{second['id']}", headers=shop.cashier, json={"ops": [{"type": "apply_coupon", "code": "WELCOME2"}]})
    assert used_up.json()["error"]["code"] == "PROMO_LIMIT_REACHED"


# Notifications

async def test_notifications_follow_permission_and_read_state(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    clerk = await login(await world.user("WHSTAFF"))
    warehouse = (await client.get(f"{API}/warehouses", headers=shop.owner)).json()["items"][0]["id"]
    adj = (await client.post(f"{API}/inventory/adjustments", headers=clerk, json={"warehouse_id": warehouse, "lines": [{"product_id": shop.product, "location_id": shop.shelf, "quantity": "-1", "reason": "LOST"}]})).json()
    await client.post(f"{API}/inventory/adjustments/{adj['id']}/submit", headers=ik(clerk))
    manager = await login(await world.user("STOREMGR"))
    items = (await client.get(f"{API}/notifications", headers=manager)).json()["items"]
    assert [(n["kind"], n["read"]) for n in items] == [("APPROVAL", False)]
    assert (await client.get(f"{API}/notifications", headers=shop.cashier)).json()["items"] == []
    await client.post(f"{API}/notifications/read", headers=manager, json={})
    assert (await client.get(f"{API}/notifications", headers=manager, params={"unread": True})).json()["items"] == []


# Imports

async def preview(client: httpx.AsyncClient, shop: Shop, kind: str, rows: list[dict]) -> dict:  # noqa: F811
    r = await client.post(f"{API}/imports/preview", headers=shop.owner, json={"type": kind, "file_name": f"{kind.lower()}.csv", "file_hash": "abc", "rows": rows})
    assert r.status_code == 200, r.text
    return r.json()


async def test_product_import_is_all_or_nothing_and_can_roll_back(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    template = (await client.get(f"{API}/imports/templates/PRODUCTS", headers=shop.owner)).json()
    assert template["columns"][0] == "sku"
    rows = [{"sku": "IMP-1", "name_en": "Imported one", "category": "DRINK", "base_unit": "PCS", "tax_code": "VAT", "status": "ACTIVE", "retail_price": "1.25", "wholesale_price": ""},
            {"sku": "IMP-2", "name_en": "Bad", "category": "NOPE", "base_unit": "PCS", "tax_code": "", "status": "ACTIVE", "retail_price": "", "wholesale_price": ""},
            {"sku": "imp-1", "name_en": "Dup", "category": "DRINK", "base_unit": "PCS", "tax_code": "", "status": "DRAFT", "retail_price": "", "wholesale_price": ""}]
    bad = await preview(client, shop, "PRODUCTS", rows)
    assert (bad["total_rows"], bad["valid_rows"]) == (3, 1)
    assert {(e["row"], e["field"]) for e in bad["errors"]} == {(3, "category"), (3, "retail_price"), (4, "sku")}
    blocked = await client.post(f"{API}/imports/commit", headers=ik(shop.owner), json={"token": bad["token"]})
    assert blocked.json()["error"]["code"] == "IMPORT_INVALID"
    good = await preview(client, shop, "PRODUCTS", rows[:1])
    batch = (await client.post(f"{API}/imports/commit", headers=ik(shop.owner), json={"token": good["token"]})).json()
    assert (batch["status"], batch["imported_rows"], batch["can_rollback"]) == ("COMMITTED", 1, True)
    product = (await client.get(f"{API}/products", headers=shop.owner, params={"q": "IMP-1"})).json()["items"][0]
    assert (product["status"], product["retail_price"], product["tax_code_id"] is not None) == ("ACTIVE", "1.2500", True)
    rolled = (await client.post(f"{API}/imports/{batch['id']}/rollback", headers=shop.owner)).json()
    assert rolled["status"] == "ROLLED_BACK" and (await client.get(f"{API}/products", headers=shop.owner, params={"q": "IMP-1"})).json()["items"] == []
    expired = await client.post(f"{API}/imports/commit", headers=ik(shop.owner), json={"token": good["token"]})
    assert expired.json()["error"]["code"] == "IMPORT_EXPIRED"


async def test_opening_stock_import_posts_movements(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    category_id = (await client.get(f"{API}/categories", headers=shop.owner)).json()["items"][0]["id"]
    product = (await client.post(f"{API}/products", headers=shop.owner, json={"sku": "WATER", "name_en": "Water", "category_id": category_id, "base_unit_id": shop.pcs, "retail_price": "1",
                                                                             "status": "ACTIVE", "conversions": [{"unit_id": shop.box, "factor": "6"}]})).json()
    rows = [{"warehouse": "WA", "location": "SHELF", "sku": "WATER", "quantity": "2", "unit": "BOX", "unit_cost": "3"}]
    pv = await preview(client, shop, "OPENING_STOCK", rows)
    assert pv["errors"] == []
    await client.post(f"{API}/imports/commit", headers=ik(shop.owner), json={"token": pv["token"]})
    detail = (await client.get(f"{API}/products/{product['id']}", headers=shop.owner)).json()
    assert (detail["on_hand"], detail["avg_cost"]) == ("12.0000", "0.500000")  # 2 boxes of 6 at 3.00 per box
    again = await preview(client, shop, "OPENING_STOCK", rows)
    assert again["errors"][0]["message"] == "Opening stock was already posted for this location."
    assert (await client.post(f"{API}/inventory/reconciliation", headers=shop.owner)).json()["differences"] == []


async def test_customer_import_and_rollback_guard(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    pv = await preview(client, shop, "CUSTOMERS", [{"code": "C-1", "name": "Dara", "phone": "012 111 222"}, {"code": "C-2", "name": "Vanna", "phone": "+855 12 111 222"}])
    assert [e["field"] for e in pv["errors"]] == ["phone"]  # same number in two formats
    pv = await preview(client, shop, "CUSTOMERS", [{"code": "C-1", "name": "Dara", "phone": "012 111 222"}])
    batch = (await client.post(f"{API}/imports/commit", headers=ik(shop.owner), json={"token": pv["token"]})).json()
    customer_id = batch["created_ids"][0]
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"}, {"type": "set_customer", "customer_id": customer_id})
    await pay(client, shop, sale["id"], amount_tendered="5")
    await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))
    assert (await client.post(f"{API}/imports/{batch['id']}/rollback", headers=shop.owner)).json()["error"]["code"] == "IN_USE"


async def test_imports_need_permission(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    assert (await client.get(f"{API}/imports", headers=shop.cashier)).status_code == 403


# Worker

async def test_worker_pass(client: httpx.AsyncClient, shop: Shop, world: World):  # noqa: F811
    users = (await client.get(f"{API}/users", headers=shop.owner)).json()["items"]
    await client.post(f"{API}/auth/forgot-password", json={"email": users[0]["email"]})
    session = (await client.get(f"{API}/cashier-sessions/current", headers=shop.cashier)).json()
    await world.db.execute(text("UPDATE cashier_sessions SET opened_at = now() - interval '13 hours' WHERE id = :id"), {"id": session["id"]})
    await world.db.commit()
    results = await worker.run_once()
    assert all(not str(v).startswith("error") for v in results.values()), results
    assert results["sessions"] >= 1
    event = await world.db.scalar(select(OutboxEvent).where(OutboxEvent.event_type == "PASSWORD_RESET_REQUESTED").order_by(OutboxEvent.id.desc()).execution_options(populate_existing=True))
    assert event.published_at is None and "SMTP" in (event.last_error or "")  # no SMTP configured: kept queued, not lost
    reminders = (await client.get(f"{API}/notifications", headers=shop.cashier)).json()["items"]
    assert any(n["kind"] == "SESSION_REMINDER" for n in reminders)
    assert (await worker.remind_open_sessions()) == 0  # one reminder per session
