"""POS sales, payments, cashier sessions, voids and returns (Phase 5)."""

import asyncio
import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.models import Warehouse
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db
API = "/api/v1"


def ik(headers: dict) -> dict:
    return {**headers, "Idempotency-Key": f"test-{uuid.uuid4()}"}


@dataclass
class Shop:
    owner: dict
    cashier: dict
    cashier_id: str
    manager_pin: str
    product: str
    pcs: str
    box: str
    shelf: str
    damaged: str
    world: World


@pytest.fixture
async def shop(client: httpx.AsyncClient, world: World, login: LoginFn) -> Shop:
    owner = await login(await world.user("OWNER"))

    async def post(path: str, body: dict, headers: dict = owner) -> dict:
        r = await client.post(f"{API}/{path}", headers=headers, json=body)
        assert r.status_code in (200, 201), r.text
        return r.json()

    pcs = (await post("units", {"code": "PCS", "name_en": "Piece"}))["id"]
    box = (await post("units", {"code": "BOX", "name_en": "Box"}))["id"]
    category = (await post("categories", {"code": "DRINK", "name_en": "Drinks"}))["id"]
    vat = (await post("tax-codes", {"code": "VAT", "name": "VAT", "rate": "10"}))["id"]
    product = (await post("products", {"sku": "COLA", "name_en": "Cola", "category_id": category, "base_unit_id": pcs, "tax_code_id": vat, "retail_price": "2.00", "status": "ACTIVE",
                                       "conversions": [{"unit_id": box, "factor": "6"}], "barcodes": [{"barcode": "COLA-1", "unit_id": pcs}]}))["id"]
    await post("currencies/rates", {"rate": "4100"})
    wa = await world.db.scalar(select(Warehouse).where(Warehouse.company_id == world.company.id, Warehouse.code == "WA"))
    damaged = await post("locations", {"code": "DMG", "name": "Damaged", "warehouse_id": str(wa.id), "type": "DAMAGED"})
    shelf = str(world.terminal.default_location_id)
    await client.post(f"{API}/inventory/opening-balances", headers=ik(owner), json={"product_id": product, "location_id": shelf, "quantity": "10", "unit_cost": "1.00"})
    cashier = await world.user("CASHIER", branches=[world.branch_a])
    await world.user("BRMGR", branches=[world.branch_a], pin="5813")
    headers = {**await login(cashier), "X-Terminal-Id": str(world.terminal.id)}
    opened = await client.post(f"{API}/cashier-sessions/open", headers=ik(headers), json={"opening": {"USD": "50", "KHR": "0"}})
    assert opened.status_code == 201, opened.text
    return Shop(owner, headers, str(cashier.user.id), "5813", product, pcs, box, shelf, damaged["id"], world)


async def new_sale(client: httpx.AsyncClient, shop: Shop, *ops: dict, headers: dict | None = None) -> dict:
    headers = headers or shop.cashier
    sale = (await client.post(f"{API}/sales", headers=ik(headers), json={})).json()
    if ops:
        r = await client.patch(f"{API}/sales/{sale['id']}", headers=headers, json={"ops": list(ops)})
        assert r.status_code == 200, r.text
        sale = r.json()
    return sale


async def pay(client: httpx.AsyncClient, shop: Shop, sale_id: str, headers: dict | None = None, **body) -> httpx.Response:
    return await client.post(f"{API}/sales/{sale_id}/payments", headers=ik(headers or shop.cashier), json={"method": "CASH", "currency": "USD", **body})


async def approval(client: httpx.AsyncClient, shop: Shop, action: str, amount: str = "0", headers: dict | None = None) -> str:
    r = await client.post(f"{API}/auth/approvals/verify", headers=headers or shop.cashier, json={"pin": shop.manager_pin, "action": action, "amount": amount})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def shelf_qty(client: httpx.AsyncClient, shop: Shop) -> Decimal:
    row = (await client.get(f"{API}/inventory/balances", headers=shop.owner, params={"product_id": shop.product})).json()["items"][0]
    return sum((Decimal(x["on_hand"]) for x in row["by_location"] if x["location_id"] == shop.shelf), Decimal(0))


# Pricing and totals

async def test_server_calculates_totals_and_ignores_client_amounts(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "3"}, {"type": "add_barcode", "barcode": "COLA-1"})
    assert len(sale["lines"]) == 1 and sale["lines"][0]["quantity"] == "4.0000"  # repeated scans increase the quantity
    line = sale["lines"][0]
    assert (line["gross_amount"], line["tax_rate"], line["tax_amount"], line["line_total"]) == ("8.0000", "10.0000", "0.8000", "8.8000")
    assert (sale["subtotal"], sale["tax_total"], sale["grand_total"]) == ("8.0000", "0.8000", "8.8000")
    assert line["unit_cost"] is None  # cashiers do not see cost
    injected = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "set_quantity", "line_id": line["id"], "quantity": "1", "price": "0.01"}]})
    assert injected.status_code == 422  # unknown fields such as a client price are rejected


async def test_box_unit_uses_base_price_times_factor(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "unit_id": shop.box, "quantity": "1"})
    line = sale["lines"][0]
    assert (line["unit_price"], line["quantity_base"], line["line_total"]) == ("12.0000", "6.0000", "13.2000")


async def test_discount_within_limit_and_above_limit(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "5"})
    line_id = sale["lines"][0]["id"]
    ok = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "line_discount", "line_id": line_id, "discount_type": "PERCENT", "value": "5", "reason": "Loyal"}]})
    assert ok.json()["lines"][0]["discount_amount"] == "0.5000" and ok.json()["grand_total"] == "10.4500"
    blocked = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "line_discount", "line_id": line_id, "discount_type": "PERCENT", "value": "15", "reason": "Damaged box"}]})
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "APPROVAL_REQUIRED" and blocked.json()["error"]["details"][0]["action"] == "DISCOUNT"
    token = await approval(client, shop, "DISCOUNT")  # the frontend may send 0; the approver's limit is checked against the real 15%
    approved = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "line_discount", "line_id": line_id, "discount_type": "PERCENT", "value": "15", "reason": "Damaged box", "approval_token": token}]})
    assert approved.status_code == 200 and approved.json()["lines"][0]["line_discount"]["approved_by"]
    too_far = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "line_discount", "line_id": line_id, "discount_type": "PERCENT", "value": "25", "reason": "x",
                                                                                                 "approval_token": await approval(client, shop, "DISCOUNT")}]})
    assert too_far.json()["error"]["code"] == "LIMIT_EXCEEDED"  # BRMGR limit is 20%


async def test_order_discount_is_shared_across_lines(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"}, {"type": "add_product", "product_id": shop.product, "unit_id": shop.box, "quantity": "1"},
                          {"type": "order_discount", "discount_type": "AMOUNT", "value": "0.70", "reason": "Promo"})
    shares = [Decimal(ln["order_discount_share"]) for ln in sale["lines"]]
    assert sum(shares) == Decimal("0.70") and shares == [Decimal("0.10"), Decimal("0.60")]
    assert sale["discount_total"] == "0.7000" and sale["grand_total"] == str(((Decimal("14") - Decimal("0.70")) * Decimal("1.1")).quantize(Decimal("0.0001")))


async def test_price_override_needs_approval(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "2"})
    line_id = sale["lines"][0]["id"]
    blocked = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "override_price", "line_id": line_id, "price": "1.50", "reason": "Price match"}]})
    assert blocked.json()["error"]["details"][0]["action"] == "PRICE_OVERRIDE"
    token = await approval(client, shop, "PRICE_OVERRIDE", "1")
    done = await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "override_price", "line_id": line_id, "price": "1.50", "reason": "Price match", "approval_token": token}]})
    line = done.json()["lines"][0]
    assert (line["unit_price"], line["price_source"], line["list_price"]) == ("1.5000", "OVERRIDE", "2.0000") and line["override_approved_by"]


# Payments and finalize

async def test_cash_sale_end_to_end(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "2"})  # 4.40
    paid = (await pay(client, shop, sale["id"], amount_tendered="10")).json()
    payment = paid["payments"][0]
    assert (payment["amount_applied"], payment["change_amount"], payment["status"]) == ("4.4000", "5.6000", "COMPLETED") and paid["balance"] == "0.0000"
    key = ik(shop.cashier)
    done = await client.post(f"{API}/sales/{sale['id']}/finalize", headers=key)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "FINALIZED" and body["payment_status"] == "PAID" and body["receipt_no"].startswith("R-A-")
    assert await shelf_qty(client, shop) == 8
    replay = await client.post(f"{API}/sales/{sale['id']}/finalize", headers=key)
    assert replay.json()["receipt_no"] == body["receipt_no"] and replay.headers.get("idempotent-replayed") == "true"
    again = await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))
    assert again.json()["error"]["code"] == "ALREADY_FINALIZED"
    moves = (await client.get(f"{API}/inventory/movements", headers=shop.owner, params={"source_id": sale["id"]})).json()["items"]
    assert [(m["type"], m["quantity_base"], m["unit_cost"]) for m in moves] == [("SALE", "2.0000", "1.000000")]
    receipt = (await client.get(f"{API}/sales/{sale['id']}/receipt", headers=shop.cashier)).json()
    assert receipt["copy_label"] is None and receipt["grand_total"] == "4.4000" and receipt["lines"][0]["name_en"] == "Cola"
    await client.post(f"{API}/sales/{sale['id']}/reprint", headers=shop.cashier)
    assert (await client.get(f"{API}/sales/{sale['id']}/receipt", headers=shop.cashier)).json()["copy_label"].startswith("COPY")


async def test_khr_cash_rounding_and_change(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})  # 2.20 USD = 9,020 KHR -> 9,000
    paid = (await pay(client, shop, sale["id"], currency="KHR", amount_tendered="10000")).json()
    p = paid["payments"][0]
    assert (p["amount_applied"], p["change_amount"], p["change_currency"], p["rounding_amount"]) == ("2.2000", "1000.0000", "KHR", "-0.0049")
    assert paid["grand_total_khr"] == "9000"


async def test_usd_tender_with_riel_change(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})  # 2.20
    p = (await pay(client, shop, sale["id"], amount_tendered="5", change_currency="KHR")).json()["payments"][0]
    assert (p["change_amount"], p["change_currency"]) == ("11500.0000", "KHR")  # 2.80 x 4100 = 11,480 -> 11,500


async def test_card_cannot_exceed_balance_and_needs_confirmation(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})
    over = await pay(client, shop, sale["id"], method="CARD", amount_tendered="5")
    assert over.status_code == 422
    pending = (await pay(client, shop, sale["id"], method="QR", amount_tendered="2.20")).json()
    assert pending["status"] == "PENDING_PAYMENT" and pending["payments"][0]["status"] == "PENDING" and pending["balance"] == "2.2000"
    reserved = (await client.get(f"{API}/inventory/balances", headers=shop.owner, params={"product_id": shop.product})).json()["items"][0]["reserved"]
    assert reserved == "1.0000"
    early = await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))
    assert early.json()["error"]["code"] == "PAYMENT_PENDING"
    payment_id = pending["payments"][0]["id"]
    done = (await client.post(f"{API}/sales/{sale['id']}/payments/{payment_id}/resolve", headers=shop.cashier, json={"outcome": "COMPLETED", "reference": "KHQR-778"})).json()
    assert done["status"] == "DRAFT" and done["balance"] == "0.0000"
    assert (await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))).json()["status"] == "FINALIZED"
    reserved = (await client.get(f"{API}/inventory/balances", headers=shop.owner, params={"product_id": shop.product})).json()["items"][0]["reserved"]
    assert reserved == "0.0000"
    other = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})
    dup = await pay(client, shop, other["id"], method="QR", amount_tendered="2.20", reference="KHQR-778")
    assert dup.json()["error"]["code"] == "DUPLICATE_PAYMENT_REFERENCE"


async def test_payments_and_finalize_need_an_open_session(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):
    other = {**await login(await world.user("CASHIER", branches=[world.branch_a])), "X-Terminal-Id": str(world.terminal.id)}
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"}, headers=other)
    assert (await pay(client, shop, sale["id"], headers=other, amount_tendered="5")).json()["error"]["code"] == "SESSION_REQUIRED"
    second = await client.post(f"{API}/cashier-sessions/open", headers=ik(other), json={"opening": {"USD": "0", "KHR": "0"}})
    assert second.json()["error"]["code"] == "SESSION_ALREADY_OPEN"  # one open session per terminal


async def test_price_change_before_finalize_is_caught(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})
    await pay(client, shop, sale["id"], amount_tendered="2.20")
    await client.post(f"{API}/prices", headers=shop.owner, json={"product_id": shop.product, "price": "2.50"})
    changed = await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))
    assert changed.json()["error"]["code"] == "PRICES_CHANGED"
    due = await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))
    assert due.json()["error"]["code"] == "BALANCE_DUE"
    await pay(client, shop, sale["id"], amount_tendered="0.55")
    assert (await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))).json()["grand_total"] == "2.7500"


async def test_last_unit_cannot_be_sold_twice(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):
    category = (await client.get(f"{API}/categories", headers=shop.owner)).json()["items"][0]["id"]
    last = (await client.post(f"{API}/products", headers=shop.owner, json={"sku": "LAST", "name_en": "Last one", "category_id": category, "base_unit_id": shop.pcs, "retail_price": "3", "status": "ACTIVE"})).json()["id"]
    await client.post(f"{API}/inventory/opening-balances", headers=ik(shop.owner), json={"product_id": last, "location_id": shop.shelf, "quantity": "1", "unit_cost": "1"})
    t2 = await client.post(f"{API}/terminals", headers=shop.owner, json={"code": "T2", "name": "Till 2", "branch_id": str(world.branch_a.id), "default_location_id": shop.shelf})
    other = {**await login(await world.user("CASHIER", branches=[world.branch_a])), "X-Terminal-Id": t2.json()["id"]}
    await client.post(f"{API}/cashier-sessions/open", headers=ik(other), json={"opening": {"USD": "0", "KHR": "0"}})
    cashiers = (shop.cashier, other)
    sales = [await new_sale(client, shop, {"type": "add_product", "product_id": last, "quantity": "1"}, headers=h) for h in cashiers]
    for sale, h in zip(sales, cashiers, strict=True):
        await pay(client, shop, sale["id"], headers=h, amount_tendered="3")
    results = await asyncio.gather(*[client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(h)) for sale, h in zip(sales, cashiers, strict=True)])
    outcomes = sorted(r.json().get("status") or r.json()["error"]["code"] for r in results)
    assert outcomes == ["FINALIZED", "INSUFFICIENT_STOCK"]
    loser = next(sale for sale, r in zip(sales, results, strict=True) if r.status_code != 200)
    assert (await client.get(f"{API}/sales/{loser['id']}", headers=shop.owner)).json()["receipt_no"] is None  # no number consumed by the rolled-back finalize
    assert (await client.post(f"{API}/inventory/reconciliation", headers=shop.owner)).json()["differences"] == []


# Hold, cancel, void

async def test_hold_and_resume_reprices(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"}, {"type": "hold", "label": "Table 4"})
    assert sale["status"] == "HELD" and sale["hold_label"] == "Table 4"
    assert [h["id"] for h in (await client.get(f"{API}/sales/held", headers=shop.cashier)).json()["items"]] == [sale["id"]]
    await client.post(f"{API}/prices", headers=shop.owner, json={"product_id": shop.product, "price": "2.10"})
    resumed = (await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "resume"}]})).json()
    assert resumed["status"] == "DRAFT" and resumed["lines"][0]["unit_price"] == "2.1000" and resumed["notices"]


async def test_cancel_with_items_needs_approval(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})
    blocked = await client.post(f"{API}/sales/{sale['id']}/cancel", headers=ik(shop.cashier), json={"reason": "Customer left"})
    assert blocked.json()["error"]["details"][0]["action"] == "CANCEL_SALE"
    token = await approval(client, shop, "CANCEL_SALE")
    done = await client.post(f"{API}/sales/{sale['id']}/cancel", headers=ik(shop.cashier), json={"reason": "Customer left", "approval_token": token})
    assert done.json()["status"] == "CANCELLED" and done.json()["receipt_no"] is None


async def test_void_restores_stock_and_refunds_cash(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "3"})  # 6.60
    await pay(client, shop, sale["id"], amount_tendered="10")
    await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))
    assert await shelf_qty(client, shop) == 7
    no_approval = await client.post(f"{API}/sales/{sale['id']}/void", headers=ik(shop.cashier), json={"reason": "Wrong item"})
    assert no_approval.json()["error"]["code"] == "APPROVAL_REQUIRED"
    voided = (await client.post(f"{API}/sales/{sale['id']}/void", headers=ik(shop.cashier), json={"reason": "Wrong item", "approval_token": await approval(client, shop, "VOID_SALE")})).json()
    assert voided["status"] == "VOIDED" and voided["payment_status"] == "REFUNDED" and voided["voided_by"]
    assert await shelf_qty(client, shop) == 10
    session = (await client.get(f"{API}/cashier-sessions/current", headers=shop.cashier)).json()
    summary = (await client.get(f"{API}/cashier-sessions/{session['id']}/summary", headers=shop.owner)).json()
    assert summary["session"]["expected"]["USD"] == "50.0000"  # 50 float + 10 tendered - 3.40 change - 6.60 refund


# Returns

async def _finalized(client: httpx.AsyncClient, shop: Shop, qty: str, *extra: dict) -> dict:
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": qty}, *extra)
    await pay(client, shop, sale["id"], amount_tendered=str(Decimal(sale["grand_total"]) + 10))
    done = await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))
    assert done.status_code == 200, done.text
    return done.json()


async def test_partial_return_refunds_from_snapshots(client: httpx.AsyncClient, shop: Shop):
    sale = await _finalized(client, shop, "4", {"type": "order_discount", "discount_type": "AMOUNT", "value": "0.40", "reason": "Promo"})  # (8.00-0.40)*1.1 = 8.36
    line = sale["lines"][0]
    body = {"lines": [{"sale_line_id": line["id"], "quantity": "1", "condition": "RESALABLE", "reason": "Not needed"}], "refund_method": "CASH"}
    quote = (await client.post(f"{API}/sales/{sale['id']}/returns/quote", headers=shop.cashier, json=body)).json()
    assert (quote["refund_total"], quote["tax_total"], quote["approval_reasons"]) == ("2.0900", "0.1900", [])
    ret = await client.post(f"{API}/sales/{sale['id']}/returns", headers=ik(shop.cashier), json=body)
    assert ret.status_code == 201, ret.text
    assert ret.json()["refund_status"] == "COMPLETED" and ret.json()["return_no"].startswith("RET-A-")
    assert await shelf_qty(client, shop) == 7  # 10 - 4 + 1 resalable
    too_many = await client.post(f"{API}/sales/{sale['id']}/returns", headers=ik(shop.cashier), json={**body, "lines": [{**body["lines"][0], "quantity": "4"}]})
    assert too_many.status_code == 422
    updated = (await client.get(f"{API}/sales/{sale['id']}", headers=shop.owner)).json()
    assert updated["lines"][0]["returned_quantity"] == "1.0000" and updated["payment_status"] == "PARTIALLY_REFUNDED"


async def test_damaged_return_goes_to_damaged_location_and_large_refund_needs_approval(client: httpx.AsyncClient, shop: Shop):
    sale = await _finalized(client, shop, "10")  # 22.00, above the cashier's 20 refund limit
    body = {"lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "10", "condition": "DAMAGED", "reason": "Crushed"}], "refund_method": "CASH"}
    blocked = await client.post(f"{API}/sales/{sale['id']}/returns", headers=ik(shop.cashier), json=body)
    assert blocked.json()["error"]["details"][0]["action"] == "REFUND"
    done = await client.post(f"{API}/sales/{sale['id']}/returns", headers=ik(shop.cashier), json={**body, "approval_token": await approval(client, shop, "REFUND", "22")})
    assert done.status_code == 201 and done.json()["approved_by"] and done.json()["lines"][0]["destination_location_id"] == shop.damaged
    assert await shelf_qty(client, shop) == 0  # damaged stock is not sellable
    assert (await client.post(f"{API}/inventory/reconciliation", headers=shop.owner)).json()["differences"] == []


async def test_exchange_creates_linked_finalized_sale(client: httpx.AsyncClient, shop: Shop):
    sale = await _finalized(client, shop, "1")  # 2.20
    body = {"lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1", "condition": "RESALABLE", "reason": "Wants a box"}], "refund_method": "CASH",
            "replacement_lines": [{"product_id": shop.product, "unit_id": shop.box, "quantity": "1"}], "settlement_method": "CASH"}
    ret = await client.post(f"{API}/sales/{sale['id']}/returns", headers=ik(shop.cashier), json=body)
    assert ret.status_code == 201, ret.text
    exchange = (await client.get(f"{API}/sales/{ret.json()['exchange_sale_id']}", headers=shop.owner)).json()
    assert exchange["status"] == "FINALIZED" and exchange["grand_total"] == "13.2000"
    assert ret.json()["difference_paid"] == "11.0000" and ret.json()["type"] == "EXCHANGE"
    assert {p["method"] for p in exchange["payments"]} == {"EXCHANGE_CREDIT", "CASH"}


async def test_electronic_refund_waits_for_reference(client: httpx.AsyncClient, shop: Shop):
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})
    await pay(client, shop, sale["id"], method="CARD", amount_tendered="2.20", approval_code="A1B2C3", card_last4="4242")
    sale = (await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))).json()
    ret = (await client.post(f"{API}/sales/{sale['id']}/returns", headers=ik(shop.cashier),
                             json={"lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1", "condition": "RESALABLE", "reason": "x"}], "refund_method": "CARD"})).json()
    assert ret["refund_status"] == "PENDING"
    confirmed = (await client.post(f"{API}/returns/{ret['id']}/confirm-refund", headers=shop.cashier, json={"reference": "RF-991"})).json()
    assert confirmed["refund_status"] == "COMPLETED"
    assert (await client.get(f"{API}/sales/{sale['id']}", headers=shop.owner)).json()["payment_status"] == "REFUNDED"


# Cashier sessions

async def test_session_close_blind_count_and_variance_approval(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):
    await _finalized(client, shop, "5")  # 11.00 cash
    session = (await client.get(f"{API}/cashier-sessions/current", headers=shop.cashier)).json()
    assert session["expected"] is None  # blind
    await client.post(f"{API}/cashier-sessions/{session['id']}/movements", headers=shop.cashier, json={"kind": "CASH_IN", "currency": "USD", "amount": "20", "reason": "Float top-up"})
    await client.post(f"{API}/cashier-sessions/{session['id']}/movements", headers=shop.cashier, json={"kind": "DROP", "currency": "USD", "amount": "30", "reason": "Safe drop"})
    big = await client.post(f"{API}/cashier-sessions/{session['id']}/movements", headers=shop.cashier, json={"kind": "PAID_OUT", "currency": "USD", "amount": "60", "reason": "Supplier"})
    assert big.json()["error"]["details"][0]["action"] == "CASH_MOVEMENT"
    # Expected: 50 + 11 + 20 - 30 = 51. Counting 45 is short by 6, beyond the 1.00 tolerance.
    closed = (await client.post(f"{API}/cashier-sessions/{session['id']}/close", headers=ik(shop.cashier), json={"counted": {"USD": "45", "KHR": "0"}})).json()
    assert closed["status"] == "CLOSING" and closed["needs_approval"] and closed["expected"]["USD"] == "51.0000" and closed["variance"]["USD"] == "-6.0000"
    own = await client.post(f"{API}/cashier-sessions/{session['id']}/approve", headers=shop.cashier, json={"reason": "mine"})
    assert own.status_code == 403
    manager = await login(await world.user("STOREMGR", branches=[world.branch_a]))
    approved = (await client.post(f"{API}/cashier-sessions/{session['id']}/approve", headers=manager, json={"reason": "Counted twice; short confirmed"})).json()
    assert approved["status"] == "CLOSED" and approved["reviewed_by"]


async def test_close_within_tolerance_closes_directly(client: httpx.AsyncClient, shop: Shop):
    session = (await client.get(f"{API}/cashier-sessions/current", headers=shop.cashier)).json()
    closed = (await client.post(f"{API}/cashier-sessions/{session['id']}/close", headers=ik(shop.cashier), json={"counted": {"USD": "49.50", "KHR": "0"}})).json()
    assert closed["status"] == "CLOSED" and closed["needs_approval"] is False
    sale = (await client.post(f"{API}/sales", headers=ik(shop.cashier), json={})).json()
    await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "add_product", "product_id": shop.product}]})
    assert (await pay(client, shop, sale["id"], amount_tendered="5")).json()["error"]["code"] == "SESSION_REQUIRED"


async def test_sales_visibility(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):
    sale = await _finalized(client, shop, "1")
    other = {**await login(await world.user("CASHIER", branches=[world.branch_a])), "X-Terminal-Id": str(world.terminal.id)}
    assert (await client.get(f"{API}/sales", headers=other)).json()["items"] == []
    found = (await client.get(f"{API}/sales", headers=other, params={"q": sale["receipt_no"]})).json()["items"]
    assert [x["id"] for x in found] == [sale["id"]]  # exact receipt lookup for returns
    assert len((await client.get(f"{API}/sales", headers=shop.owner)).json()["items"]) == 1


