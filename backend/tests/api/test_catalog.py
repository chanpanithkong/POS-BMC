"""Catalogue, products, barcodes and pricing (Phase 3)."""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import Product
from app.services.products import check_digit
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db
API = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def ean13(body12: str) -> str:
    return body12 + str(check_digit(body12))


@dataclass
class Catalog:
    owner: dict
    pcs: str
    box: str
    kg: str
    category: str


@pytest.fixture
async def cat(client: httpx.AsyncClient, world: World, login: LoginFn) -> Catalog:
    owner = await login(await world.user("OWNER"))

    async def post(path: str, body: dict) -> str:
        response = await client.post(f"{API}/{path}", headers=owner, json=body)
        assert response.status_code == 201, response.text
        return response.json()["id"]

    return Catalog(
        owner=owner,
        pcs=await post("units", {"code": "PCS", "name_en": "Piece"}),
        box=await post("units", {"code": "BOX", "name_en": "Box"}),
        kg=await post("units", {"code": "KG", "name_en": "Kilogram", "dimension": "MASS", "precision": 3}),
        category=await post("categories", {"code": "DRINK", "name_en": "Drinks"}),
    )


async def make_product(client: httpx.AsyncClient, cat: Catalog, **extra) -> dict:
    body = {"name_en": "Water 500ml", "category_id": cat.category, "base_unit_id": cat.pcs, "retail_price": "0.50", **extra}
    response = await client.post(f"{API}/products", headers=cat.owner, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# Categories, brands, units

async def test_category_depth_and_cycles(client: httpx.AsyncClient, cat: Catalog):
    parent = cat.category
    for level in range(2, 5):
        r = await client.post(f"{API}/categories", headers=cat.owner, json={"code": f"L{level}", "name_en": f"Level {level}", "parent_id": parent})
        assert r.status_code == 201
        parent = r.json()["id"]
    too_deep = await client.post(f"{API}/categories", headers=cat.owner, json={"code": "L5", "name_en": "Level 5", "parent_id": parent})
    assert too_deep.status_code == 422
    cycle = await client.patch(f"{API}/categories/{cat.category}", headers=cat.owner, json={"parent_id": parent})
    assert cycle.status_code == 422


async def test_category_negative_stock_needs_company_setting(client: httpx.AsyncClient, cat: Catalog):
    blocked = await client.patch(f"{API}/categories/{cat.category}", headers=cat.owner, json={"allow_negative_stock": True})
    assert blocked.status_code == 422
    await client.patch(f"{API}/settings", headers=cat.owner, json={"negative_stock_allowed": True})
    assert (await client.patch(f"{API}/categories/{cat.category}", headers=cat.owner, json={"allow_negative_stock": True})).status_code == 200


async def test_in_use_master_data_cannot_be_deleted(client: httpx.AsyncClient, cat: Catalog):
    await make_product(client, cat)
    assert (await client.delete(f"{API}/categories/{cat.category}", headers=cat.owner)).status_code == 409
    assert (await client.delete(f"{API}/units/{cat.pcs}", headers=cat.owner)).status_code == 409
    assert (await client.delete(f"{API}/units/{cat.kg}", headers=cat.owner)).status_code == 204
    assert (await client.post(f"{API}/units", headers=cat.owner, json={"code": "pcs", "name_en": "Dup"})).status_code == 409


async def test_cashier_cannot_manage_catalogue(client: httpx.AsyncClient, world: World, login: LoginFn, cat: Catalog):
    cashier = await login(await world.user("CASHIER"))
    assert (await client.get(f"{API}/categories", headers=cashier)).status_code == 200
    assert (await client.post(f"{API}/brands", headers=cashier, json={"code": "B", "name": "B"})).status_code == 403
    assert (await client.post(f"{API}/products", headers=cashier, json={"name_en": "X", "category_id": cat.category, "base_unit_id": cat.pcs})).status_code == 403


# Products

async def test_create_with_auto_sku_price_conversion_and_barcode(client: httpx.AsyncClient, cat: Catalog):
    code = ean13("885000000001")
    product = await make_product(client, cat, status="ACTIVE", wholesale_price="0.40",
                                 conversions=[{"unit_id": cat.box, "factor": "24", "is_sales_default": False, "is_purchase_default": True}],
                                 barcodes=[{"barcode": code, "symbology": "EAN13", "unit_id": cat.pcs}])
    assert product["sku"] == "SKU-000001" and product["status"] == "ACTIVE"
    assert product["retail_price"] == "0.5000" and product["wholesale_price"] == "0.4000"
    assert product["conversions"][0]["factor"] == "24.0000"
    assert product["barcodes"][0]["barcode"] == code
    assert product["unit_code"] == "PCS" and product["category_name"] == "Drinks"


async def test_frontend_payload_shape_is_accepted(client: httpx.AsyncClient, cat: Catalog):
    """The product form sends ids and created_at as empty strings and several read-only-looking fields."""
    body = {
        "type": "STANDARD", "sku": "", "name_en": "Rice 5kg", "name_km": "អង្ករ", "description": "", "category_id": cat.category, "brand_id": None, "base_unit_id": cat.pcs,
        "tax_code_id": None, "allow_fraction": False, "precision": 0, "retail_price": "6.5", "wholesale_price": "6", "min_selling_price": None, "track_expiry": False,
        "is_favourite": True, "image": None, "status": "DRAFT", "conversions": [], "suppliers": [],
        "barcodes": [{"id": "", "barcode": "RICE-5KG", "symbology": "CODE128", "unit_id": cat.pcs, "active": True, "created_at": ""}],
        "stock_settings": {"reorder_level": 10, "min_level": 5, "max_level": 100, "reorder_qty": 50}, "warehouse_settings": {}, "variants": [],
    }
    response = await client.post(f"{API}/products", headers=cat.owner, json=body)
    assert response.status_code == 201, response.text
    saved = response.json()
    update = await client.patch(f"{API}/products/{saved['id']}", headers=cat.owner, json={**{k: v for k, v in body.items() if k != "variants"}, "barcodes": saved["barcodes"], "name_en": "Rice 5 kg"})
    assert update.status_code == 200, update.text
    assert update.json()["name_en"] == "Rice 5 kg" and update.json()["stock_settings"]["reorder_level"] == "10.0000"


async def test_barcode_rules(client: httpx.AsyncClient, cat: Catalog):
    good = ean13("885000000002")
    bad_check = good[:-1] + str((int(good[-1]) + 1) % 10)
    wrong = await client.post(f"{API}/products", headers=cat.owner, json={"name_en": "X", "category_id": cat.category, "base_unit_id": cat.pcs, "barcodes": [{"barcode": bad_check, "symbology": "EAN13", "unit_id": cat.pcs}]})
    assert wrong.status_code == 422
    first = await make_product(client, cat, barcodes=[{"barcode": good, "symbology": "EAN13", "unit_id": cat.pcs}])
    clash = await client.post(f"{API}/products", headers=cat.owner, json={"name_en": "Y", "category_id": cat.category, "base_unit_id": cat.pcs, "barcodes": [{"barcode": good, "symbology": "EAN13", "unit_id": cat.pcs}]})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "DUPLICATE_BARCODE"
    # Deactivating it on the first product frees it for another product.
    released = await client.patch(f"{API}/products/{first['id']}", headers=cat.owner, json={"barcodes": [{"barcode": good, "symbology": "EAN13", "unit_id": cat.pcs, "active": False}]})
    assert released.status_code == 200 and released.json()["barcodes"][0]["active"] is False
    assert (await client.post(f"{API}/products", headers=cat.owner, json={"name_en": "Y", "category_id": cat.category, "base_unit_id": cat.pcs, "barcodes": [{"barcode": good, "symbology": "EAN13", "unit_id": cat.pcs}]})).status_code == 201


async def test_generated_barcodes_are_valid_and_distinct(client: httpx.AsyncClient, cat: Catalog):
    codes = [(await client.post(f"{API}/products/barcodes/generate", headers=cat.owner)).json()["barcode"] for _ in range(3)]
    assert len(set(codes)) == 3
    assert all(len(c) == 13 and c.startswith("20") and check_digit(c[:12]) == int(c[12]) for c in codes)


async def test_activation_needs_a_retail_price(client: httpx.AsyncClient, cat: Catalog):
    r = await client.post(f"{API}/products", headers=cat.owner, json={"name_en": "No price", "category_id": cat.category, "base_unit_id": cat.pcs, "status": "ACTIVE"})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "retail_price"


async def test_status_transitions(client: httpx.AsyncClient, cat: Catalog):
    product = await make_product(client, cat, status="ACTIVE")
    assert (await client.patch(f"{API}/products/{product['id']}", headers=cat.owner, json={"status": "DISCONTINUED"})).status_code == 200
    back = await client.patch(f"{API}/products/{product['id']}", headers=cat.owner, json={"status": "ACTIVE"})
    assert back.status_code == 409 and back.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_base_unit_locked_after_movements(client: httpx.AsyncClient, world: World, cat: Catalog):
    product = await make_product(client, cat)
    await world.db.execute(text("UPDATE products SET has_movements = true WHERE id = :id"), {"id": product["id"]})
    await world.db.commit()
    r = await client.patch(f"{API}/products/{product['id']}", headers=cat.owner, json={"base_unit_id": cat.box})
    assert r.status_code == 422
    assert (await client.delete(f"{API}/products/{product['id']}", headers=cat.owner)).status_code == 409


async def test_weighed_products_are_fractional(client: httpx.AsyncClient, cat: Catalog):
    count_unit = await client.post(f"{API}/products", headers=cat.owner, json={"name_en": "Pork", "type": "WEIGHED", "category_id": cat.category, "base_unit_id": cat.pcs})
    assert count_unit.status_code == 422
    pork = await make_product(client, cat, name_en="Pork", type="WEIGHED", base_unit_id=cat.kg, retail_price="5.80")
    assert pork["allow_fraction"] is True and pork["precision"] == 3


async def test_costs_hidden_without_permission(client: httpx.AsyncClient, world: World, login: LoginFn, cat: Catalog):
    product = await make_product(client, cat)
    assert (await client.get(f"{API}/products/{product['id']}", headers=cat.owner)).json()["avg_cost"] == "0.000000"
    cashier = await login(await world.user("CASHIER"))
    seen = (await client.get(f"{API}/products/{product['id']}", headers=cashier)).json()
    assert seen["avg_cost"] is None and seen["last_purchase_cost"] is None


async def test_variants_are_created_as_children(client: httpx.AsyncClient, cat: Catalog):
    parent = await make_product(client, cat, name_en="T-shirt", type="VARIANT_PARENT", sku="TS", retail_price="8", variants=[
        {"attrs": {"_colour": "Red", "_size": "M"}, "sku": "TS-REDM"}, {"attrs": {"_colour": "Red", "_size": "L"}, "sku": "TS-REDL", "barcode": "TSREDL"},
    ])
    children = (await client.get(f"{API}/products", headers=cat.owner, params={"q": "TS-RED"})).json()["items"]
    assert {c["sku"] for c in children} == {"TS-REDM", "TS-REDL"}
    assert all(c["parent_id"] == parent["id"] and c["retail_price"] == "8.0000" for c in children)
    assert next(c for c in children if c["sku"] == "TS-REDM")["variant_attrs"] == {"Colour": "Red", "Size": "M"}


async def test_search_by_name_sku_and_barcode(client: httpx.AsyncClient, cat: Catalog):
    await make_product(client, cat, name_en="Coca-Cola 330ml", name_km="កូកា", sku="COKE330", barcodes=[{"barcode": "COKE-330", "unit_id": cat.pcs}])
    for q in ("coca", "កូកា", "coke3", "COKE-330"):
        items = (await client.get(f"{API}/products", headers=cat.owner, params={"q": q})).json()["items"]
        assert [i["sku"] for i in items] == ["COKE330"], q


async def test_delete_draft_and_history(client: httpx.AsyncClient, cat: Catalog):
    product = await make_product(client, cat)
    await client.patch(f"{API}/products/{product['id']}", headers=cat.owner, json={"name_en": "Water 600ml"})
    history = (await client.get(f"{API}/products/{product['id']}/history", headers=cat.owner)).json()["items"]
    assert any(h["field"] == "name_en" and h["before"] == "Water 500ml" and h["after"] == "Water 600ml" for h in history)
    assert (await client.delete(f"{API}/products/{product['id']}", headers=cat.owner)).status_code == 204
    assert (await client.get(f"{API}/products/{product['id']}", headers=cat.owner)).status_code == 404


async def test_duplicate(client: httpx.AsyncClient, cat: Catalog):
    product = await make_product(client, cat, barcodes=[{"barcode": "DUP-1", "unit_id": cat.pcs}])
    copy = (await client.post(f"{API}/products/{product['id']}/duplicate", headers=cat.owner)).json()
    assert copy["status"] == "DRAFT" and copy["sku"] != product["sku"] and copy["barcodes"] == [] and copy["retail_price"] == "0.5000"


async def test_image_upload_and_serving(client: httpx.AsyncClient, cat: Catalog):
    data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
    product = await make_product(client, cat, image=data_url)
    assert product["image"].startswith("/api/v1/files/products/")
    served = await client.get(product["image"])
    assert served.status_code == 200 and served.content == PNG
    fake = "data:image/png;base64," + base64.b64encode(b"<script>alert(1)</script>").decode()
    assert (await client.post(f"{API}/products", headers=cat.owner, json={"name_en": "X", "category_id": cat.category, "base_unit_id": cat.pcs, "image": fake})).status_code == 422
    assert (await client.get(f"{API}/files/products/..%2F..%2F.env")).status_code == 404


# Pricing

async def _retail(client: httpx.AsyncClient, cat: Catalog, product_id: str) -> str:
    return (await client.get(f"{API}/products/{product_id}", headers=cat.owner)).json()["retail_price"]


async def test_new_price_closes_the_old_one_and_is_recorded(client: httpx.AsyncClient, cat: Catalog):
    product = await make_product(client, cat)
    r = await client.post(f"{API}/prices", headers=cat.owner, json={"product_id": product["id"], "price": "0.60"})
    assert r.status_code == 201, r.text
    assert await _retail(client, cat, product["id"]) == "0.6000"
    rows = (await client.get(f"{API}/prices", headers=cat.owner, params={"product_id": product["id"], "include_past": True})).json()["items"]
    assert len(rows) == 2 and rows[1]["effective_to"] == rows[0]["effective_from"]
    history = (await client.get(f"{API}/prices/history", headers=cat.owner, params={"product_id": product["id"]})).json()["items"]
    assert [(h["old_price"], h["new_price"]) for h in history] == [("0.5000", "0.6000"), (None, "0.5000")]
    assert (await client.post(f"{API}/prices", headers=cat.owner, json={"product_id": product["id"], "price": "0.60"})).json()["error"]["code"] == "NO_CHANGE"


async def test_prices_cannot_be_backdated_or_below_minimum(client: httpx.AsyncClient, cat: Catalog):
    product = await make_product(client, cat, min_selling_price="0.45")
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert (await client.post(f"{API}/prices", headers=cat.owner, json={"product_id": product["id"], "price": "0.70", "effective_from": past})).status_code == 422
    assert (await client.post(f"{API}/prices", headers=cat.owner, json={"product_id": product["id"], "price": "0.40"})).status_code == 422


async def test_scheduled_price_can_be_removed_and_reopens_previous(client: httpx.AsyncClient, cat: Catalog):
    product = await make_product(client, cat)
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    scheduled = (await client.post(f"{API}/prices", headers=cat.owner, json={"product_id": product["id"], "price": "0.75", "effective_from": future})).json()
    assert await _retail(client, cat, product["id"]) == "0.5000"
    clash = await client.post(f"{API}/prices", headers=cat.owner, json={"product_id": product["id"], "price": "0.55"})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "PRICE_SCHEDULE_CONFLICT"
    assert (await client.delete(f"{API}/prices/{scheduled['id']}", headers=cat.owner)).status_code == 204
    rows = (await client.get(f"{API}/prices", headers=cat.owner, params={"product_id": product["id"]})).json()["items"]
    assert len(rows) == 1 and rows[0]["effective_to"] is None
    current = rows[0]["id"]
    assert (await client.delete(f"{API}/prices/{current}", headers=cat.owner)).json()["error"]["code"] == "PRICE_IN_EFFECT"


async def test_resolution_order_and_unit_fallback(client: httpx.AsyncClient, world: World, cat: Catalog):
    code_pcs, code_box = ean13("885000000010"), ean13("885000000027")
    product = await make_product(client, cat, status="ACTIVE", conversions=[{"unit_id": cat.box, "factor": "24"}],
                                 barcodes=[{"barcode": code_pcs, "symbology": "EAN13", "unit_id": cat.pcs}, {"barcode": code_box, "symbology": "EAN13", "unit_id": cat.box}])
    await client.post(f"{API}/prices", headers=cat.owner, json={"product_id": product["id"], "price": "0.45", "branch_id": str(world.branch_a.id)})
    scan_a = (await client.get(f"{API}/products/barcode/{code_pcs}", headers=cat.owner, params={"branch_id": str(world.branch_a.id)})).json()
    scan_b = (await client.get(f"{API}/products/barcode/{code_pcs}", headers=cat.owner, params={"branch_id": str(world.branch_b.id)})).json()
    assert (scan_a["unit_price"], scan_a["price_source"]) == ("0.4500", "BRANCH")
    assert (scan_b["unit_price"], scan_b["price_source"]) == ("0.5000", "RETAIL")
    box = (await client.get(f"{API}/products/barcode/{code_box}", headers=cat.owner)).json()
    assert (box["unit_price"], box["price_source"], box["unit_factor"]) == ("12.0000", "RETAIL_BASE_UNIT", "24.0000")
    await client.post(f"{API}/prices", headers=cat.owner, json={"product_id": product["id"], "unit_id": cat.box, "price": "11"})
    box = (await client.get(f"{API}/products/barcode/{code_box}", headers=cat.owner)).json()
    assert (box["unit_price"], box["price_source"]) == ("11.0000", "RETAIL")


async def test_scan_refuses_unsellable_products(client: httpx.AsyncClient, world: World, cat: Catalog):
    product = await make_product(client, cat, barcodes=[{"barcode": "DRAFT-1", "unit_id": cat.pcs}])
    assert (await client.get(f"{API}/products/barcode/DRAFT-1", headers=cat.owner)).json()["error"]["code"] == "PRODUCT_NOT_SELLABLE"
    await client.patch(f"{API}/products/{product['id']}", headers=cat.owner, json={"status": "ACTIVE", "branch_activation": {str(world.branch_b.id): False}})
    assert (await client.get(f"{API}/products/barcode/DRAFT-1", headers=cat.owner, params={"branch_id": str(world.branch_a.id)})).status_code == 200
    assert (await client.get(f"{API}/products/barcode/DRAFT-1", headers=cat.owner, params={"branch_id": str(world.branch_b.id)})).status_code == 422
    assert (await client.get(f"{API}/products/barcode/NOPE", headers=cat.owner)).status_code == 404


async def test_bulk_price_change(client: httpx.AsyncClient, cat: Catalog):
    a = await make_product(client, cat, name_en="A", retail_price="1.00")
    b = await make_product(client, cat, name_en="B", retail_price="2.00", min_selling_price="1.95")
    preview = (await client.post(f"{API}/prices/bulk/preview", headers=cat.owner, json={"category_id": cat.category, "mode": "PERCENT", "value": -5})).json()["items"]
    assert {(r["sku"], r["new_price"], r["below_min"]) for r in preview} == {(a["sku"], "0.95", False), (b["sku"], "1.90", True)}
    rejected = await client.post(f"{API}/prices/bulk", headers=cat.owner, json={"category_id": cat.category, "mode": "PERCENT", "value": -5})
    assert rejected.status_code == 422
    applied = await client.post(f"{API}/prices/bulk", headers=cat.owner, json={"category_id": cat.category, "mode": "AMOUNT", "value": "0.10"})
    assert applied.json() == {"updated": 2, "scheduled": False}
    assert await _retail(client, cat, a["id"]) == "1.1000" and await _retail(client, cat, b["id"]) == "2.1000"


async def test_cashier_cannot_change_prices(client: httpx.AsyncClient, world: World, login: LoginFn, cat: Catalog):
    product = await make_product(client, cat)
    cashier = await login(await world.user("CASHIER"))
    assert (await client.post(f"{API}/prices", headers=cashier, json={"product_id": product["id"], "price": "0.1"})).status_code == 403


async def test_database_rejects_overlapping_prices(world: World, client: httpx.AsyncClient, cat: Catalog):
    product = await make_product(client, cat)
    row = (await world.db.execute(text("SELECT unit_id, price_list_id FROM product_prices WHERE product_id = :p"), {"p": product["id"]})).one()
    with pytest.raises(IntegrityError):
        await world.db.execute(text(
            "INSERT INTO product_prices (id, company_id, product_id, unit_id, price_list_id, price, effective_from) "
            "VALUES (gen_random_uuid(), :c, :p, :u, :l, 1, now() - interval '1 hour')"
        ), {"c": world.company.id, "p": product["id"], "u": row.unit_id, "l": row.price_list_id})
    await world.db.rollback()
    assert await world.db.scalar(select(Product.sku).where(Product.id == product["id"]))
