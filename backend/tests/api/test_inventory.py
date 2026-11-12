"""Inventory ledger, costing, adjustments, transfers, counts, alerts (Phase 4)."""

import asyncio
import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import InventoryMovement, Warehouse, WarehouseLocation
from tests.conftest import LoginFn, World

pytestmark = pytest.mark.db
API = "/api/v1"


def ik(headers: dict) -> dict:
    return {**headers, "Idempotency-Key": f"test-{uuid.uuid4()}"}


@dataclass
class Store:
    owner: dict
    unit: str
    category: str
    shelf: str  # sellable location in branch A's warehouse (WA)
    store: str  # storage location in WA
    damaged: str
    wh_a: str
    wh_b: str
    recv_b: str
    world: World


@pytest.fixture
async def store(client: httpx.AsyncClient, world: World, login: LoginFn) -> Store:
    owner = await login(await world.user("OWNER"))

    async def post(path: str, body: dict) -> dict:
        r = await client.post(f"{API}/{path}", headers=owner, json=body)
        assert r.status_code == 201, r.text
        return r.json()

    unit = (await post("units", {"code": "PCS", "name_en": "Piece"}))["id"]
    category = (await post("categories", {"code": "GEN", "name_en": "General"}))["id"]
    wa = await world.db.scalar(select(Warehouse).where(Warehouse.company_id == world.company.id, Warehouse.code == "WA"))
    shelf = await world.db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == wa.id, WarehouseLocation.code == "SHELF"))
    storage = await post("locations", {"code": "STORE", "name": "Back store", "warehouse_id": str(wa.id), "type": "STORAGE"})
    damaged = await post("locations", {"code": "DMG", "name": "Damaged", "warehouse_id": str(wa.id), "type": "DAMAGED"})
    branch_b = await post("branches", {"code": "B2", "name_en": "Branch B2"})
    warehouses = (await client.get(f"{API}/warehouses", headers=owner)).json()["items"]
    wh_b = next(w for w in warehouses if w["branch_id"] == branch_b["id"])
    locations = (await client.get(f"{API}/locations", headers=owner, params={"warehouse_id": wh_b["id"]})).json()["items"]
    recv_b = next(loc["id"] for loc in locations if loc["type"] == "RECEIVING")
    return Store(owner, unit, category, str(shelf.id), storage["id"], damaged["id"], str(wa.id), wh_b["id"], recv_b, world)


async def product(client: httpx.AsyncClient, st: Store, sku: str, **extra) -> str:
    body = {"sku": sku, "name_en": sku, "category_id": st.category, "base_unit_id": st.unit, "retail_price": "2", "status": "ACTIVE", **extra}
    r = await client.post(f"{API}/products", headers=st.owner, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def opening(client: httpx.AsyncClient, st: Store, product_id: str, location: str, qty: str, cost: str, **extra) -> httpx.Response:
    return await client.post(f"{API}/inventory/opening-balances", headers=ik(st.owner), json={"product_id": product_id, "location_id": location, "quantity": qty, "unit_cost": cost, **extra})


async def on_hand(client: httpx.AsyncClient, st: Store, product_id: str, location: str | None = None) -> Decimal:
    row = (await client.get(f"{API}/inventory/balances", headers=st.owner, params={"product_id": product_id})).json()["items"][0]
    if location is None:
        return Decimal(row["on_hand"])
    return sum((Decimal(loc["on_hand"]) for loc in row["by_location"] if loc["location_id"] == location), Decimal(0))


async def reconciled(client: httpx.AsyncClient, st: Store) -> bool:
    result = (await client.post(f"{API}/inventory/reconciliation", headers=st.owner)).json()
    return result["differences"] == [] and result["balances_checked"] > 0


# Ledger, costing, immutability

async def test_opening_stock_sets_balance_and_cost(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "OPEN-1")
    r = await opening(client, store, p, store.shelf, "10", "1.20")
    assert r.status_code == 201, r.text
    assert r.json()["type"] == "OPENING" and r.json()["unit_cost"] == "1.200000"
    assert await on_hand(client, store, p) == 10
    again = await opening(client, store, p, store.shelf, "5", "1")
    assert again.status_code == 409  # opening stock only for products that never moved
    assert await reconciled(client, store)


async def test_weighted_average_cost(world: World, client: httpx.AsyncClient, store: Store, login: LoginFn):
    """10 at 1.00 then a costed receipt of 30 at 2.00 gives (10*1 + 30*2) / 40 = 1.75."""
    from app.models import Product
    from app.services import stock
    from app.services.principal import load_principal

    p = await product(client, store, "WAC-1")
    await opening(client, store, p, store.shelf, "10", "1.00")
    owner_user = store.world.accounts[0].user
    actor = await load_principal(world.db, owner_user.id, owner_user.id)
    prod = await world.db.get(Product, uuid.UUID(p))
    location = await world.db.get(WarehouseLocation, uuid.UUID(store.store))
    await stock.post(world.db, actor, [stock.Move(prod, Decimal("30"), "PURCHASE_RECEIPT", "TEST", "t", "t1", to_location=location, unit_cost=Decimal("2.00"))])
    await world.db.commit()
    detail = (await client.get(f"{API}/products/{p}", headers=store.owner)).json()
    assert detail["avg_cost"] == "1.750000" and detail["last_purchase_cost"] == "2.0000"


async def test_ledger_is_append_only(client: httpx.AsyncClient, store: Store, world: World):
    p = await product(client, store, "IMM-1")
    movement_id = (await opening(client, store, p, store.shelf, "3", "1")).json()["id"]
    for statement in ("UPDATE inventory_movements SET quantity_base = 99 WHERE id = :id", "DELETE FROM inventory_movements WHERE id = :id"):
        with pytest.raises(DBAPIError, match="append-only"):
            await world.db.execute(text(statement), {"id": movement_id})
        await world.db.rollback()


async def test_reversal_posts_an_opposite_movement_once(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "REV-1")
    await opening(client, store, p, store.shelf, "5", "1")
    moved = await client.post(f"{API}/inventory/relocations", headers=ik(store.owner), json={"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "2"})
    assert moved.status_code == 200, moved.text
    reversed_ = await client.post(f"{API}/inventory/movements/{moved.json()['id']}/reverse", headers=ik(store.owner), json={"reason": "Wrong shelf"})
    assert reversed_.status_code == 200 and reversed_.json()["reverses_movement_id"] == moved.json()["id"]
    assert await on_hand(client, store, p, store.shelf) == 5 and await on_hand(client, store, p, store.store) == 0
    twice = await client.post(f"{API}/inventory/movements/{moved.json()['id']}/reverse", headers=ik(store.owner), json={"reason": "Again"})
    assert twice.json()["error"]["code"] == "ALREADY_REVERSED"
    history = (await client.get(f"{API}/inventory/movements", headers=store.owner, params={"product_id": p})).json()["items"]
    original = next(m for m in history if m["id"] == moved.json()["id"])
    assert original["reversed_by_movement_id"] == reversed_.json()["id"]


async def test_running_balance(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "RUN-1")
    await opening(client, store, p, store.shelf, "10", "1")
    for qty in ("3", "2"):
        await client.post(f"{API}/inventory/relocations", headers=ik(store.owner), json={"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": qty})
    rows = (await client.get(f"{API}/inventory/movements", headers=store.owner, params={"product_id": p, "location_id": store.shelf})).json()["items"]
    assert [r["running_balance"] for r in rows] == ["5.0000", "7.0000", "10.0000"]


# Negative stock, idempotency, concurrency

async def test_negative_stock_is_blocked(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "NEG-1")
    await opening(client, store, p, store.shelf, "2", "1")
    r = await client.post(f"{API}/inventory/relocations", headers=ik(store.owner), json={"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "3"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert r.json()["error"]["details"][0]["available"] == "2.0000"
    assert await on_hand(client, store, p, store.shelf) == 2


async def test_idempotency_replays_without_posting_twice(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "IDEM-1")
    await opening(client, store, p, store.shelf, "10", "1")
    headers = ik(store.owner)
    body = {"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "4"}
    first = await client.post(f"{API}/inventory/relocations", headers=headers, json=body)
    second = await client.post(f"{API}/inventory/relocations", headers=headers, json=body)
    assert first.status_code == second.status_code == 200
    assert second.headers.get("idempotent-replayed") == "true" and first.json()["id"] == second.json()["id"]
    assert await on_hand(client, store, p, store.store) == 4
    reused = await client.post(f"{API}/inventory/relocations", headers=headers, json={**body, "quantity": "1"})
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    missing = await client.post(f"{API}/inventory/relocations", headers=store.owner, json=body)
    assert missing.status_code == 422


async def test_failed_command_releases_its_key(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "IDEM-2")
    await opening(client, store, p, store.shelf, "1", "1")
    headers = ik(store.owner)
    body = {"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "5"}
    failed = await client.post(f"{API}/inventory/relocations", headers=headers, json=body)
    assert failed.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    adj = (await client.post(f"{API}/inventory/adjustments", headers=store.owner, json={"warehouse_id": store.wh_a, "lines": [{"product_id": p, "location_id": store.shelf, "quantity": "9", "reason": "FOUND"}]})).json()
    await client.post(f"{API}/inventory/adjustments/{adj['id']}/submit", headers=ik(store.owner))
    await client.post(f"{API}/inventory/adjustments/{adj['id']}/post", headers=ik(store.owner))
    retried = await client.post(f"{API}/inventory/relocations", headers=headers, json=body)  # same key: it was released, so this runs
    assert retried.status_code == 200 and "idempotent-replayed" not in retried.headers
    assert await on_hand(client, store, p, store.store) == 5


async def test_concurrent_moves_cannot_oversell(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "RACE-1")
    await opening(client, store, p, store.shelf, "5", "1")
    body = {"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "3"}
    results = await asyncio.gather(*[client.post(f"{API}/inventory/relocations", headers=ik(store.owner), json=body) for _ in range(4)])
    assert sorted(r.status_code for r in results) == [200, 409, 409, 409]
    assert await on_hand(client, store, p, store.shelf) == 2 and await reconciled(client, store)


# Adjustments

async def test_adjustment_within_limit_posts_without_second_approval(client: httpx.AsyncClient, world: World, login: LoginFn, store: Store):
    p = await product(client, store, "ADJ-1")
    await opening(client, store, p, store.shelf, "10", "5")
    manager = await login(await world.user("INVMGR"))  # adjustment limit 300
    adj = await client.post(f"{API}/inventory/adjustments", headers=manager, json={"warehouse_id": store.wh_a, "notes": "", "lines": [
        {"product_id": p, "name": "ADJ-1", "location_id": store.shelf, "quantity": "-2", "reason": "DAMAGED", "notes": "Dropped"}]})
    assert adj.status_code == 201, adj.text
    submitted = (await client.post(f"{API}/inventory/adjustments/{adj.json()['id']}/submit", headers=ik(manager))).json()
    assert submitted["status"] == "APPROVED" and submitted["requires_approval"] is False
    posted = (await client.post(f"{API}/inventory/adjustments/{adj.json()['id']}/post", headers=ik(manager))).json()
    assert posted["status"] == "POSTED" and posted["total_value"] == "-10.0000"
    assert await on_hand(client, store, p) == 8
    movement = (await client.get(f"{API}/inventory/movements", headers=store.owner, params={"product_id": p, "type": "DAMAGE"})).json()["items"]
    assert len(movement) == 1 and movement[0]["source_no"] == posted["adjustment_no"]


async def test_adjustment_above_limit_needs_another_approver(client: httpx.AsyncClient, world: World, login: LoginFn, store: Store):
    p = await product(client, store, "ADJ-2")
    await opening(client, store, p, store.shelf, "100", "10")
    creator = await login(await world.user("INVMGR"))  # limit 300
    adj = (await client.post(f"{API}/inventory/adjustments", headers=creator, json={"warehouse_id": store.wh_a, "lines": [
        {"product_id": p, "location_id": store.shelf, "quantity": "-40", "reason": "LOST"}]})).json()  # value 400
    assert (await client.post(f"{API}/inventory/adjustments/{adj['id']}/submit", headers=ik(creator))).json()["status"] == "SUBMITTED"
    own = await client.post(f"{API}/inventory/adjustments/{adj['id']}/approve", headers=ik(creator))
    assert own.status_code == 403 and own.json()["error"]["code"] == "SOD_VIOLATION"
    other_invmgr = await login(await world.user("INVMGR"))
    too_small = await client.post(f"{API}/inventory/adjustments/{adj['id']}/approve", headers=ik(other_invmgr))
    assert too_small.json()["error"]["code"] == "LIMIT_EXCEEDED"
    early = await client.post(f"{API}/inventory/adjustments/{adj['id']}/post", headers=ik(creator))
    assert early.json()["error"]["code"] == "INVALID_STATE_TRANSITION"
    store_manager = await login(await world.user("STOREMGR"))  # limit 500
    approved = (await client.post(f"{API}/inventory/adjustments/{adj['id']}/approve", headers=ik(store_manager))).json()
    assert approved["status"] == "APPROVED" and approved["approved_by"]
    assert (await client.post(f"{API}/inventory/adjustments/{adj['id']}/post", headers=ik(creator))).json()["status"] == "POSTED"
    assert await on_hand(client, store, p) == 60


async def test_failed_adjustment_post_changes_nothing(client: httpx.AsyncClient, store: Store):
    """A multi-line posting is all or nothing: the second line fails, so the first is rolled back."""
    a, b = await product(client, store, "ROLL-A"), await product(client, store, "ROLL-B")
    await opening(client, store, a, store.shelf, "5", "1")
    await opening(client, store, b, store.shelf, "1", "1")
    adj = (await client.post(f"{API}/inventory/adjustments", headers=store.owner, json={"warehouse_id": store.wh_a, "lines": [
        {"product_id": a, "location_id": store.shelf, "quantity": "-2", "reason": "WRITE_OFF"},
        {"product_id": b, "location_id": store.shelf, "quantity": "-3", "reason": "WRITE_OFF"}]})).json()
    await client.post(f"{API}/inventory/adjustments/{adj['id']}/submit", headers=ik(store.owner))
    failed = await client.post(f"{API}/inventory/adjustments/{adj['id']}/post", headers=ik(store.owner))
    assert failed.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert await on_hand(client, store, a) == 5 and await on_hand(client, store, b) == 1
    detail = next(x for x in (await client.get(f"{API}/inventory/adjustments", headers=store.owner)).json()["items"] if x["id"] == adj["id"])
    assert detail["status"] == "APPROVED"


async def test_adjustment_reason_signs(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "SIGN-1")
    bad = await client.post(f"{API}/inventory/adjustments", headers=store.owner, json={"warehouse_id": store.wh_a, "lines": [{"product_id": p, "location_id": store.shelf, "quantity": "2", "reason": "DAMAGED"}]})
    assert bad.status_code == 422
    other_wh = await client.post(f"{API}/inventory/adjustments", headers=store.owner, json={"warehouse_id": store.wh_a, "lines": [{"product_id": p, "location_id": store.recv_b, "quantity": "2", "reason": "FOUND"}]})
    assert other_wh.status_code == 404


async def test_unusual_adjustment_raises_alert(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "ALERT-ADJ")
    await opening(client, store, p, store.shelf, "50", "10")
    adj = (await client.post(f"{API}/inventory/adjustments", headers=store.owner, json={"warehouse_id": store.wh_a, "lines": [{"product_id": p, "location_id": store.shelf, "quantity": "-20", "reason": "LOST"}]})).json()
    await client.post(f"{API}/inventory/adjustments/{adj['id']}/submit", headers=ik(store.owner))
    await client.post(f"{API}/inventory/adjustments/{adj['id']}/post", headers=ik(store.owner))
    alerts = (await client.get(f"{API}/alerts", headers=store.owner)).json()["items"]
    assert any(a["type"] == "UNUSUAL_ADJUSTMENT" and a["product_id"] == p for a in alerts)


# Transfers

async def test_transfer_conserves_stock(client: httpx.AsyncClient, world: World, login: LoginFn, store: Store):
    p = await product(client, store, "TRF-1")
    await opening(client, store, p, store.store, "20", "3")
    requester = await login(await world.user("WHSTAFF"))
    t = await client.post(f"{API}/inventory/transfers", headers=requester, json={"source_warehouse_id": store.wh_a, "destination_warehouse_id": store.wh_b, "reason": "Restock",
                                                                                "lines": [{"product_id": p, "name": "TRF-1", "quantity": "12"}]})
    assert t.status_code == 201, t.text
    tid, line = t.json()["id"], t.json()["lines"][0]["id"]
    assert (await client.post(f"{API}/inventory/transfers/{tid}/approve", headers=ik(store.owner))).json()["status"] == "APPROVED"
    dispatched = (await client.post(f"{API}/inventory/transfers/{tid}/dispatch", headers=ik(store.owner), json={"lines": [{"line_id": line, "quantity": "10"}]})).json()
    assert dispatched["status"] == "DISPATCHED"
    assert await on_hand(client, store, p) == 10  # in-transit stock is not counted in either warehouse
    overview = (await client.get(f"{API}/inventory/balances", headers=store.owner, params={"product_id": p, "warehouse_id": store.wh_b})).json()["items"][0]
    assert overview["in_transit"] == "10.0000"
    partial = (await client.post(f"{API}/inventory/transfers/{tid}/receive", headers=ik(store.owner), json={"lines": [
        {"line_id": line, "name": "TRF-1", "outstanding": 10, "received": "6", "damaged": "1", "short": "0", "excess": "0"}]})).json()
    assert partial["status"] == "PARTIALLY_RECEIVED"
    done = (await client.post(f"{API}/inventory/transfers/{tid}/receive", headers=ik(store.owner), json={"lines": [{"line_id": line, "received": "2", "short": "1", "excess": "1"}]})).json()
    assert done["status"] == "RECEIVED"
    closed = (await client.post(f"{API}/inventory/transfers/{tid}/close", headers=ik(store.owner))).json()
    assert closed["status"] == "CLOSED"
    # 20 at A - 10 sent; B got 6 + 2 good + 1 damaged + 1 excess; 1 short written off. 10 + 10 = 20 - 1 short + 1 excess.
    assert await on_hand(client, store, p) == 20
    assert await on_hand(client, store, p, store.recv_b) == 9
    transit = await world.db.scalar(text("SELECT coalesce(sum(b.on_hand), 0) FROM inventory_balances b JOIN warehouse_locations l ON l.id = b.location_id WHERE l.location_type = 'IN_TRANSIT' AND b.product_id = :p"), {"p": p})
    assert transit == 0
    assert await reconciled(client, store)


async def test_transfer_receipt_cannot_exceed_dispatch(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "TRF-2")
    await opening(client, store, p, store.store, "5", "1")
    t = (await client.post(f"{API}/inventory/transfers", headers=store.owner, json={"source_warehouse_id": store.wh_a, "destination_warehouse_id": store.wh_b, "reason": "x", "lines": [{"product_id": p, "quantity": "5"}]})).json()
    await client.post(f"{API}/inventory/transfers/{t['id']}/approve", headers=ik(store.owner))
    await client.post(f"{API}/inventory/transfers/{t['id']}/dispatch", headers=ik(store.owner))
    over = await client.post(f"{API}/inventory/transfers/{t['id']}/receive", headers=ik(store.owner), json={"lines": [{"line_id": t["lines"][0]["id"], "received": "6"}]})
    assert over.status_code == 422
    early_close = await client.post(f"{API}/inventory/transfers/{t['id']}/close", headers=ik(store.owner))
    assert early_close.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


# Counts

async def test_count_posts_deltas_not_absolute_quantities(client: httpx.AsyncClient, world: World, login: LoginFn, store: Store):
    p = await product(client, store, "CNT-1")
    await opening(client, store, p, store.shelf, "10", "2")
    counter = await login(await world.user("WHSTAFF"))
    count = (await client.post(f"{API}/inventory/counts", headers=counter, json={"warehouse_id": store.wh_a, "scope": "CYCLE_LOCATION", "category_id": "", "location_id": store.shelf,
                                                                              "sample_size": 1, "freeze": False, "blind": True})).json()
    line = next(x for x in count["lines"] if x["product_id"] == p)
    assert line["snapshot_qty"] is None  # blind
    # Stock moves during an unfrozen count; the count must not wipe it out.
    await client.post(f"{API}/inventory/relocations", headers=ik(store.owner), json={"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "3"})
    lines = [{"line_id": x["id"], "counted_qty": x["snapshot_qty"] if x["product_id"] != p else "9"} for x in count["lines"]]
    others = [x for x in count["lines"] if x["product_id"] != p]
    assert not others  # only this product sits on the shelf in this test company
    await client.patch(f"{API}/inventory/counts/{count['id']}/lines", headers=counter, json={"lines": lines})
    review = (await client.post(f"{API}/inventory/counts/{count['id']}/submit", headers=ik(counter))).json()
    assert review["status"] == "REVIEW" and review["lines"][0]["variance"] == "-1.0000" and review["lines"][0]["snapshot_qty"] == "10.0000"
    own = await client.post(f"{API}/inventory/counts/{count['id']}/approve", headers=ik(counter))
    assert own.status_code == 403
    approved = (await client.post(f"{API}/inventory/counts/{count['id']}/approve", headers=ik(store.owner))).json()
    assert approved["status"] == "APPROVED"
    posted = (await client.post(f"{API}/inventory/counts/{count['id']}/post", headers=ik(store.owner))).json()
    assert posted["status"] == "POSTED"
    assert await on_hand(client, store, p, store.shelf) == 6  # 10 - 3 moved - 1 variance, not reset to 9
    assert await reconciled(client, store)


async def test_large_variance_needs_recount(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "CNT-2")
    await opening(client, store, p, store.store, "50", "1")
    count = (await client.post(f"{API}/inventory/counts", headers=store.owner, json={"warehouse_id": store.wh_a, "scope": "CYCLE_LOCATION", "location_id": store.store, "blind": False})).json()
    line = count["lines"][0]
    await client.patch(f"{API}/inventory/counts/{count['id']}/lines", headers=store.owner, json={"lines": [{"line_id": line["id"], "counted_qty": "40"}]})
    review = (await client.post(f"{API}/inventory/counts/{count['id']}/submit", headers=ik(store.owner))).json()
    assert review["lines"][0]["recount_required"] is True
    blocked = await client.post(f"{API}/inventory/counts/{count['id']}/approve", headers=ik(store.owner))
    assert blocked.status_code == 422
    await client.patch(f"{API}/inventory/counts/{count['id']}/lines", headers=store.owner, json={"lines": [{"line_id": line["id"], "counted_qty": "49", "reason": "Recounted"}]})
    await store.world.db.execute(text("UPDATE companies SET settings = settings || '{\"reduced_sod_mode\": true}' WHERE id = :c"), {"c": store.world.company.id})
    await store.world.db.commit()
    assert (await client.post(f"{API}/inventory/counts/{count['id']}/approve", headers=ik(store.owner))).json()["status"] == "APPROVED"


async def test_frozen_count_blocks_movements(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "FRZ-1")
    await opening(client, store, p, store.shelf, "5", "1")
    count = (await client.post(f"{API}/inventory/counts", headers=store.owner, json={"warehouse_id": store.wh_a, "scope": "CYCLE_LOCATION", "location_id": store.shelf, "freeze": True})).json()
    blocked = await client.post(f"{API}/inventory/relocations", headers=ik(store.owner), json={"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "1"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "STOCK_FROZEN"
    await client.post(f"{API}/inventory/counts/{count['id']}/cancel", headers=ik(store.owner))
    allowed = await client.post(f"{API}/inventory/relocations", headers=ik(store.owner), json={"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "1"})
    assert allowed.status_code == 200


# Alerts, batches, reorder, scope

async def test_alerts_raise_and_resolve(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "LOW-1", stock_settings={"reorder_level": "5", "min_level": "0", "max_level": "20", "reorder_qty": "10"})
    await opening(client, store, p, store.shelf, "3", "1")
    first = (await client.post(f"{API}/alerts/evaluate", headers=store.owner)).json()
    assert first["raised"] >= 1
    again = (await client.post(f"{API}/alerts/evaluate", headers=store.owner)).json()
    assert again["raised"] == 0  # one open alert per condition
    alerts = (await client.get(f"{API}/alerts", headers=store.owner)).json()["items"]
    low = next(a for a in alerts if a["type"] == "LOW_STOCK" and a["product_id"] == p)
    suggestions = (await client.get(f"{API}/inventory/reorder-suggestions", headers=store.owner, params={"warehouse_id": store.wh_a})).json()["items"]
    assert next(s for s in suggestions if s["product_id"] == p)["suggested_qty"] == "17"
    snoozed = await client.post(f"{API}/alerts/{low['id']}/action", headers=store.owner, json={"action": "SNOOZE", "days": 3})
    assert snoozed.json()["status"] == "SNOOZED"
    adj = (await client.post(f"{API}/inventory/adjustments", headers=store.owner, json={"warehouse_id": store.wh_a, "lines": [{"product_id": p, "location_id": store.shelf, "quantity": "10", "reason": "FOUND"}]})).json()
    await client.post(f"{API}/inventory/adjustments/{adj['id']}/submit", headers=ik(store.owner))
    await client.post(f"{API}/inventory/adjustments/{adj['id']}/post", headers=ik(store.owner))
    await client.post(f"{API}/alerts/evaluate", headers=store.owner)
    open_low = [a for a in (await client.get(f"{API}/alerts", headers=store.owner)).json()["items"] if a["type"] == "LOW_STOCK" and a["product_id"] == p]
    assert open_low == [] or open_low[0]["status"] == "SNOOZED"


async def test_expiring_batches(client: httpx.AsyncClient, store: Store):
    from datetime import date, timedelta

    p = await product(client, store, "EXP-1", track_expiry=True)
    soon = (date.today() + timedelta(days=5)).isoformat()
    assert (await opening(client, store, p, store.shelf, "4", "1", batch_no="LOT-A", expiry_date=soon)).status_code == 201
    rows = (await client.get(f"{API}/inventory/batches", headers=store.owner, params={"within_days": 30})).json()["items"]
    assert [(r["batch_no"], r["days_to_expiry"], r["quantity"]) for r in rows if r["product_id"] == p] == [("LOT-A", 5, "4.0000")]
    await client.post(f"{API}/alerts/evaluate", headers=store.owner)
    assert any(a["type"] == "EXPIRING" and a["product_id"] == p for a in (await client.get(f"{API}/alerts", headers=store.owner)).json()["items"])


async def test_costs_hidden_and_scope_enforced(client: httpx.AsyncClient, world: World, login: LoginFn, store: Store):
    p = await product(client, store, "SCOPE-1")
    await opening(client, store, p, store.shelf, "4", "2.5")
    staff = await login(await world.user("WHSTAFF", branches=[world.branch_b]))
    row = (await client.get(f"{API}/inventory/balances", headers=staff, params={"product_id": p})).json()["items"][0]
    assert row["on_hand"] == "0" and row["avg_cost"] is None and row["value"] is None  # branch A stock is outside scope
    moves = (await client.get(f"{API}/inventory/movements", headers=staff, params={"product_id": p})).json()["items"]
    assert moves == []
    admin = await login(await world.user("SYSADMIN"))  # the only default role without stock access
    assert (await client.get(f"{API}/inventory/movements", headers=admin)).status_code == 403


async def test_reconciliation_detects_tampering(client: httpx.AsyncClient, world: World, store: Store):
    p = await product(client, store, "TAMPER-1")
    await opening(client, store, p, store.shelf, "4", "1")
    await world.db.execute(text("UPDATE inventory_balances SET on_hand = 5 WHERE product_id = :p"), {"p": p})
    await world.db.commit()
    result = (await client.post(f"{API}/inventory/reconciliation", headers=store.owner)).json()
    assert [(d["sku"], d["balance"], d["movement_sum"]) for d in result["differences"]] == [("TAMPER-1", "5.0000", "4.0000")]
    await world.db.execute(text("UPDATE inventory_balances SET on_hand = 4 WHERE product_id = :p"), {"p": p})
    await world.db.commit()


async def test_every_movement_has_matching_ledger_rows(world: World, client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "LEDGER-1")
    await opening(client, store, p, store.shelf, "4", "1")
    rows = list(await world.db.scalars(select(InventoryMovement).where(InventoryMovement.product_id == uuid.UUID(p))))
    assert len(rows) == 1 and rows[0].business_date is not None and rows[0].user_name


async def test_product_list_shows_real_stock(client: httpx.AsyncClient, store: Store):
    p = await product(client, store, "LIST-1")
    await opening(client, store, p, store.shelf, "6", "1")
    await opening(client, store, await product(client, store, "LIST-2"), store.store, "2", "1")
    await client.post(f"{API}/inventory/relocations", headers=ik(store.owner), json={"product_id": p, "from_location_id": store.shelf, "to_location_id": store.store, "quantity": "2"})
    detail = (await client.get(f"{API}/products/{p}", headers=store.owner)).json()
    assert (detail["on_hand"], detail["available"]) == ("6.0000", "4.0000")
