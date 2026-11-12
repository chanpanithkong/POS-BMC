"""Customers, groups, group pricing, store credit and loyalty (Phase 6)."""

import httpx
import pytest

from tests.api.test_sales import Shop, approval, ik, new_sale, pay, shop  # noqa: F401  (shop is a fixture)
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db
API = "/api/v1"


async def customer(client: httpx.AsyncClient, headers: dict, **body) -> dict:
    r = await client.post(f"{API}/customers", headers=headers, json={"name": "Sok Dara", "phone": "+855 12 345 678", "email": "", "address": "", "notes": "", "consent_marketing": False, "group_id": "", **body})
    assert r.status_code == 201, r.text
    return r.json()


async def finalize(client: httpx.AsyncClient, shop: Shop, sale: dict, **payment) -> dict:  # noqa: F811
    await pay(client, shop, sale["id"], amount_tendered=sale["grand_total"], **payment)
    r = await client.post(f"{API}/sales/{sale['id']}/finalize", headers=ik(shop.cashier))
    assert r.status_code == 200, r.text
    return r.json()


async def test_customer_codes_phone_uniqueness_and_masking(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    c = await customer(client, shop.owner)
    assert c["code"] == "CUS-000001" and c["phone"] == "+855 12 345 678"
    dup = await client.post(f"{API}/customers", headers=shop.owner, json={"name": "Other", "phone": "012345678"})
    assert dup.status_code == 409  # same number in local format
    seen_by_cashier = (await client.get(f"{API}/customers/{c['id']}", headers=shop.cashier)).json()
    assert seen_by_cashier["phone"] != c["phone"] and "•" in seen_by_cashier["phone"]
    found = (await client.get(f"{API}/customers", headers=shop.cashier, params={"q": "012 345"})).json()["items"]
    assert [x["id"] for x in found] == [c["id"]]
    blocked = await client.patch(f"{API}/customers/{c['id']}", headers=shop.cashier, json={"phone": "099999999"})
    assert blocked.status_code == 403


async def test_group_discount_and_group_price(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    group = (await client.post(f"{API}/customer-groups", headers=shop.owner, json={"code": "WHOLE", "name": "Wholesale", "price_list_id": "", "discount_pct": "10", "status": "ACTIVE"})).json()
    assert group["price_list_id"]
    c = await customer(client, shop.owner, group_id=group["id"])
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"}, {"type": "set_customer", "customer_id": c["id"]})
    line = sale["lines"][0]
    assert (sale["customer_name"], line["unit_price"], line["price_source"]) == ("Sok Dara", "1.8000", "CUSTOMER_GROUP")
    set_price = await client.post(f"{API}/prices", headers=shop.owner, json={"product_id": shop.product, "price": "1.50", "customer_group_id": group["id"]})
    assert set_price.status_code == 201, set_price.text
    repriced = (await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "set_quantity", "line_id": line["id"], "quantity": "2"}]})).json()
    assert repriced["lines"][0]["unit_price"] == "1.5000"  # an explicit group price beats the group discount
    walk_in = (await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "set_customer", "customer_id": None}]})).json()
    assert walk_in["lines"][0]["unit_price"] == "2.0000"


async def test_store_credit_refund_spend_and_void(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    await client.patch(f"{API}/settings", headers=shop.owner, json={"store_credit_enabled": True})
    c = await customer(client, shop.owner)
    sale = await finalize(client, shop, await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "2"}, {"type": "set_customer", "customer_id": c["id"]}))
    ret = await client.post(f"{API}/sales/{sale['id']}/returns", headers=ik(shop.cashier),
                            json={"lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1", "condition": "RESALABLE", "reason": "Gift"}], "refund_method": "STORE_CREDIT"})
    assert ret.status_code == 201, ret.text
    assert (await client.get(f"{API}/customers/{c['id']}", headers=shop.owner)).json()["store_credit"] == "2.2000"
    second = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "2"}, {"type": "set_customer", "customer_id": c["id"]})
    too_much = await pay(client, shop, second["id"], method="STORE_CREDIT", amount_tendered="3")
    assert too_much.status_code == 422
    paid = (await pay(client, shop, second["id"], method="STORE_CREDIT", amount_tendered="2.20")).json()
    assert paid["balance"] == "2.2000"
    await pay(client, shop, second["id"], amount_tendered="2.20")
    done = (await client.post(f"{API}/sales/{second['id']}/finalize", headers=ik(shop.cashier))).json()
    assert (await client.get(f"{API}/customers/{c['id']}", headers=shop.owner)).json()["store_credit"] == "0.0000"
    voided = await client.post(f"{API}/sales/{done['id']}/void", headers=ik(shop.cashier), json={"reason": "Mistake", "approval_token": await approval(client, shop, "VOID_SALE")})
    assert voided.json()["status"] == "VOIDED", voided.text
    assert (await client.get(f"{API}/customers/{c['id']}", headers=shop.owner)).json()["store_credit"] == "2.2000"  # credit returned


async def test_store_credit_needs_setting_and_customer(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    sale = await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"})
    assert (await pay(client, shop, sale["id"], method="STORE_CREDIT", amount_tendered="1")).status_code == 422
    c = await customer(client, shop.owner)
    await client.patch(f"{API}/sales/{sale['id']}", headers=shop.cashier, json={"ops": [{"type": "set_customer", "customer_id": c["id"]}]})
    off = await pay(client, shop, sale["id"], method="STORE_CREDIT", amount_tendered="1")
    assert off.status_code == 422 and "turned off" in off.json()["error"]["message"]


async def test_loyalty_and_spend_recorded(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    await client.patch(f"{API}/settings", headers=shop.owner, json={"loyalty_enabled": True, "loyalty_points_per_usd": "1"})
    c = await customer(client, shop.owner)
    sale = await finalize(client, shop, await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "5"}, {"type": "set_customer", "customer_id": c["id"]}))
    assert sale["loyalty_earned"] == "11.0000"  # 11.00 USD
    after = (await client.get(f"{API}/customers/{c['id']}", headers=shop.owner)).json()
    assert (after["loyalty_points"], after["total_spent"]) == ("11.0000", "11.0000") and after["last_purchase_at"]


async def test_anonymise_keeps_history(client: httpx.AsyncClient, shop: Shop, world: World, login: LoginFn):  # noqa: F811
    c = await customer(client, shop.owner)
    await finalize(client, shop, await new_sale(client, shop, {"type": "add_product", "product_id": shop.product, "quantity": "1"}, {"type": "set_customer", "customer_id": c["id"]}))
    assert (await client.delete(f"{API}/customers/{c['id']}", headers=shop.owner)).json()["error"]["code"] == "CUSTOMER_IN_USE"
    anon = (await client.post(f"{API}/customers/{c['id']}/anonymize", headers=shop.owner)).json()
    assert (anon["name"], anon["phone"], anon["anonymized"], anon["status"]) == ("Anonymised customer", "", True, "INACTIVE")
    cashier = await login(await world.user("CASHIER"))
    assert (await client.post(f"{API}/customers/{c['id']}/anonymize", headers=cashier)).status_code == 403
    again = await customer(client, shop.owner)  # the number is free again
    assert again["phone"] == "+855 12 345 678"


async def test_group_in_use_and_inactive_group(client: httpx.AsyncClient, shop: Shop):  # noqa: F811
    group = (await client.post(f"{API}/customer-groups", headers=shop.owner, json={"code": "VIP", "name": "VIP", "discount_pct": "5"})).json()
    await customer(client, shop.owner, group_id=group["id"])
    assert (await client.delete(f"{API}/customer-groups/{group['id']}", headers=shop.owner)).json()["error"]["code"] == "GROUP_IN_USE"
    await client.patch(f"{API}/customer-groups/{group['id']}", headers=shop.owner, json={"status": "INACTIVE"})
    assert (await client.post(f"{API}/customers", headers=shop.owner, json={"name": "New", "group_id": group["id"]})).status_code == 422
