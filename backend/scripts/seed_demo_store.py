r"""Builds a DEMO database with about two months of realistic trading, to see the frontend as a live shop.

Run:  .venv\Scripts\python.exe -m scripts.seed_demo_store             (database pims_demo_store)
      .venv\Scripts\python.exe -m scripts.seed_demo_store pims_demo_x  (any name containing "demo")
Then: $env:DB_NAME="pims_demo_store"; .venv\Scripts\python.exe -m app.serve

How it works
- Refuses DB_NAME and any database without "demo" in its name; never touches an existing company.
- Every business record goes through the real API in-process (the same routes the frontend calls), so
  pricing, tax, stock movements, costing, approvals, separation of duties and numbering all apply.
- A simulated clock walks day by day through the last DAYS days: the services read that clock, and
  rows written by the seeding run get it as their created/posted time. Nothing is edited afterwards
  and the ledger stays append-only. Sign-in sessions and the audit log keep real times.
- Users are the same as scripts.seed_demo (plus a second cashier). They share one password: the one
  in backend/.demo-credentials when present, else DEMO_PASSWORD, else a generated one written there.
- All names are clearly sample data ("Demo Mart", "(demo)" suppliers, demo.invalid emails).
"""

import asyncio
import base64
import importlib
import logging
import math
import os
import random
import secrets
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import DateTime, func, select
from sqlalchemy import event as sa_event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.config import BACKEND_DIR
from app.core.runtime import use_selector_loop
from app.core.security import hash_secret, pin_lookup
from app.db import session as db_session
from app.models import Company, Role, User, UserBranchAccess, UserRole
from app.services.bootstrap import create_company
from scripts.seed import seed_reference_data
from scripts.seed_demo import USERS, ensure_database

API = "/api/v1"
TZ = ZoneInfo("Asia/Phnom_Penh")
DAYS = int(os.environ.get("DEMO_DAYS", "60"))
RATE = Decimal("4100")
rng = random.Random(20261112)
log = print

# Simulated clock

class Clock:
    at: datetime = datetime.now(UTC)
    active: bool = False


CLOCK = Clock()


class SimDateTime(datetime):
    """datetime whose now() follows the seeding clock; installed only in the business service modules."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        at = CLOCK.at if CLOCK.active else datetime.now(UTC)
        return at.astimezone(tz) if tz else at.astimezone(UTC).replace(tzinfo=None)


# Authentication, approvals and idempotency keep real time: tokens and PIN approvals must stay valid.
SIM_MODULES = ["sales", "stock", "cash_sessions", "purchasing", "returns", "inventory_docs", "expenses", "customers", "pricing", "promotions", "common", "alerts",
               "notifications", "products", "catalog", "org", "dashboard", "reports"]
REAL_TIME_TABLES = {"user_sessions", "login_attempts", "password_reset_tokens", "approvals", "idempotency_keys", "audit_logs"}
_ts_cache: dict[type, tuple[list[str], list[str]]] = {}


def _timestamp_columns(cls: type) -> tuple[list[str], list[str]]:
    if cls not in _ts_cache:
        mapper = sa_inspect(cls)
        created, updated = [], []
        if getattr(cls, "__tablename__", "") not in REAL_TIME_TABLES:
            for attr in mapper.column_attrs:
                col = attr.columns[0]
                if isinstance(col.type, DateTime) and col.server_default is not None:
                    created.append(attr.key)
                if isinstance(col.type, DateTime) and col.onupdate is not None:
                    updated.append(attr.key)
        _ts_cache[cls] = (created, updated)
    return _ts_cache[cls]


def _stamp(session: Session, _ctx, _instances) -> None:
    """Rows written while seeding get the simulated time instead of the database's now()."""
    if not CLOCK.active:
        return
    for obj in session.new:
        for key in _timestamp_columns(type(obj))[0]:
            if getattr(obj, key, None) is None:
                setattr(obj, key, CLOCK.at)
    for obj in session.dirty:
        if session.is_modified(obj):
            for key in _timestamp_columns(type(obj))[1]:
                setattr(obj, key, CLOCK.at)


def install_clock() -> None:
    for name in SIM_MODULES:
        module = importlib.import_module(f"app.services.{name}")
        if getattr(module, "datetime", None) is datetime:
            module.datetime = SimDateTime
    sa_event.listen(Session, "before_flush", _stamp)


def local(day, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(day, time(hh, mm), TZ).astimezone(UTC)


# Sample catalogue: sku, name, Khmer name, category, brand, price, cost, units per case, popularity, expiry-tracked

CATEGORIES = [("DRINK", "Drinks", "ភេសជ្ជៈ"), ("SNACK", "Snacks", "នំចំណី"), ("GROCERY", "Grocery", "គ្រឿងទេស"), ("FRESH", "Dairy and bakery", "ទឹកដោះគោ និងនំប៉័ង"),
              ("HOME", "Household", "គ្រឿងប្រើប្រាស់"), ("CARE", "Personal care", "ថែរក្សាខ្លួន")]
BRANDS = [("ANGKOR", "Angkor Beverages (demo)"), ("MEKONG", "Mekong Foods (demo)"), ("LOTUS", "Lotus Home (demo)"), ("SUNRISE", "Sunrise Dairy (demo)"), ("PURE", "Pure Care (demo)")]
SUPPLIERS = [("SUP-BEV", "Angkor Beverage Distribution (demo)", 2), ("SUP-FOOD", "Mekong Foods Wholesale (demo)", 3), ("SUP-FRESH", "Sunrise Dairy Co. (demo)", 1),
             ("SUP-HOME", "Lotus Home Supplies (demo)", 4), ("SUP-CARE", "Pure Care Trading (demo)", 5)]
SUPPLIER_OF = {"DRINK": "SUP-BEV", "SNACK": "SUP-FOOD", "GROCERY": "SUP-FOOD", "FRESH": "SUP-FRESH", "HOME": "SUP-HOME", "CARE": "SUP-CARE"}
PRODUCTS = [
    ("DRK-COLA-330", "Cola 330ml can", "កូកាកំប៉ុង", "DRINK", "ANGKOR", "0.75", "0.45", 24, 10, False),
    ("DRK-LEMON-330", "Lemon soda 330ml can", "ទឹកក្រូចឆ្មា", "DRINK", "ANGKOR", "0.70", "0.42", 24, 5, False),
    ("DRK-WATER-500", "Drinking water 500ml", "ទឹកសុទ្ធ ៥០០មល", "DRINK", "ANGKOR", "0.35", "0.15", 24, 14, False),
    ("DRK-WATER-1500", "Drinking water 1.5L", "ទឹកសុទ្ធ ១.៥លីត្រ", "DRINK", "ANGKOR", "0.80", "0.45", 12, 6, False),
    ("DRK-OJ-1L", "Orange juice 1L", "ទឹកក្រូច", "DRINK", None, "2.50", "1.60", 12, 3, False),
    ("DRK-COFFEE-CAN", "Iced coffee can", "កាហ្វេកំប៉ុង", "DRINK", None, "0.90", "0.55", 24, 6, False),
    ("DRK-GTEA-500", "Green tea 500ml", "តែបៃតង", "DRINK", None, "0.85", "0.50", 24, 5, False),
    ("DRK-ENERGY-250", "Energy drink 250ml", "ភេសជ្ជៈថាមពល", "DRINK", "ANGKOR", "0.80", "0.48", 24, 7, False),
    ("DRK-BEER-330", "Beer 330ml can", "ស្រាបៀរ", "DRINK", "ANGKOR", "0.90", "0.62", 24, 9, False),
    ("DRK-SOY-250", "Soy milk 250ml", "ទឹកសណ្ដែក", "DRINK", None, "0.50", "0.30", 24, 4, False),
    ("SNK-CHIPS-50", "Potato chips 50g", "ដំឡូងបារាំងចៀន", "SNACK", "MEKONG", "1.10", "0.65", 24, 5, False),
    ("SNK-CASSAVA", "Cassava chips 60g", "ដំឡូងមីចៀន", "SNACK", "MEKONG", "0.60", "0.33", 30, 4, False),
    ("SNK-CHOCO", "Chocolate bar 45g", "សូកូឡា", "SNACK", None, "1.00", "0.58", 24, 4, False),
    ("SNK-BISCUIT", "Butter biscuits 120g", "នំប៊ីស្គី", "SNACK", "MEKONG", "0.90", "0.52", 24, 4, False),
    ("SNK-PEANUT", "Roasted peanuts 100g", "សណ្ដែកដីលីង", "SNACK", "MEKONG", "0.70", "0.40", 30, 3, False),
    ("SNK-CUPCAKE", "Cup cake", "នំខេក", "SNACK", None, "0.40", "0.22", 24, 3, False),
    ("GRC-RICE-5KG", "Jasmine rice 5kg", "អង្ករផ្កាម្លិះ ៥គ.ក", "GROCERY", "MEKONG", "6.50", "4.80", 4, 4, False),
    ("GRC-NOODLE", "Instant noodles", "មីកញ្ចប់", "GROCERY", "MEKONG", "0.30", "0.18", 30, 12, False),
    ("GRC-OIL-1L", "Cooking oil 1L", "ប្រេងឆា", "GROCERY", None, "2.40", "1.75", 12, 4, False),
    ("GRC-FISHSAUCE", "Fish sauce 700ml", "ទឹកត្រី", "GROCERY", "MEKONG", "1.50", "0.95", 12, 3, False),
    ("GRC-SOYSAUCE", "Soy sauce 600ml", "ទឹកស៊ីអ៊ីវ", "GROCERY", None, "1.20", "0.75", 12, 2, False),
    ("GRC-SUGAR-1KG", "White sugar 1kg", "ស្ករស", "GROCERY", None, "1.10", "0.80", 10, 3, False),
    ("GRC-SALT", "Iodised salt 500g", "អំបិល", "GROCERY", None, "0.40", "0.22", 20, 2, False),
    ("GRC-SARDINE", "Canned sardines 155g", "ត្រីខកំប៉ុង", "GROCERY", None, "1.00", "0.62", 24, 3, False),
    ("GRC-EGG-10", "Eggs, pack of 10", "ពងមាន់", "GROCERY", None, "1.80", "1.30", 10, 5, False),
    ("GRC-COFFEE-3IN1", "3-in-1 coffee, box of 20", "កាហ្វេ ៣ក្នុង១", "GROCERY", None, "3.50", "2.40", 12, 3, False),
    ("GRC-CONDENSED", "Condensed milk 380g", "ទឹកដោះគោខាប់", "GROCERY", "SUNRISE", "1.20", "0.78", 24, 4, False),
    ("FRS-MILK-1L", "Fresh milk 1L", "ទឹកដោះគោស្រស់", "FRESH", "SUNRISE", "2.20", "1.50", 12, 5, True),
    ("FRS-YOGURT", "Yogurt cup 100g", "យ៉ាអួ", "FRESH", "SUNRISE", "0.60", "0.35", 24, 4, True),
    ("FRS-BREAD", "Sandwich bread loaf", "នំប៉័ង", "FRESH", None, "1.30", "0.80", 10, 5, False),
    ("HOM-DETERGENT", "Laundry detergent 1kg", "ម្សៅសាប៊ូ", "HOME", "LOTUS", "3.20", "2.20", 12, 2, False),
    ("HOM-DISHWASH", "Dishwashing liquid 500ml", "ទឹកលាងចាន", "HOME", "LOTUS", "1.40", "0.85", 12, 2, False),
    ("HOM-TISSUE-10", "Toilet paper, 10 rolls", "ក្រដាសអនាម័យ", "HOME", "LOTUS", "3.80", "2.70", 6, 2, False),
    ("HOM-SOAP", "Bath soap 90g", "សាប៊ូដុំ", "HOME", "LOTUS", "1.20", "0.70", 48, 3, False),
    ("HOM-TRASHBAG", "Trash bags, roll of 20", "ថង់សំរាម", "HOME", None, "1.50", "0.90", 20, 1, False),
    ("HOM-MOSQUITO", "Mosquito coils, box of 10", "ធូបដុតមូស", "HOME", None, "0.80", "0.45", 30, 2, False),
    ("CAR-SHAMPOO", "Shampoo 400ml", "សាប៊ូកក់សក់", "CARE", "PURE", "4.50", "3.10", 12, 2, False),
    ("CAR-TOOTHPASTE", "Toothpaste 150g", "ថ្នាំដុសធ្មេញ", "CARE", "PURE", "1.60", "1.00", 24, 2, False),
    ("CAR-TOOTHBRUSH", "Toothbrush", "ច្រាសដុសធ្មេញ", "CARE", "PURE", "0.90", "0.50", 24, 1, False),
    ("CAR-PADS", "Sanitary pads, pack of 10", "សំឡីអនាម័យ", "CARE", "PURE", "2.20", "1.50", 24, 1, False),
    ("CAR-LOTION", "Body lotion 200ml", "ឡេលាបខ្លួន", "CARE", "PURE", "3.90", "2.60", 12, 1, False),
    ("CAR-FACEWASH", "Face wash 100g", "ទឹកលាងមុខ", "CARE", "PURE", "3.20", "2.10", 12, 1, False),
]
FAVOURITES = {"DRK-COLA-330", "DRK-WATER-500", "DRK-BEER-330", "GRC-NOODLE", "GRC-EGG-10", "FRS-BREAD", "DRK-COFFEE-CAN", "SNK-CHIPS-50"}
FIRST = ["Sok", "Dara", "Sophea", "Vanna", "Chenda", "Rithy", "Bopha", "Kosal", "Malis", "Nary", "Visal", "Sreyneang", "Piseth", "Sokunthea", "Vibol", "Channary", "Ratha", "Sothea"]
LAST = ["Chan", "Kim", "Sok", "Heng", "Lim", "Meas", "Prak", "Ouk", "Seng", "Tep", "Yim", "Nhem"]
CASHIER2 = ("cashier2", "CASHIER", "Srey Mom Cashier")
PINS = {"cashier": "1593", "cashier2": "2580", "manager": "2468"}
PDF = "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n").decode()


def ean13(n: int) -> str:
    body = f"884{n:09d}"
    total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body))
    return body + str((10 - total % 10) % 10)


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), ROUND_HALF_UP))


# API access as each demo user

class SeedError(RuntimeError):
    pass


class Api:
    def __init__(self, client: httpx.AsyncClient, password: str):
        self.client, self.password, self.tokens = client, password, {}
        self.calls = 0
        self.last_error = ""

    async def _login(self, user: str) -> None:
        r = await self.client.post(f"{API}/auth/login", json={"username": user, "password": self.password})
        if r.status_code != 200:
            raise SeedError(f"login {user}: {r.status_code} {r.text}")
        self.tokens[user] = r.json()["access_token"]

    async def call(self, method: str, user: str, path: str, body=None, params=None, *, terminal: str | None = None, ik: bool = False, allow: tuple = ()):
        for attempt in (1, 2):
            if user not in self.tokens:
                await self._login(user)
            headers = {"Authorization": f"Bearer {self.tokens[user]}"}
            if terminal:
                headers["X-Terminal-Id"] = terminal
            if ik:
                headers["Idempotency-Key"] = f"seed-{uuid.uuid4()}"
            self.calls += 1
            r = await self.client.request(method, f"{API}/{path}", headers=headers, json=body, params=params)
            if r.status_code == 401 and attempt == 1:
                self.tokens.pop(user, None)  # the access token lasts 15 real minutes
                continue
            break
        if r.status_code in (200, 201, 204):
            return r.json() if r.content else {}
        if r.status_code in allow:
            self.last_error = f"{method} {path}: {r.status_code} {r.text[:300]}"
            return None
        raise SeedError(f"{method} {path} as {user}: {r.status_code} {r.text[:500]}")

    async def get(self, user, path, **params):
        return await self.call("GET", user, path, params=params or None)

    async def post(self, user, path, body=None, **kw):
        return await self.call("POST", user, path, body if body is not None else {}, **kw)

    async def patch(self, user, path, body, **kw):
        return await self.call("PATCH", user, path, body, **kw)


# Shop state kept by the seeder

@dataclass
class Item:
    sku: str
    id: str
    price: Decimal
    cost: Decimal
    case: int
    weight: int
    category: str
    expiry: bool
    supplier: str = ""


@dataclass
class Till:
    code: str
    terminal: str
    cashier: str
    branch: str
    warehouse: str
    shelf: str
    receiving: str
    sales_per_day: tuple[int, int]
    session: str | None = None
    today_sales: list = field(default_factory=list)


@dataclass
class Shop:
    api: Api
    items: list[Item] = field(default_factory=list)
    customers: list[str] = field(default_factory=list)
    suppliers: dict[str, str] = field(default_factory=dict)
    tills: list[Till] = field(default_factory=list)
    case_unit: str = ""
    expense_cats: dict[str, str] = field(default_factory=dict)
    open_pos: list[dict] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=lambda: {"sales": 0, "voids": 0, "returns": 0, "pos": 0, "grns": 0, "transfers": 0, "adjustments": 0, "expenses": 0, "skipped": 0})
    invoice_no: int = 1000

    def demand(self, item: Item, till: Till) -> float:
        total = sum(i.weight for i in self.items)
        lo, hi = till.sales_per_day
        return (lo + hi) / 2 * 3.6 * item.weight / total


async def setup_company(url: str, password: str) -> bool:
    db_session.configure_engine(url)
    async with db_session.session_factory()() as db:
        await seed_reference_data(db)
        await db.commit()
        if await db.scalar(select(func.count()).select_from(Company)):
            return False
        company = await create_company(db, legal_name="Demo Mart Co., Ltd. (sample data)", trading_name="Demo Mart")
        company.settings = {**company.settings, "store_credit_enabled": True, "loyalty_enabled": True}
        await db.flush()
        roles = {r.code: r for r in await db.scalars(select(Role).where(Role.company_id == company.id))}
        for username, role, name in [*USERS, CASHIER2]:
            pin = PINS.get(username)
            user = User(company_id=company.id, username=username, email=f"{username}@demo.invalid", full_name=name, password_hash=hash_secret(password),
                        pin_hash=hash_secret(pin) if pin else None, pin_lookup=pin_lookup(company.id, pin) if pin else None)
            db.add(user)
            await db.flush()
            db.add(UserRole(user_id=user.id, role_id=roles[role].id))
        await db.commit()
    return True


async def restrict_branches(branch_of: dict[str, str]) -> None:
    async with db_session.session_factory()() as db:
        for username, branch in branch_of.items():
            user = await db.scalar(select(User).where(User.username == username))
            db.add(UserBranchAccess(user_id=user.id, branch_id=uuid.UUID(branch)))
        await db.commit()


async def build_catalogue(shop: Shop, start) -> None:
    api = shop.api
    CLOCK.at = local(start, 8)
    await api.post("owner", "currencies/rates", {"rate": str(RATE)})
    tk = await api.post("owner", "branches", {"code": "TK", "name_en": "Toul Kork", "name_km": "ទួលគោក", "address": "St. 289, Toul Kork, Phnom Penh", "phone": "023 880 001",
                                               "open_time": "07:00", "close_time": "22:00"})
    bkk = await api.post("owner", "branches", {"code": "BKK", "name_en": "Boeung Keng Kang", "name_km": "បឹងកេងកង", "address": "St. 63, BKK1, Phnom Penh", "phone": "023 880 002",
                                                "open_time": "07:00", "close_time": "22:00"})
    vat = await api.post("owner", "tax-codes", {"code": "VAT10", "name": "VAT 10% (demo rate)", "rate": "10"})
    shop.case_unit = (await api.post("owner", "units", {"code": "CASE", "name_en": "Case", "name_km": "កេស"}))["id"]
    pcs = (await api.post("owner", "units", {"code": "PCS", "name_en": "Piece", "name_km": "ដុំ"}))["id"]
    warehouses = (await api.get("owner", "warehouses"))["items"]
    locations = (await api.get("owner", "locations"))["items"]
    place = {}
    for branch in (tk, bkk):
        wh = next(w for w in warehouses if w["branch_id"] == branch["id"])
        locs = [x for x in locations if x["warehouse_id"] == wh["id"]]
        place[branch["code"]] = (wh["id"], next(x["id"] for x in locs if x["type"] == "SELLABLE"), next((x["id"] for x in locs if x["type"] == "RECEIVING"), None))
    terminals = {}
    for branch, code, name in ((tk, "TK1", "Toul Kork Counter 1"), (tk, "TK2", "Toul Kork Counter 2"), (bkk, "BKK1", "BKK Counter 1")):
        terminals[code] = (await api.post("owner", "terminals", {"code": code, "name": name, "branch_id": branch["id"], "default_location_id": place[branch["code"]][1]}))["id"]
    await restrict_branches({"cashier": tk["id"], "sales": tk["id"], "branch": tk["id"], "cashier2": bkk["id"]})
    shop.tills = [Till("TK1", terminals["TK1"], "cashier", tk["id"], *place["TK"], sales_per_day=(18, 30)),
                  Till("BKK1", terminals["BKK1"], "cashier2", bkk["id"], *place["BKK"], sales_per_day=(8, 16))]

    cats = {code: (await api.post("owner", "categories", {"code": code, "name_en": name, "name_km": km, "default_tax_code_id": vat["id"]}))["id"] for code, name, km in CATEGORIES}
    brands = {code: (await api.post("owner", "brands", {"code": code, "name": name}))["id"] for code, name in BRANDS}
    for code, name, lead in SUPPLIERS:
        shop.suppliers[code] = (await api.post("purchasing", "suppliers", {"code": code, "name_en": name, "lead_time_days": lead, "payment_terms": "Net 30" if lead > 1 else "COD",
                                                                          "contacts": [{"name": f"{rng.choice(FIRST)} {rng.choice(LAST)}", "phone": f"0{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}"}]},
                                                 allow=(422,)) or await api.post("purchasing", "suppliers", {"code": code, "name_en": name, "lead_time_days": lead}))["id"]
    total_weight = sum(p[8] for p in PRODUCTS)
    for n, (sku, name, km, cat, brand, price, cost, case, weight, expiry) in enumerate(PRODUCTS, start=1):
        daily = 66 * weight / total_weight  # both branches, units per day
        supplier = shop.suppliers[SUPPLIER_OF[cat]]
        body = {"sku": sku, "name_en": name, "name_km": km, "category_id": cats[cat], "brand_id": brands.get(brand) if brand else None, "base_unit_id": pcs, "tax_code_id": vat["id"],
                "retail_price": price, "wholesale_price": money(Decimal(price) * Decimal("0.92")), "status": "ACTIVE", "track_expiry": expiry, "is_favourite": sku in FAVOURITES,
                "conversions": [{"unit_id": shop.case_unit, "factor": str(case), "is_purchase_default": True}],
                "barcodes": [{"barcode": ean13(n), "symbology": "EAN13", "unit_id": pcs}],
                "stock_settings": {"reorder_level": str(math.ceil(daily * 3)), "min_level": str(math.ceil(daily)), "max_level": str(math.ceil(daily * 12)), "reorder_qty": str(case * 2)},
                "suppliers": [{"supplier_id": supplier, "purchase_unit_id": shop.case_unit, "cost": money(Decimal(cost) * case), "lead_time_days": 2, "preferred": True}]}
        view = await api.post("owner", "products", body)
        shop.items.append(Item(sku, view["id"], Decimal(price), Decimal(cost), case, weight, cat, expiry, supplier))
    # A product that is set up but was never stocked, and one discontinued line, as in a real catalogue.
    await api.post("owner", "products", {"sku": "SNK-SEAWEED", "name_en": "Seaweed snack 10g", "category_id": cats["SNACK"], "base_unit_id": pcs, "tax_code_id": vat["id"], "retail_price": "0.80", "status": "DRAFT"})

    groups = {}
    for code, name, pct in (("WHOLESALE", "Wholesale buyers", "5"), ("VIP", "VIP members", "3"), ("STAFF", "Staff purchases", "10")):
        groups[code] = (await api.post("owner", "customer-groups", {"code": code, "name": name, "discount_pct": pct}))["id"]
    for i in range(28):
        group = "WHOLESALE" if i < 4 else "VIP" if i < 10 else None
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}" + (" Mini Mart (demo)" if group == "WHOLESALE" else " (demo)")
        body = {"name": name, "phone": f"0{rng.choice([12, 15, 17, 77, 89, 96])} {rng.randint(100, 999)} {rng.randint(100, 999)}", **({"group_id": groups[group]} if group else {})}
        shop.customers.append((await api.post("owner", "customers", body))["id"])
    for code, name in (("RENT", "Rent"), ("UTIL", "Utilities"), ("WAGES", "Casual wages"), ("TRANSPORT", "Transport and delivery"), ("REPAIR", "Repairs and maintenance"), ("SUPPLIES", "Store supplies")):
        shop.expense_cats[code] = (await api.post("owner", "expense-categories", {"code": code, "name": name}))["id"]
    log(f"catalogue: {len(shop.items)} products, {len(shop.customers)} customers, {len(shop.suppliers)} suppliers, 2 branches, 3 terminals")

    # Opening stock at go-live: everything arrives at Toul Kork; part of it is transferred to BKK on day two.
    tk_till = shop.tills[0]
    for item in shop.items:
        qty = math.ceil(sum(shop.demand(item, t) for t in shop.tills) * 10) + item.case
        body = {"product_id": item.id, "location_id": tk_till.shelf, "quantity": str(qty), "unit_cost": str(item.cost)}
        if item.expiry:
            body |= {"batch_no": f"OPEN-{item.sku[-6:]}", "expiry_date": (start + timedelta(days=40)).isoformat()}
        await api.post("inventory", "inventory/opening-balances", body, ik=True)


async def availability(shop: Shop, till: Till) -> dict[str, Decimal]:
    rows = (await shop.api.get(till.cashier, "products", sellable="true", terminal_id=till.terminal, limit=500))["items"]
    return {r["id"]: Decimal(r.get("available") or "0") for r in rows}


async def put_away(shop: Shop, warehouse: str, shelf: str, product_ids: list[str]) -> None:
    """Moves received stock from the receiving bay to the sales floor."""
    for pid in product_ids:
        rows = (await shop.api.get("inventory", "inventory/balances", product_id=pid, warehouse_id=warehouse))["items"]
        for row in rows:
            for loc in row.get("by_location", []):
                qty = Decimal(loc.get("on_hand") or "0")
                if loc["location_id"] != shelf and qty > 0 and loc.get("location_type", loc.get("type", "RECEIVING")) in ("RECEIVING", "STORAGE"):
                    await shop.api.post("warehouse", "inventory/relocations", {"product_id": pid, "from_location_id": loc["location_id"], "to_location_id": shelf,
                                                                                 "quantity": str(qty), "reason": "Put-away"}, ik=True, allow=(409, 422))


async def transfer(shop: Shop, source: Till, dest: Till, lines: list[tuple[Item, int]], reason: str, *, receive: bool = True) -> None:
    api = shop.api
    t = await api.post("inventory", "inventory/transfers", {"source_warehouse_id": source.warehouse, "destination_warehouse_id": dest.warehouse, "reason": reason,
                                                            "lines": [{"product_id": i.id, "quantity": str(q)} for i, q in lines]})
    await api.post("owner", f"inventory/transfers/{t['id']}/approve", ik=True)
    t = await api.post("warehouse", f"inventory/transfers/{t['id']}/dispatch", {"lines": [{"line_id": ln["id"], "quantity": ln["quantity"] if "quantity" in ln else str(q)}
                                                                                      for ln, (_, q) in zip(t["lines"], lines, strict=True)]}, ik=True)
    shop.stats["transfers"] += 1
    if not receive:
        return
    CLOCK.at += timedelta(hours=3)
    await api.post("warehouse", f"inventory/transfers/{t['id']}/receive", {"lines": [{"line_id": ln["id"], "received": str(q), "damaged": "0", "short": "0", "excess": "0"}
                                                                                    for ln, (_, q) in zip(t["lines"], lines, strict=True)]}, ik=True)
    await put_away(shop, dest.warehouse, dest.shelf, [i.id for i, _ in lines])


async def order_stock(shop: Shop, till: Till, day) -> None:
    """Weekly purchase orders per supplier for what is running low at this branch."""
    api = shop.api
    stock_now = await availability(shop, till)
    by_supplier: dict[str, list[tuple[Item, int]]] = {}
    for item in shop.items:
        daily = shop.demand(item, till)
        have = stock_now.get(item.id, Decimal(0))
        if have < Decimal(str(daily * 8)):
            cases = math.ceil(max(daily * 15 - float(have), item.case) / item.case)
            by_supplier.setdefault(item.supplier, []).append((item, cases))
    for supplier, lines in by_supplier.items():
        po = await api.post("purchasing", "purchase-orders", {"supplier_id": supplier, "warehouse_id": till.warehouse, "expected_date": (day + timedelta(days=2)).isoformat(),
                                                              "notes": f"Weekly order for {till.code[:-1]}",
                                                              "lines": [{"product_id": i.id, "unit_id": shop.case_unit, "quantity": str(c), "unit_cost": money(i.cost * i.case)} for i, c in lines]})
        await api.post("purchasing", f"purchase-orders/{po['id']}/submit", ik=True)
        approved = await api.post("manager", f"purchase-orders/{po['id']}/approve", ik=True)
        if approved["status"] != "APPROVED":
            await api.post("owner", f"purchase-orders/{po['id']}/approve", ik=True)
        po = await api.post("purchasing", f"purchase-orders/{po['id']}/send", ik=True)
        shop.open_pos.append({"po": po, "till": till, "due": day + timedelta(days=rng.choice([1, 2, 2, 3])), "lines": lines})
        shop.stats["pos"] += 1


async def receive_due(shop: Shop, day) -> None:
    api = shop.api
    for entry in [e for e in shop.open_pos if e["due"] <= day]:
        po, till = entry["po"], entry["till"]
        lines = []
        for pl, (item, cases) in zip(po["lines"], entry["lines"], strict=True):
            short = 1 if cases > 2 and rng.random() < 0.05 else 0
            damaged = 1 if rng.random() < 0.03 else 0
            line = {"po_line_id": pl["id"], "product_id": item.id, "unit_id": shop.case_unit, "quantity_received": str(cases - short - damaged), "quantity_damaged": str(damaged),
                    "quantity_rejected": "0", "unit_cost": money(item.cost * item.case), "batch_no": "", "expiry_date": ""}
            if item.expiry:
                line |= {"batch_no": f"B{day:%y%m%d}-{item.sku[-4:]}", "expiry_date": (day + timedelta(days=rng.choice([21, 28, 35]))).isoformat()}
            lines.append(line)
        body = {"po_id": po["id"], "supplier_id": "", "warehouse_id": "", "delivery_note": f"DN-{rng.randint(10000, 99999)}", "invoice_ref": "", "blind": False,
                "exception_reason": "Short or damaged on delivery" if any(ln["quantity_damaged"] != "0" or ln["quantity_received"] != str(c) for ln, (_, c) in zip(lines, entry["lines"], strict=True)) else "",
                "lines": lines}
        grn = await api.post("warehouse", "goods-receipts", body)
        posted = await api.post("warehouse", f"goods-receipts/{grn['id']}/post", ik=True, allow=(403, 409))
        if posted is None or posted.get("status") != "POSTED":
            await api.post("manager", f"goods-receipts/{grn['id']}/approve", ik=True, allow=(404, 409, 422))
            await api.post("warehouse", f"goods-receipts/{grn['id']}/post", ik=True)
        await put_away(shop, till.warehouse, till.shelf, [i.id for i, _ in entry["lines"]])
        shop.stats["grns"] += 1
        shop.open_pos.remove(entry)
        # The supplier's invoice follows; most are paid within the period.
        shop.invoice_no += 1
        total = (await api.get("purchasing", f"purchase-orders/{po['id']}"))["total"]
        inv = await api.post("purchasing", "supplier-invoices", {"invoice_no": f"INV-{shop.invoice_no}", "supplier_id": po["supplier_id"], "po_id": po["id"],
                                                                 "invoice_date": day.isoformat(), "due_date": (day + timedelta(days=30)).isoformat(), "amount": total}, allow=(409, 422))
        if inv and rng.random() < 0.7:
            await api.post("purchasing", f"supplier-invoices/{inv['id']}/payments", {"amount": inv.get("amount", total), "reference": f"ABA-{rng.randint(100000, 999999)}"}, allow=(409, 422))


async def open_session(shop: Shop, till: Till) -> None:
    opened = await shop.api.post(till.cashier, "cashier-sessions/open", {"opening": {"USD": "50", "KHR": "400000"}}, terminal=till.terminal, ik=True)
    till.session, till.today_sales = opened["id"], []


def _expected_from(summary: dict) -> dict:
    """Opening float + cash sales - cash refunds + cash in/out, per currency (what the drawer should hold)."""
    out = {k: Decimal(str(v)) for k, v in (summary["session"].get("opening") or {}).items()}
    for key, sign in (("cash_sales", 1), ("cash_refunds", -1)):
        for cur, v in (summary.get(key) or {}).items():
            out[cur] = out.get(cur, Decimal(0)) + sign * Decimal(str(v))
    for kind, amounts in (summary.get("movement_totals") or {}).items():
        sign = 1 if kind == "CASH_IN" else -1
        for cur, v in amounts.items():
            out[cur] = out.get(cur, Decimal(0)) + sign * Decimal(str(v))
    return {k: str(v) for k, v in out.items()}


async def close_session(shop: Shop, till: Till) -> None:
    api = shop.api
    summary = await api.get("owner", f"cashier-sessions/{till.session}/summary")
    expected = summary["session"].get("expected")
    if not expected:
        expected = _expected_from(summary)
        log(f"    {till.code}: expected cash worked out from the summary: {expected}")
    counted = {k: str(max(Decimal(str(v)), Decimal(0))) for k, v in expected.items()}
    roll = rng.random()
    if roll < 0.12:
        counted["USD"] = str(Decimal(counted["USD"]) - Decimal(rng.choice(["0.25", "0.50", "0.75"])))  # small, within tolerance
    elif roll < 0.15:
        counted["USD"] = str(Decimal(counted["USD"]) - Decimal(rng.choice(["2", "3.50", "5"])))  # needs a manager's review
    closed = await api.post(till.cashier, f"cashier-sessions/{till.session}/close", {"counted": counted}, terminal=till.terminal, ik=True)
    if closed.get("status") == "CLOSING":
        await api.post("manager", f"cashier-sessions/{till.session}/approve", {"reason": "Recounted with cashier; shortage confirmed"})
    till.session = None


def pick_lines(shop: Shop, stock_left: dict[str, Decimal]) -> list[tuple[Item, int]]:
    n = rng.choices([1, 2, 3, 4, 5, 6], weights=[24, 26, 20, 14, 9, 7])[0]
    chosen: dict[str, tuple[Item, int]] = {}
    for _ in range(n):
        item = rng.choices(shop.items, weights=[i.weight for i in shop.items])[0]
        qty = rng.choices([1, 2, 3, 6], weights=[62, 24, 9, 5])[0]
        have = stock_left.get(item.id, Decimal(0)) - (chosen[item.sku][1] if item.sku in chosen else 0)
        if have >= qty:
            chosen[item.sku] = (item, (chosen[item.sku][1] if item.sku in chosen else 0) + qty)
    return list(chosen.values())


async def one_sale(shop: Shop, till: Till, stock_left: dict[str, Decimal], *, finish: bool = True) -> dict | None:
    api = shop.api
    lines = pick_lines(shop, stock_left)
    if not lines:
        shop.stats["skipped"] += 1
        return None
    sale = await api.post(till.cashier, "sales", {}, terminal=till.terminal, ik=True)
    ops: list[dict] = [{"type": "add_product", "product_id": i.id, "quantity": str(q)} for i, q in lines]
    if rng.random() < 0.3:
        ops.append({"type": "set_customer", "customer_id": rng.choice(shop.customers)})
    sale = await api.patch(till.cashier, f"sales/{sale['id']}", {"ops": ops}, terminal=till.terminal)
    if rng.random() < 0.04 and sale["lines"] and not any(ln.get("promotion_id") for ln in sale["lines"]):
        sale = await api.patch(till.cashier, f"sales/{sale['id']}", {"ops": [{"type": "line_discount", "line_id": sale["lines"][0]["id"], "discount_type": "PERCENT", "value": "5",
                                                                               "reason": "Dented packaging"}]}, terminal=till.terminal, allow=(403,)) or sale
    if not finish:
        held = await api.patch(till.cashier, f"sales/{sale['id']}", {"ops": [{"type": "hold", "label": "Customer went to fetch cash"}]}, terminal=till.terminal)
        return held
    total = Decimal(sale["grand_total"])
    method = rng.choices(["CASH_USD", "CASH_KHR", "QR", "CARD"], weights=[46, 22, 24, 8])[0]
    if method == "CASH_USD":
        tender = next(x for x in (total, *(Decimal(v) for v in (1, 2, 5, 10, 20, 50, 100))) if x >= total and (x == total or rng.random() < 0.8)) if rng.random() < 0.15 else \
            next(Decimal(v) for v in (1, 2, 5, 10, 20, 50, 100) if Decimal(v) >= total)
        small_change = tender - total < 5 and rng.random() < 0.4  # riel change only for small amounts, as tills do
        pay = {"method": "CASH", "currency": "USD", "amount_tendered": money(tender), "change_currency": "KHR" if small_change else "USD"}
    elif method == "CASH_KHR":
        riel = (total * RATE / 1000).to_integral_value(ROUND_CEILING) * 1000
        pay = {"method": "CASH", "currency": "KHR", "amount_tendered": str(riel + (rng.choice([0, 0, 1000, 5000]) if riel > 5000 else 0)), "change_currency": "KHR"}
    elif method == "QR":
        pay = {"method": "QR", "currency": "USD", "amount_tendered": money(total), "reference": f"KHQR-{rng.randint(10**9, 10**10 - 1)}", "provider": "Bakong"}
    else:
        pay = {"method": "CARD", "currency": "USD", "amount_tendered": money(total), "approval_code": f"{rng.randint(100000, 999999)}", "card_last4": f"{rng.randint(0, 9999):04d}"}
    sale = await api.post(till.cashier, f"sales/{sale['id']}/payments", pay, terminal=till.terminal, ik=True)
    if Decimal(sale["balance"]) > 0:
        sale = await api.post(till.cashier, f"sales/{sale['id']}/payments", {"method": "CASH", "currency": "USD", "amount_tendered": money(Decimal(sale["balance"]))},
                              terminal=till.terminal, ik=True)
    done = await api.post(till.cashier, f"sales/{sale['id']}/finalize", terminal=till.terminal, ik=True, allow=(409, 422))
    if done is None:
        log(f"    finalize refused: {api.last_error}")
        token = (await api.post(till.cashier, "auth/approvals/verify", {"pin": PINS["manager"], "action": "CANCEL_SALE", "amount": sale["grand_total"]}, terminal=till.terminal))["token"]
        await api.post(till.cashier, f"sales/{sale['id']}/cancel", {"reason": "Payment problem", "approval_token": token}, terminal=till.terminal, ik=True, allow=(404, 409, 422))
        shop.stats["skipped"] += 1
        return None
    for item, qty in lines:
        stock_left[item.id] -= qty
    shop.stats["sales"] += 1
    till.today_sales.append(done)
    return done


async def void_sale(shop: Shop, till: Till, sale: dict) -> None:
    api = shop.api
    token = (await api.post(till.cashier, "auth/approvals/verify", {"pin": PINS["manager"], "action": "VOID_SALE", "amount": sale["grand_total"]}, terminal=till.terminal))["token"]
    if await api.post(till.cashier, f"sales/{sale['id']}/void", {"reason": "Rang up the wrong items", "approval_token": token}, terminal=till.terminal, ik=True, allow=(403, 409, 422)):
        shop.stats["voids"] += 1


async def return_items(shop: Shop, till: Till, sale: dict) -> None:
    line = sale["lines"][0]
    body = {"lines": [{"sale_line_id": line["id"], "quantity": "1", "condition": rng.choice(["RESALABLE", "RESALABLE", "DAMAGED"]), "reason": rng.choice(["Changed mind", "Wrong flavour", "Damaged packaging"])}],
            "refund_method": "CASH"}
    if await shop.api.post(till.cashier, f"sales/{sale['id']}/returns", body, terminal=till.terminal, ik=True, allow=(403, 409, 422)):
        shop.stats["returns"] += 1


async def expense(shop: Shop, till: Till, cat: str, description: str, amount: Decimal, day, method: str = "BANK_TRANSFER") -> None:
    body = {"date": day.isoformat(), "category_id": shop.expense_cats[cat], "description": description, "amount": money(amount), "currency": "USD", "payment_method": method, "branch_id": till.branch}
    if amount >= 100:
        body["attachment"] = PDF
    created = await shop.api.post("owner", "expenses", body)
    if created.get("status") == "SUBMITTED" and day < datetime.now(TZ).date() - timedelta(days=1):
        await shop.api.post("accountant", f"expenses/{created['id']}/approve", {})
    shop.stats["expenses"] += 1


async def adjust(shop: Shop, till: Till, item: Item, qty: int, reason: str, note: str) -> None:
    api = shop.api
    adj = await api.post("inventory", "inventory/adjustments", {"warehouse_id": till.warehouse, "notes": note,
                                                                "lines": [{"product_id": item.id, "location_id": till.shelf, "quantity": str(qty), "reason": reason, "notes": note}]}, allow=(409, 422))
    if not adj:
        return
    adj = await api.post("inventory", f"inventory/adjustments/{adj['id']}/submit", ik=True)
    if adj["status"] != "APPROVED":
        adj = await api.post("owner", f"inventory/adjustments/{adj['id']}/approve", ik=True)
    await api.post("inventory", f"inventory/adjustments/{adj['id']}/post", ik=True, allow=(409, 422))
    shop.stats["adjustments"] += 1


async def promotions(shop: Shop, start, today) -> None:
    api = shop.api
    by_sku = {i.sku: i for i in shop.items}
    for code, name, skus, pct, begin, end in (
        ("NEWYEAR-DRINKS", "Drinks 10% off (ended)", ["DRK-OJ-1L", "DRK-GTEA-500", "DRK-SOY-250"], "10", start + timedelta(days=8), start + timedelta(days=22)),
        ("SNACK-WEEK", "Snack week 15% off", ["SNK-CHIPS-50", "SNK-CASSAVA", "SNK-CHOCO"], "15", today - timedelta(days=10), today + timedelta(days=10)),
        ("CARE-NEXT", "Personal care 12% off (upcoming)", ["CAR-SHAMPOO", "CAR-LOTION"], "12", today + timedelta(days=5), today + timedelta(days=20)),
    ):
        CLOCK.at = local(min(begin, today) - timedelta(days=1), 9)
        promo = await api.post("owner", "promotions", {"code": code, "name": name, "type": "PRODUCT", "discount_pct": pct, "product_ids": [by_sku[s].id for s in skus],
                                                       "start_date": begin.isoformat(), "end_date": end.isoformat(), "priority": 1})
        await api.post("manager", f"promotions/{promo['id']}/approve", allow=(409, 422))
    await api.post("owner", "coupons", {"code": "WELCOME1", "description": "$1 off a spend of $10 (demo)", "discount_amount": "1", "min_spend": "10",
                                        "start_date": start.isoformat(), "end_date": (today + timedelta(days=30)).isoformat(), "usage_limit": 200}, allow=(409, 422))


async def trade(shop: Shop, start, today, now_local: datetime) -> None:
    api = shop.api
    tk, bkk = shop.tills
    item_by_sku = {i.sku: i for i in shop.items}
    # Day two: stock BKK from Toul Kork.
    day = start + timedelta(days=1)
    CLOCK.at = local(day, 6, 30)
    await transfer(shop, tk, bkk, [(i, math.ceil(shop.demand(i, bkk) * 10)) for i in shop.items], "Opening stock for BKK")

    day = start + timedelta(days=2)
    while day <= today:
        is_today = day == today
        weekend = day.weekday() >= 5
        CLOCK.at = local(day, 6, 45)
        await receive_due(shop, day)
        if day.weekday() == 0:
            CLOCK.at = local(day, 7, 15)
            for till in shop.tills:
                await order_stock(shop, till, day)
        if day == start + timedelta(days=30):
            CLOCK.at = local(day, 7, 20)  # supplier price rise
            for sku, price in (("DRK-COLA-330", "0.80"), ("GRC-OIL-1L", "2.60"), ("GRC-RICE-5KG", "6.80")):
                await api.patch("owner", f"products/{item_by_sku[sku].id}", {"retail_price": price}, allow=(403, 409, 422))
        if day.day == 1 or day == start + timedelta(days=2):
            CLOCK.at = local(day, 9)
            await expense(shop, tk, "RENT", "Shop rent, Toul Kork", Decimal("1200"), day)
            await expense(shop, bkk, "RENT", "Shop rent, BKK", Decimal("950"), day)
        if day.weekday() == 4:
            CLOCK.at = local(day, 16)
            await expense(shop, tk, "UTIL", "Electricity and water", Decimal(str(rng.randint(140, 220))), day)
            await expense(shop, bkk, "UTIL", "Electricity and water", Decimal(str(rng.randint(80, 140))), day)
            await expense(shop, tk, "WAGES", "Weekend helper", Decimal("45"), day, "CASH")
        if rng.random() < 0.12:
            CLOCK.at = local(day, 15)
            await expense(shop, rng.choice(shop.tills), rng.choice(["TRANSPORT", "REPAIR", "SUPPLIES"]), rng.choice(["Tuk-tuk delivery", "Fix freezer door", "Receipt paper rolls", "Cleaning supplies"]),
                          Decimal(str(rng.randint(8, 60))), day, "CASH")

        # Trading day: both tills open at 07:00 and close at 21:45.
        stocks = {}
        for till in shop.tills:
            CLOCK.at = local(day, 7)
            await open_session(shop, till)
            stocks[till.code] = await availability(shop, till)
        events = []
        for till in shop.tills:
            lo, hi = till.sales_per_day
            count = rng.randint(lo, hi) + (4 if weekend else 0)
            for _ in range(count):
                minute = int(rng.triangular(7 * 60 + 15, 21 * 60 + 30, 18 * 60))  # busier in the evening
                events.append((minute, till))
        events.sort(key=lambda e: e[0])
        for minute, till in events:
            at = local(day, minute // 60, minute % 60)
            if is_today and at > now_local.astimezone(UTC) - timedelta(minutes=5):
                break
            CLOCK.at = at
            done = await one_sale(shop, till, stocks[till.code])
            if done and rng.random() < 0.012:
                CLOCK.at += timedelta(minutes=2)
                await void_sale(shop, till, done)
            elif done and len(till.today_sales) > 3 and rng.random() < 0.02:
                CLOCK.at += timedelta(minutes=rng.randint(20, 90))
                await return_items(shop, till, rng.choice(till.today_sales[:-1]))
        if rng.random() < 0.15:
            till = rng.choice(shop.tills)
            CLOCK.at = local(day, 21, 50)
            victim = rng.choice([i for i in shop.items if not i.expiry])
            if stocks[till.code].get(victim.id, 0) > 2:
                await adjust(shop, till, victim, -1, "DAMAGED", rng.choice(["Dropped while shelving", "Leaking", "Crushed in delivery"]))
        if is_today:
            break
        for till in shop.tills:
            CLOCK.at = local(day, 21, 45)
            await close_session(shop, till)
        if day.toordinal() % 9 == 0:
            log(f"  {day}: {shop.stats['sales']} sales so far, {api.calls} API calls")
        day += timedelta(days=1)

    # Today: tills stay open, one sale is on hold, a PO waits for approval and a transfer is on the road.
    CLOCK.at = min(now_local.astimezone(UTC) - timedelta(minutes=3), local(today, 21))
    stock_tk = await availability(shop, tk)
    await one_sale(shop, tk, stock_tk, finish=False)
    po = await api.post("purchasing", "purchase-orders", {"supplier_id": shop.suppliers["SUP-CARE"], "warehouse_id": tk.warehouse, "expected_date": (today + timedelta(days=3)).isoformat(),
                                                          "notes": "Restock before the personal care promotion",
                                                          "lines": [{"product_id": item_by_sku[s].id, "unit_id": shop.case_unit, "quantity": "2", "unit_cost": money(item_by_sku[s].cost * item_by_sku[s].case)}
                                                                    for s in ("CAR-SHAMPOO", "CAR-LOTION")]})
    await api.post("purchasing", f"purchase-orders/{po['id']}/submit", ik=True)
    await api.post("purchasing", "purchase-orders", {"supplier_id": shop.suppliers["SUP-BEV"], "warehouse_id": bkk.warehouse, "expected_date": (today + timedelta(days=4)).isoformat(),
                                                     "notes": "Draft: check prices first",
                                                     "lines": [{"product_id": item_by_sku["DRK-BEER-330"].id, "unit_id": shop.case_unit, "quantity": "5", "unit_cost": money(item_by_sku["DRK-BEER-330"].cost * 24)}]})
    if stock_tk.get(item_by_sku["DRK-WATER-500"].id, 0) > 30:
        await transfer(shop, tk, bkk, [(item_by_sku["DRK-WATER-500"], 24)], "Weekend demand at BKK", receive=False)


async def seed_store(url: str, password: str) -> bool:
    install_clock()
    today = datetime.now(TZ).date()
    start = today - timedelta(days=DAYS)
    CLOCK.active, CLOCK.at = True, local(start - timedelta(days=2), 8)
    if not await setup_company(url, password):
        log("This database already has a company; nothing changed. Use a new database name to build again.")
        return False
    from app.main import create_app

    app = create_app()
    logging.disable(logging.WARNING)  # the in-process API would log every request
    shop = Shop(Api(httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)), base_url="http://seed", timeout=60), password))
    try:
        await build_catalogue(shop, start - timedelta(days=1))
        await promotions(shop, start, today)
        await trade(shop, start, today, datetime.now(TZ))
    finally:
        await shop.api.client.aclose()
        CLOCK.active = False
        logging.disable(logging.NOTSET)
    log("done: " + ", ".join(f"{v} {k}" for k, v in shop.stats.items()) + f" ({shop.api.calls} API calls)")
    await db_session.dispose_engine()
    return True


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "pims_demo_store"
    url = ensure_database(name)
    path = BACKEND_DIR / ".demo-credentials"
    existing = None
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Password for every demo user:"):
                existing = line.split(":", 1)[1].strip()
    password = existing or os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(12)
    if asyncio.run(seed_store(url, password)):
        lines = [f"Demo databases: pims_demo, {name}", f"Password for every demo user: {password}",
                 "PINs: cashier 1593 (Toul Kork), cashier2 2580 (BKK, store database only), manager 2468", "Users:"]
        lines += [f"  {u:<11} {r}" for u, r, _ in [*USERS, CASHIER2]]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log(f"Start the API with DB_NAME={name}. Credentials: {path} (git-ignored).")


if __name__ == "__main__":
    use_selector_loop()
    main()
