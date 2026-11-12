"""Suppliers, purchase orders, goods receipts, supplier invoices and purchase returns (Phase 6)."""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.models import Warehouse, WarehouseLocation
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db
API = "/api/v1"


def ik(headers: dict) -> dict:
    return {**headers, "Idempotency-Key": f"test-{uuid.uuid4()}"}


@dataclass
class Buy:
    owner: dict
    buyer: dict
    approver: dict
    clerk: dict
    receiver: dict
    product: str
    pcs: str
    case: str
    supplier: str
    warehouse: str
    shelf: str
    damaged: str
    world: World


@pytest.fixture
async def buy(client: httpx.AsyncClient, world: World, login: LoginFn) -> Buy:
    owner = await login(await world.user("OWNER"))

    async def post(path: str, body: dict) -> dict:
        r = await client.post(f"{API}/{path}", headers=owner, json=body)
        assert r.status_code in (200, 201), r.text
        return r.json()

    pcs = (await post("units", {"code": "PCS", "name_en": "Piece"}))["id"]
    case = (await post("units", {"code": "CASE", "name_en": "Case"}))["id"]
    category = (await post("categories", {"code": "GEN", "name_en": "General"}))["id"]
    product = (await post("products", {"sku": "OIL", "name_en": "Cooking oil", "category_id": category, "base_unit_id": pcs, "retail_price": "3", "status": "ACTIVE",
                                       "conversions": [{"unit_id": case, "factor": "12", "is_purchase_default": True}]}))["id"]
    supplier = (await post("suppliers", {"code": "SUP1", "name_en": "Mekong Foods", "lead_time_days": 5, "contacts": [{"name": "Dara", "phone": "012345678"}]}))["id"]
    wa = await world.db.scalar(select(Warehouse).where(Warehouse.company_id == world.company.id, Warehouse.code == "WA"))
    shelf = await world.db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == wa.id, WarehouseLocation.code == "SHELF"))
    damaged = (await post("locations", {"code": "DMG", "name": "Damaged", "warehouse_id": str(wa.id), "type": "DAMAGED"}))["id"]
    await client.post(f"{API}/inventory/opening-balances", headers=ik(owner), json={"product_id": product, "location_id": str(shelf.id), "quantity": "10", "unit_cost": "2"})
    return Buy(owner, await login(await world.user("PUROFF")), await login(await world.user("STOREMGR")), await login(await world.user("WHSTAFF")),
               await login(await world.user("INVMGR")), product, pcs, case, supplier, str(wa.id), str(shelf.id), damaged, world)


async def make_po(client: httpx.AsyncClient, b: Buy, qty: str = "2", cost: str = "12", headers: dict | None = None) -> dict:
    r = await client.post(f"{API}/purchase-orders", headers=headers or b.buyer, json={
        "supplier_id": b.supplier, "warehouse_id": b.warehouse, "expected_date": (date.today() + timedelta(days=5)).isoformat(), "notes": "",
        "lines": [{"product_id": b.product, "unit_id": b.case, "quantity": qty, "unit_cost": cost}]})
    assert r.status_code == 201, r.text
    return r.json()


async def act(client: httpx.AsyncClient, path: str, doc_id: str, verb: str, headers: dict, body: dict | None = None) -> httpx.Response:
    return await client.post(f"{API}/{path}/{doc_id}/{verb}", headers=ik(headers), json=body or {})


async def approved_po(client: httpx.AsyncClient, b: Buy, **kw) -> dict:
    po = await make_po(client, b, **kw)
    await act(client, "purchase-orders", po["id"], "submit", b.buyer)
    r = await act(client, "purchase-orders", po["id"], "approve", b.approver)
    assert r.json()["status"] == "APPROVED", r.text
    return (await act(client, "purchase-orders", po["id"], "send", b.buyer)).json()


async def stock(client: httpx.AsyncClient, b: Buy) -> dict:
    return (await client.get(f"{API}/inventory/balances", headers=b.owner, params={"product_id": b.product})).json()["items"][0]


async def receive(client: httpx.AsyncClient, b: Buy, po: dict, headers: dict | None = None, **line) -> dict:
    pl = po["lines"][0]
    r = await client.post(f"{API}/goods-receipts", headers=headers or b.clerk, json={
        "po_id": po["id"], "supplier_id": "", "warehouse_id": "", "delivery_note": "DN-1", "invoice_ref": "", "exception_reason": "", "blind": False,
        "lines": [{"po_line_id": pl["id"], "product_id": b.product, "unit_id": b.case, "quantity_received": "2", "quantity_damaged": "0", "quantity_rejected": "0", "unit_cost": "12",
                   "batch_no": "", "expiry_date": "", "name": "Cooking oil", "unit_code": "CASE", "factor": 12, "open": 2, "track_expiry": False, **line}]})
    assert r.status_code == 201, r.text
    return r.json()


# Purchase orders

async def test_po_approval_flow_and_on_order(client: httpx.AsyncClient, buy: Buy):
    po = await make_po(client, buy)
    assert (po["status"], po["total"], po["lines"][0]["quantity_base"]) == ("DRAFT", "24.0000", "24.0000")
    await act(client, "purchase-orders", po["id"], "submit", buy.buyer)
    assert (await act(client, "purchase-orders", po["id"], "approve", buy.buyer)).status_code == 403  # buyers cannot approve
    assert (await act(client, "purchase-orders", po["id"], "approve", buy.approver)).json()["status"] == "APPROVED"
    edited = await client.patch(f"{API}/purchase-orders/{po['id']}", headers=buy.buyer, json={"lines": [{"product_id": buy.product, "unit_id": buy.case, "quantity": "3", "unit_cost": "12"}]})
    assert edited.json()["status"] == "PENDING_APPROVAL" and edited.json()["approved_by"] is None  # BR-PUR-001
    await act(client, "purchase-orders", po["id"], "approve", buy.approver)
    sent = (await act(client, "purchase-orders", po["id"], "send", buy.buyer)).json()
    assert sent["status"] == "SENT" and sent["sent_at"]
    row = await stock(client, buy)
    assert (row["on_hand"], row["on_order"]) == ("10.0000", "36.0000")  # ordering is not receiving (BR-PUR-002)


async def test_creator_cannot_approve_and_limits_apply(client: httpx.AsyncClient, buy: Buy):
    own = await make_po(client, buy, headers=buy.approver)
    await act(client, "purchase-orders", own["id"], "submit", buy.approver)
    assert (await act(client, "purchase-orders", own["id"], "approve", buy.approver)).json()["error"]["code"] == "SOD_VIOLATION"
    big = await make_po(client, buy, qty="500", cost="12")  # 6,000 > STOREMGR limit 5,000
    await act(client, "purchase-orders", big["id"], "submit", buy.buyer)
    assert (await act(client, "purchase-orders", big["id"], "approve", buy.approver)).json()["error"]["code"] == "LIMIT_EXCEEDED"
    assert (await act(client, "purchase-orders", big["id"], "approve", buy.owner)).json()["status"] == "APPROVED"


async def test_draft_po_delete_and_cancel(client: httpx.AsyncClient, buy: Buy):
    draft = await make_po(client, buy)
    assert (await client.delete(f"{API}/purchase-orders/{draft['id']}", headers=buy.buyer)).status_code == 204
    po = await approved_po(client, buy)
    assert (await client.delete(f"{API}/purchase-orders/{po['id']}", headers=buy.buyer)).status_code == 409
    assert (await act(client, "purchase-orders", po["id"], "cancel", buy.buyer, {"reason": "Supplier out of stock"})).json()["status"] == "CANCELLED"


# Goods receipts

async def test_receipt_posts_once_and_updates_cost(client: httpx.AsyncClient, buy: Buy):
    po = await approved_po(client, buy)
    grn = await receive(client, buy, po)
    assert grn["status"] == "DRAFT" and grn["discrepancies"] == []
    key = ik(buy.clerk)
    posted = await client.post(f"{API}/goods-receipts/{grn['id']}/post", headers=key, json={})
    assert posted.json()["status"] == "POSTED", posted.text
    replay = await client.post(f"{API}/goods-receipts/{grn['id']}/post", headers=key, json={})
    assert replay.headers.get("idempotent-replayed") == "true"
    again = await act(client, "goods-receipts", grn["id"], "post", buy.clerk)
    assert again.json()["error"]["code"] == "ALREADY_POSTED"  # BR-GRN-001
    row = await stock(client, buy)
    assert (row["on_hand"], row["on_order"]) == ("34.0000", "0")
    product = (await client.get(f"{API}/products/{buy.product}", headers=buy.owner)).json()
    assert product["avg_cost"] == "1.294118" and product["last_purchase_cost"] == "1.0000"  # (10 x 2 + 24 x 1) / 34
    assert (await client.get(f"{API}/purchase-orders/{po['id']}", headers=buy.buyer)).json()["status"] == "RECEIVED"


async def test_over_delivery_needs_approval_and_damage_is_kept_apart(client: httpx.AsyncClient, buy: Buy):
    po = await approved_po(client, buy)
    grn = await receive(client, buy, po, quantity_received="2", quantity_damaged="1", quantity_rejected="1")  # 36 base against 24 open
    assert any("tolerance" in d for d in grn["discrepancies"]) and grn["flagged_for_review"]
    pending = (await act(client, "goods-receipts", grn["id"], "post", buy.clerk)).json()
    assert pending["status"] == "PENDING_APPROVAL"
    assert (await act(client, "goods-receipts", grn["id"], "approve", buy.clerk)).status_code == 403
    posted = (await act(client, "goods-receipts", grn["id"], "approve", buy.approver)).json()
    assert posted["status"] == "POSTED" and posted["approved_by"]
    row = await stock(client, buy)
    by_loc = {x["location_id"]: x["on_hand"] for x in row["by_location"]}
    assert by_loc[buy.shelf] == "34.0000" and by_loc[buy.damaged] == "12.0000"  # the rejected case never enters stock


async def test_receipt_without_po_needs_exception_permission(client: httpx.AsyncClient, buy: Buy):
    body = {"po_id": "", "supplier_id": buy.supplier, "warehouse_id": buy.warehouse, "exception_reason": "Urgent delivery, PO to follow",
            "lines": [{"product_id": buy.product, "unit_id": buy.pcs, "quantity_received": "5", "unit_cost": "1.10"}]}
    assert (await client.post(f"{API}/goods-receipts", headers=buy.clerk, json=body)).status_code == 403  # BR-GRN-003
    grn = (await client.post(f"{API}/goods-receipts", headers=buy.receiver, json=body)).json()
    assert grn["flagged_for_review"]
    assert (await act(client, "goods-receipts", grn["id"], "post", buy.receiver)).json()["status"] == "PENDING_APPROVAL"
    assert (await act(client, "goods-receipts", grn["id"], "approve", buy.approver)).json()["status"] == "POSTED"


async def test_partial_receipt_and_short_close(client: httpx.AsyncClient, buy: Buy):
    po = await approved_po(client, buy, qty="5")
    grn = await receive(client, buy, po, quantity_received="2")
    assert any("short by" in d for d in grn["discrepancies"])
    await act(client, "goods-receipts", grn["id"], "post", buy.clerk)
    po = (await client.get(f"{API}/purchase-orders/{po['id']}", headers=buy.buyer)).json()
    assert po["status"] == "PARTIALLY_RECEIVED" and po["lines"][0]["received_base"] == "24.0000"
    closed = (await act(client, "purchase-orders", po["id"], "close", buy.approver, {"reason": "Supplier cannot deliver rest"})).json()
    assert closed["status"] == "SHORT_CLOSED" and closed["lines"][0]["cancelled_base"] == "36.0000"
    assert (await stock(client, buy))["on_order"] == "0"


async def test_expiry_tracked_products_need_batch(client: httpx.AsyncClient, buy: Buy):
    await client.patch(f"{API}/products/{buy.product}", headers=buy.owner, json={"track_expiry": True})
    po = await approved_po(client, buy)
    missing = await client.post(f"{API}/goods-receipts", headers=buy.clerk, json={"po_id": po["id"], "lines": [
        {"po_line_id": po["lines"][0]["id"], "product_id": buy.product, "unit_id": buy.case, "quantity_received": "2", "unit_cost": "12"}]})
    assert missing.status_code == 422
    grn = await receive(client, buy, po, batch_no="LOT-9", expiry_date=(date.today() + timedelta(days=200)).isoformat())
    await act(client, "goods-receipts", grn["id"], "post", buy.clerk)
    batches = (await client.get(f"{API}/inventory/batches", headers=buy.owner)).json()["items"]
    assert [(x["batch_no"], x["quantity"]) for x in batches] == [("LOT-9", "24.0000")]


# Supplier invoices

async def test_invoice_matching_duplicates_and_payments(client: httpx.AsyncClient, buy: Buy):
    po = await approved_po(client, buy)
    grn = await receive(client, buy, po)
    await act(client, "goods-receipts", grn["id"], "post", buy.clerk)
    today = date.today().isoformat()
    due = (date.today() + timedelta(days=30)).isoformat()
    matched = await client.post(f"{API}/supplier-invoices", headers=buy.buyer, json={"invoice_no": "INV-001", "supplier_id": buy.supplier, "po_id": po["id"], "invoice_date": today, "due_date": due, "amount": "24"})
    assert matched.json()["status"] == "MATCHED", matched.text
    dup = await client.post(f"{API}/supplier-invoices", headers=buy.buyer, json={"invoice_no": "inv 001", "supplier_id": buy.supplier, "po_id": "", "invoice_date": today, "due_date": due, "amount": "24"})
    assert dup.json()["error"]["code"] == "DUPLICATE_INVOICE"  # BR-PUR-003
    mismatch = await client.post(f"{API}/supplier-invoices", headers=buy.buyer, json={"invoice_no": "INV-002", "supplier_id": buy.supplier, "po_id": po["id"], "invoice_date": today, "due_date": due, "amount": "30"})
    assert mismatch.json()["status"] == "MISMATCH" and "Warning" not in mismatch.json()["match_notes"]
    inv = matched.json()["id"]
    assert (await client.post(f"{API}/supplier-invoices/{inv}/payments", headers=buy.buyer, json={"amount": "30", "reference": "TT-1"})).status_code == 422
    part = (await client.post(f"{API}/supplier-invoices/{inv}/payments", headers=buy.buyer, json={"amount": "10", "reference": "TT-1"})).json()
    assert (part["status"], part["paid_amount"]) == ("PARTIALLY_PAID", "10.0000")
    supplier = (await client.get(f"{API}/suppliers/{buy.supplier}", headers=buy.buyer)).json()
    assert supplier["outstanding_balance"] == "44.0000" and supplier["on_time_rate"] == "100.00" and supplier["fill_rate"] == "100.00"


# Purchase returns

async def test_purchase_return_flow(client: httpx.AsyncClient, buy: Buy):
    po = await approved_po(client, buy)
    grn = await receive(client, buy, po)
    await act(client, "goods-receipts", grn["id"], "post", buy.clerk)
    too_many = await client.post(f"{API}/purchase-returns", headers=buy.buyer, json={"goods_receipt_id": grn["id"], "reason": "x", "lines": [{"product_id": buy.product, "location_id": buy.shelf, "quantity_base": "30"}]})
    assert too_many.status_code == 422
    pr = (await client.post(f"{API}/purchase-returns", headers=buy.buyer, json={"goods_receipt_id": grn["id"], "reason": "Leaking bottles",
                                                                               "lines": [{"product_id": buy.product, "name": "Cooking oil", "location_id": buy.shelf, "quantity_base": "6"}]})).json()
    assert (pr["status"], pr["total"]) == ("DRAFT", "6.0000")
    assert (await act(client, "purchase-returns", pr["id"], "approve", buy.approver)).json()["status"] == "APPROVED"
    dispatched = (await act(client, "purchase-returns", pr["id"], "dispatch", buy.buyer)).json()
    assert dispatched["status"] == "DISPATCHED"
    assert (await stock(client, buy))["on_hand"] == "28.0000"
    product = (await client.get(f"{API}/products/{buy.product}", headers=buy.owner)).json()
    assert product["avg_cost"] == "1.357143"  # (44 - 6 x 1) / 28: returned at the cost it came in at
    credited = (await act(client, "purchase-returns", pr["id"], "credit", buy.buyer, {"credit_note_ref": "CN-55"})).json()
    assert (credited["status"], credited["credit_note_ref"]) == ("CREDITED", "CN-55")
    assert (await client.post(f"{API}/inventory/reconciliation", headers=buy.owner)).json()["differences"] == []


async def test_supplier_links_drive_reorder_suggestions(client: httpx.AsyncClient, buy: Buy):
    updated = await client.patch(f"{API}/products/{buy.product}", headers=buy.owner, json={
        "stock_settings": {"reorder_level": "20", "min_level": "0", "max_level": "50", "reorder_qty": "24"},
        "suppliers": [{"supplier_id": buy.supplier, "supplier_sku": "MF-OIL", "purchase_unit_id": buy.case, "cost": "11.50", "lead_time_days": 4, "preferred": True}]})
    assert updated.status_code == 200, updated.text
    assert updated.json()["suppliers"][0]["supplier_sku"] == "MF-OIL"
    suggestion = next(x for x in (await client.get(f"{API}/inventory/reorder-suggestions", headers=buy.owner)).json()["items"] if x["product_id"] == buy.product)
    assert (suggestion["supplier_name"], suggestion["purchase_unit_code"], suggestion["suggested_base"], suggestion["suggested_qty"], suggestion["lead_time_days"]) == ("Mekong Foods", "CASE", "40.0000", "4", 4)
    po = await make_po(client, buy)
    assert po["lines"][0]["supplier_sku"] == "MF-OIL"
    two = await client.patch(f"{API}/products/{buy.product}", headers=buy.owner, json={"suppliers": [
        {"supplier_id": buy.supplier, "preferred": True}, {"supplier_id": buy.supplier, "preferred": False}]})
    assert two.status_code == 422


async def test_supplier_with_open_orders_cannot_be_removed(client: httpx.AsyncClient, buy: Buy):
    await approved_po(client, buy)
    assert (await client.delete(f"{API}/suppliers/{buy.supplier}", headers=buy.buyer)).json()["error"]["code"] == "SUPPLIER_IN_USE"
    dup = await client.post(f"{API}/suppliers", headers=buy.buyer, json={"code": "sup1", "name_en": "Dup"})
    assert dup.status_code == 409


