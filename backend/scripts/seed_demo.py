r"""Creates a separate DEMO database for trying the frontend against the real API.

Run:  .venv\Scripts\python.exe -m scripts.seed_demo            (database pims_demo)
      .venv\Scripts\python.exe -m scripts.seed_demo pims_demo2

- Refuses to touch DB_NAME (your development database) and anything that is not named *demo*.
- Creates the database if it is missing, migrates it, and seeds only when it has no company yet.
- One user per role with the frontend's demo usernames (owner, manager, cashier, ...). They share one
  password, taken from DEMO_PASSWORD or generated, written to backend/.demo-credentials (git-ignored).
- Everything is clearly demo data: company "Demo Mart (sample data)", tax code DEMO-VAT.
Then start the API on it:  $env:DB_NAME="pims_demo"; .venv\Scripts\python.exe -m app.serve
"""

import asyncio
import os
import secrets
import sys
from datetime import time
from decimal import Decimal

import psycopg
from psycopg import sql
from sqlalchemy import func, select

from alembic import command
from alembic.config import Config
from app.core.config import BACKEND_DIR, get_settings
from app.core.runtime import use_selector_loop
from app.core.security import hash_secret, pin_lookup
from app.db import session as db_session
from app.models import Company, Role, TaxCode, User, UserBranchAccess, UserRole, Warehouse, WarehouseLocation
from app.schemas import catalog as cs
from app.schemas import org as os_
from app.schemas import purchasing as ps
from app.services import catalog, customers, org, products, purchasing, stock
from app.services.bootstrap import create_company
from app.workers.run import system_principal
from scripts.seed import seed_reference_data

USERS = [("owner", "OWNER", "Sophea Owner"), ("manager", "STOREMGR", "Dara Store Manager"), ("branch", "BRMGR", "Vanna Branch Manager"), ("cashier", "CASHIER", "Sokha Cashier"),
         ("inventory", "INVMGR", "Rithy Inventory"), ("purchasing", "PUROFF", "Chenda Purchasing"), ("warehouse", "WHSTAFF", "Piseth Warehouse"), ("accountant", "ACCT", "Malis Accountant"),
         ("auditor", "AUDITOR", "Bopha Auditor"), ("admin", "SYSADMIN", "Kosal Admin"), ("sales", "SALES", "Nary Sales"), ("viewer", "READONLY", "Visal Viewer")]
PRODUCTS = [("COLA-330", "Cola 330ml", "កូកា", "DRINK", "0.75", "0.45", "8850000000010", 48), ("WATER-500", "Drinking water 500ml", "ទឹកសុទ្ធ", "DRINK", "0.35", "0.15", "8850000000027", 120),
            ("RICE-5KG", "Jasmine rice 5kg", "អង្ករ", "GROCERY", "6.50", "4.80", "8850000000034", 20), ("NOODLE", "Instant noodles", "មី", "GROCERY", "0.30", "0.18", "8850000000041", 200),
            ("SOAP", "Bath soap", "សាប៊ូ", "HOME", "1.20", "0.70", "8850000000058", 3)]


def ensure_database(name: str) -> str:
    settings = get_settings()
    if name == settings.db_name or "demo" not in name.lower():
        sys.exit(f"Refusing to use '{name}': the demo database must differ from DB_NAME and contain 'demo'.")
    if not settings.db_password.get_secret_value():
        sys.exit("DB_PASSWORD is empty in backend/.env.")
    info = psycopg.conninfo.make_conninfo(host=settings.db_host, port=settings.db_port, user=settings.db_user, password=settings.db_password.get_secret_value(), dbname="postgres")
    with psycopg.connect(info, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(name)))
            print(f"{name}: created")
    url = settings.url_for(name)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    return url


async def seed(url: str, password: str) -> bool:
    db_session.configure_engine(url)
    async with db_session.session_factory()() as db:
        await seed_reference_data(db)
        await db.commit()
        if await db.scalar(select(func.count()).select_from(Company)):
            print("Demo data already present; nothing changed.")
            return False
        company = await create_company(db, legal_name="Demo Mart Co., Ltd. (sample data)", trading_name="Demo Mart")
        company.settings = {**company.settings, "store_credit_enabled": True, "loyalty_enabled": True}
        await db.commit()
        actor = system_principal(company.id)
        await org.create_rate(db, actor, os_.ExchangeRateCreate.model_validate({"rate": "4100"}))
        tk = await org.create_branch(db, actor, os_.BranchCreate(code="TK", name_en="Toul Kork", name_km="ទួលគោក", open_time=time(7), close_time=time(22)))
        bkk = await org.create_branch(db, actor, os_.BranchCreate(code="BKK", name_en="BKK1", name_km="បឹងកេងកង"))
        vat = await org.create_record(db, actor, TaxCode, os_.TaxCodeCreate(code="DEMO-VAT", name="Demo VAT (confirm real rate)", rate=Decimal("10")), "tax_code")
        shelves = {}
        for branch in (tk, bkk):
            wh = await db.scalar(select(Warehouse).where(Warehouse.branch_id == branch.id))
            shelves[branch.code] = await db.scalar(select(WarehouseLocation).where(WarehouseLocation.warehouse_id == wh.id, WarehouseLocation.location_type == "SELLABLE"))
        terminals = {}
        for branch, code, name in ((tk, "TK1", "Toul Kork Counter 1"), (tk, "TK2", "Toul Kork Counter 2"), (bkk, "BKK1", "BKK1 Counter 1")):
            view = await org.create_terminal(db, actor, os_.TerminalCreate(code=code, name=name, branch_id=branch.id, default_location_id=shelves[branch.code].id))
            terminals[code] = view["id"]

        pcs = await catalog.create_unit(db, actor, cs.UnitCreate(code="PCS", name_en="Piece", name_km="ដុំ"))
        box = await catalog.create_unit(db, actor, cs.UnitCreate(code="BOX", name_en="Box", name_km="ប្រអប់"))
        cats = {}
        for code, name in (("DRINK", "Drinks"), ("GROCERY", "Grocery"), ("HOME", "Household")):
            cats[code] = await catalog.create_category(db, actor, cs.CategoryCreate(code=code, name_en=name, default_tax_code_id=vat.id))
        roles = {r.code: r for r in await db.scalars(select(Role).where(Role.company_id == company.id))}
        users = {}
        for username, role, name in USERS:
            pin = "1593" if role == "CASHIER" else ("2468" if role in ("STOREMGR", "BRMGR") and username == "manager" else None)
            user = User(company_id=company.id, username=username, email=f"{username}@demo.invalid", full_name=name, password_hash=hash_secret(password),
                        pin_hash=hash_secret(pin) if pin else None, pin_lookup=pin_lookup(company.id, pin) if pin else None)
            db.add(user)
            await db.flush()
            db.add(UserRole(user_id=user.id, role_id=roles[role].id))
            if role in ("CASHIER", "SALES", "BRMGR"):
                db.add(UserBranchAccess(user_id=user.id, branch_id=tk.id))
            users[username] = user
        await db.commit()
        supplier = await purchasing.create_supplier(db, actor, ps.SupplierCreate(code="MKF", name_en="Mekong Foods (demo)", lead_time_days=5))
        for sku, name, km, cat, price, cost, barcode, qty in PRODUCTS:
            view = await products.create_product(db, actor, cs.ProductCreate(
                sku=sku, name_en=name, name_km=km, category_id=cats[cat].id, base_unit_id=pcs.id, retail_price=Decimal(price), status="ACTIVE",
                conversions=[cs.ConversionIn(unit_id=box.id, factor=Decimal(12), is_purchase_default=True)],
                barcodes=[cs.BarcodeIn(barcode=barcode, symbology="EAN13", unit_id=pcs.id)],
                stock_settings=cs.StockSettingsIn(reorder_level=Decimal(10), max_level=Decimal(150), reorder_qty=Decimal(48)),
                suppliers=[cs.SupplierLinkIn(supplier_id=supplier["id"], purchase_unit_id=box.id, cost=Decimal(cost) * 12, preferred=True)],
            ))
            # Opening stock is a one-time go-live entry per product, so it goes to the Toul Kork shelf only.
            await stock.opening_balance(db, actor, product_id=view["id"], location_id=shelves["TK"].id, quantity=Decimal(qty), unit_cost=Decimal(cost),
                                        batch_no="", expiry_date=None, key=f"demo-{sku}")
        group = await customers.create_group(db, actor, ps.GroupCreate(code="WHOLESALE", name="Wholesale buyers", discount_pct=Decimal(5)))
        await customers.create_customer(db, actor, ps.CustomerCreate(name="Sok Dara (demo)", phone="012 345 678", group_id=group.id))
        await db.commit()
        print(f"Demo company created with {len(USERS)} users, {len(PRODUCTS)} products and terminals {', '.join(terminals)}.")
    await db_session.dispose_engine()
    return True


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "pims_demo"
    url = ensure_database(name)
    password = os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(12)
    created = asyncio.run(seed(url, password))
    if created:
        path = BACKEND_DIR / ".demo-credentials"
        lines = [f"Demo database: {name}", f"Password for every demo user: {password}", "Cashier PIN: 1593 (cashier), manager PIN: 2468 (manager)", "Users:"]
        lines += [f"  {u:<11} {r}" for u, r, _ in USERS]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Credentials written to {path} (git-ignored). Start the API with DB_NAME={name}.")


if __name__ == "__main__":
    use_selector_loop()
    main()
