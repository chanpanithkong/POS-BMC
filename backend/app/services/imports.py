"""Two-phase imports (IMP; Phase 8, BR-IMP-001).

1. Preview: every row is validated against the database and the file itself; the valid
   rows are stored with a one-hour token. Nothing is written to master data.
2. Commit: rows are validated again and written in ONE transaction: if any row fails,
   nothing is imported. Stock arrives only through movements (OPENING), prices only
   through effective-dated price rows, so the usual rules and audit apply.
Products, suppliers and customers can be rolled back while nothing references them yet.
Opening stock, prices and count entries are corrected with adjustments, prices or recounts.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, InvalidStateTransition, NotFound, ValidationFailed
from app.models import (
    Branch,
    Brand,
    Category,
    Customer,
    ImportBatch,
    ImportPreview,
    InventoryMovement,
    PriceList,
    Product,
    ProductBarcode,
    PurchaseOrder,
    Sale,
    StockCount,
    StockCountLine,
    Supplier,
    TaxCode,
    Unit,
    UnitConversion,
    Warehouse,
    WarehouseLocation,
)
from app.services import pricing, stock
from app.services.common import record_audit
from app.services.customers import normalise_phone
from app.services.principal import Principal
from app.services.products import barcode_problem

COLUMNS = {
    "PRODUCTS": ["sku", "name_en", "name_km", "category", "brand", "base_unit", "tax_code", "status", "retail_price", "wholesale_price"],
    "BARCODES": ["sku", "barcode", "unit"],
    "SUPPLIERS": ["code", "name", "currency", "phone"],
    "CUSTOMERS": ["code", "name", "phone"],
    "OPENING_STOCK": ["warehouse", "location", "sku", "quantity", "unit", "unit_cost"],
    "PRICES": ["sku", "unit", "price_list", "branch", "price", "effective_from"],
    "STOCK_COUNT": ["count_no", "location", "sku", "counted_quantity", "unit"],
}
REQUIRED = {
    "PRODUCTS": ["sku", "name_en", "category", "base_unit", "status"],
    "BARCODES": ["sku", "barcode", "unit"],
    "SUPPLIERS": ["code", "name", "currency"],
    "CUSTOMERS": ["code", "name", "phone"],
    "OPENING_STOCK": ["warehouse", "location", "sku", "quantity", "unit", "unit_cost"],
    "PRICES": ["sku", "unit", "price_list", "price", "effective_from"],
    "STOCK_COUNT": ["count_no", "location", "sku", "counted_quantity"],
}
ROLLBACK_TYPES = ("PRODUCTS", "SUPPLIERS", "CUSTOMERS")
MAX_ROWS = 50_000


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value: str) -> Decimal | None:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def symbology(code: str) -> str:
    return {13: "EAN13", 8: "EAN8", 12: "UPCA"}.get(len(code), "CODE128") if code.isdigit() else "CODE128"


class Lookups:
    """Everything a validation pass needs, loaded once."""

    async def load(self, db: AsyncSession, actor: Principal) -> "Lookups":
        c = actor.company_id
        self.categories = {}
        for cat in await db.scalars(select(Category).where(Category.company_id == c)):
            self.categories[cat.code.lower()] = cat
            self.categories.setdefault(cat.name_en.lower(), cat)
        self.units = {u.code.lower(): u for u in await db.scalars(select(Unit).where(Unit.company_id == c))}
        self.taxes = {t.code.lower(): t for t in await db.scalars(select(TaxCode).where(TaxCode.company_id == c))}
        self.brands = {}
        for b in await db.scalars(select(Brand).where(Brand.company_id == c)):
            self.brands[b.code.lower()] = b
            self.brands.setdefault(b.name.lower(), b)
        self.products = {p.sku.lower(): p for p in await db.scalars(select(Product).where(Product.company_id == c, Product.deleted_at.is_(None)))}
        self.barcodes = set(await db.scalars(select(ProductBarcode.barcode).where(ProductBarcode.company_id == c, ProductBarcode.active)))
        self.suppliers = {x.lower() for x in await db.scalars(select(Supplier.code).where(Supplier.company_id == c, Supplier.deleted_at.is_(None)))}
        self.customer_codes = {x.lower() for x in await db.scalars(select(Customer.code).where(Customer.company_id == c))}
        self.customer_phones = set(await db.scalars(select(Customer.phone_normalised).where(Customer.company_id == c, Customer.phone_normalised != "", Customer.anonymized.is_(False))))
        self.warehouses = {w.code.lower(): w for w in await db.scalars(select(Warehouse).where(Warehouse.id.in_(stock.visible_warehouses(actor))))}
        self.locations = {(loc.warehouse_id, loc.code.lower()): loc for loc in await db.scalars(select(WarehouseLocation).where(WarehouseLocation.company_id == c))}
        self.price_lists = {pl.code.lower(): pl for pl in await db.scalars(select(PriceList).where(PriceList.company_id == c))}
        self.branches = {b.code.lower(): b for b in await db.scalars(select(Branch).where(Branch.company_id == c))}
        self.counts = {x.count_no.lower(): x for x in await db.scalars(select(StockCount).where(StockCount.company_id == c))}
        self.conversions = {(cv.product_id, cv.unit_id): cv.factor for cv in await db.scalars(select(UnitConversion))}
        opened = await db.execute(select(InventoryMovement.product_id, InventoryMovement.to_location_id).where(InventoryMovement.company_id == c, InventoryMovement.movement_type == "OPENING"))
        self.openings = {(pid, lid) for pid, lid in opened}
        return self

    def factor(self, product: Product, unit: Unit | None) -> Decimal | None:
        if unit is None:
            return None
        if unit.id == product.base_unit_id:
            return Decimal(1)
        return self.conversions.get((product.id, unit.id))


async def validate(db: AsyncSession, actor: Principal, kind: str, rows: list[dict[str, str]]) -> tuple[list[dict], Lookups]:
    lk = await Lookups().load(db, actor)
    errors: list[dict] = []
    seen: set[str] = set()
    today = datetime.now(UTC).date()

    def err(i: int, field: str, value: str, message: str) -> None:
        errors.append({"row": i, "field": field, "value": value, "message": message})

    def dup(i: int, key: str, field: str, value: str) -> None:
        if key in seen:
            err(i, field, value, "Duplicate within this file.")
        seen.add(key)

    def num(i: int, field: str, value: str, *, positive: bool = False, allow_zero: bool = True) -> Decimal | None:
        if value == "":
            return None
        n = _number(value)
        if n is None:
            err(i, field, value, "Must be a number.")
        elif n < 0 or (positive and n == 0 and not allow_zero):
            err(i, field, value, "Must be greater than zero." if positive else "Must not be negative.")
        return n

    for index, row in enumerate(rows):
        i = index + 2  # row 1 is the header
        for field in REQUIRED[kind]:
            if not row.get(field):
                err(i, field, row.get(field, ""), "Required field is empty.")
        sku = row.get("sku", "")
        product = lk.products.get(sku.lower()) if sku else None
        if kind == "PRODUCTS":
            dup(i, f"sku:{sku.lower()}", "sku", sku)
            if product:
                err(i, "sku", sku, "SKU already exists.")
            if row.get("category") and row["category"].lower() not in lk.categories:
                err(i, "category", row["category"], "Unknown category.")
            if row.get("base_unit") and row["base_unit"].lower() not in lk.units:
                err(i, "base_unit", row["base_unit"], "Unknown unit.")
            if row.get("tax_code") and row["tax_code"].upper() != "EXEMPT" and row["tax_code"].lower() not in lk.taxes:
                err(i, "tax_code", row["tax_code"], "Unknown tax code.")
            if row.get("brand") and row["brand"].lower() not in lk.brands:
                err(i, "brand", row["brand"], "Unknown brand.")
            if row.get("status") and row["status"].upper() not in ("DRAFT", "ACTIVE", "INACTIVE"):
                err(i, "status", row["status"], "Use DRAFT, ACTIVE or INACTIVE.")
            retail = num(i, "retail_price", row.get("retail_price", ""))
            num(i, "wholesale_price", row.get("wholesale_price", ""))
            if row.get("status", "").upper() == "ACTIVE" and not retail:
                err(i, "retail_price", row.get("retail_price", ""), "An active product needs a retail price.")
        elif kind == "BARCODES":
            code = row.get("barcode", "")
            dup(i, f"bc:{code}", "barcode", code)
            if code and (problem := barcode_problem(code, symbology(code))):
                err(i, "barcode", code, problem)
            if code in lk.barcodes:
                err(i, "barcode", code, "Barcode already in use.")
            if sku and not product:
                err(i, "sku", sku, "Unknown SKU.")
            unit = lk.units.get(row.get("unit", "").lower())
            if row.get("unit") and unit is None:
                err(i, "unit", row["unit"], "Unknown unit.")
            elif product and unit and lk.factor(product, unit) is None:
                err(i, "unit", row["unit"], "The product has no conversion for this unit.")
        elif kind == "SUPPLIERS":
            code = row.get("code", "")
            dup(i, f"c:{code.lower()}", "code", code)
            if code.lower() in lk.suppliers:
                err(i, "code", code, "Supplier code already exists.")
            if row.get("currency") and row["currency"].upper() not in ("USD", "KHR"):
                err(i, "currency", row["currency"], "Currency must be USD or KHR.")
        elif kind == "CUSTOMERS":
            code, phone = row.get("code", ""), normalise_phone(row.get("phone", ""))
            dup(i, f"c:{code.lower()}", "code", code)
            dup(i, f"p:{phone}", "phone", row.get("phone", ""))
            if code.lower() in lk.customer_codes:
                err(i, "code", code, "Customer code already exists.")
            if phone and phone in lk.customer_phones:
                err(i, "phone", row.get("phone", ""), "A customer with this phone already exists.")
        elif kind == "OPENING_STOCK":
            dup(i, f"{sku.lower()}:{row.get('warehouse', '').lower()}:{row.get('location', '').lower()}", "sku", sku)
            warehouse = lk.warehouses.get(row.get("warehouse", "").lower())
            if row.get("warehouse") and warehouse is None:
                err(i, "warehouse", row["warehouse"], "Unknown warehouse (or outside your access).")
            location = lk.locations.get((warehouse.id, row.get("location", "").lower())) if warehouse else None
            if warehouse and row.get("location") and (location is None or location.location_type == "IN_TRANSIT"):
                err(i, "location", row["location"], "Unknown location in this warehouse.")
            if sku and not product:
                err(i, "sku", sku, "Unknown SKU.")
            if product and product.type in ("SERVICE", "VARIANT_PARENT"):
                err(i, "sku", sku, "This product does not hold stock.")
            if product and location and (product.id, location.id) in lk.openings:
                err(i, "sku", sku, "Opening stock was already posted for this location.")
            qty = num(i, "quantity", row.get("quantity", ""), positive=True, allow_zero=False)
            num(i, "unit_cost", row.get("unit_cost", ""))
            unit = lk.units.get(row.get("unit", "").lower())
            factor = lk.factor(product, unit) if product else None
            if product and row.get("unit") and factor is None:
                err(i, "unit", row["unit"], "The product has no conversion for this unit.")
            if product and qty and factor and not product.allow_fraction and (qty * factor) != (qty * factor).to_integral_value():
                err(i, "quantity", row["quantity"], "Must be a whole number for this product.")
        elif kind == "PRICES":
            dup(i, f"{sku.lower()}:{row.get('unit', '').lower()}:{row.get('price_list', '').lower()}:{row.get('branch', '').lower()}", "sku", sku)
            if sku and not product:
                err(i, "sku", sku, "Unknown SKU.")
            unit = lk.units.get(row.get("unit", "").lower())
            if row.get("unit") and unit is None:
                err(i, "unit", row["unit"], "Unknown unit.")
            elif product and unit and lk.factor(product, unit) is None:
                err(i, "unit", row["unit"], "The product has no conversion for this unit.")
            plist = lk.price_lists.get(row.get("price_list", "").lower())
            if row.get("price_list") and (plist is None or plist.type == "GROUP"):
                err(i, "price_list", row["price_list"], "Unknown price list (group prices are set per group).")
            if row.get("branch") and row["branch"].lower() not in lk.branches:
                err(i, "branch", row["branch"], "Unknown branch.")
            num(i, "price", row.get("price", ""))
            try:
                if row.get("effective_from") and datetime.fromisoformat(row["effective_from"][:10]).date() < today:
                    err(i, "effective_from", row["effective_from"], "Prices cannot be backdated.")
            except ValueError:
                err(i, "effective_from", row["effective_from"], "Use the date format YYYY-MM-DD.")
        elif kind == "STOCK_COUNT":
            dup(i, f"{sku.lower()}:{row.get('location', '').lower()}", "sku", sku)
            count = lk.counts.get(row.get("count_no", "").lower())
            if row.get("count_no") and count is None:
                err(i, "count_no", row["count_no"], "Unknown stock count.")
            if count and count.status != "COUNTING":
                err(i, "count_no", row["count_no"], "This count is not open for counting.")
            num(i, "counted_quantity", row.get("counted_quantity", ""))
            if count and product:
                location = lk.locations.get((count.warehouse_id, row.get("location", "").lower()))
                line = await db.scalar(select(StockCountLine.id).where(StockCountLine.count_id == count.id, StockCountLine.product_id == product.id,
                                                                       StockCountLine.location_id == (location.id if location else None)).limit(1))
                if line is None:
                    err(i, "sku", sku, "Not part of this count.")
            elif sku and not product:
                err(i, "sku", sku, "Unknown SKU.")
    return errors, lk


async def preview(db: AsyncSession, actor: Principal, kind: str, file_name: str, file_hash: str, raw_rows: list[dict]) -> dict:
    if not raw_rows:
        raise ValidationFailed("file", "The file has no data rows.")
    if len(raw_rows) > MAX_ROWS:
        raise ValidationFailed("file", f"The file exceeds {MAX_ROWS:,} rows.")
    rows = [{str(k).strip().lower(): _text(v) for k, v in r.items()} for r in raw_rows]
    missing = [c for c in REQUIRED[kind] if c not in rows[0]]
    if missing:
        raise ValidationFailed("file", f"Missing column(s): {', '.join(missing)}. Download the template for the correct format.")
    errors, _ = await validate(db, actor, kind, rows)
    token = secrets.token_urlsafe(24)
    await db.execute(delete(ImportPreview).where(ImportPreview.expires_at < datetime.now(UTC)))
    db.add(ImportPreview(token=token, company_id=actor.company_id, user_id=actor.user_id, type=kind, file_name=file_name, file_hash=file_hash, rows=rows,
                         expires_at=datetime.now(UTC) + timedelta(hours=1)))
    await db.commit()
    bad = {e["row"] for e in errors}
    return {"type": kind, "file_name": file_name, "total_rows": len(rows), "valid_rows": len(rows) - len(bad), "errors": errors[:2000], "sample": rows[:20], "columns": COLUMNS[kind], "token": token}


async def commit(db: AsyncSession, actor: Principal, token: str) -> dict:
    pv = await db.scalar(select(ImportPreview).where(ImportPreview.token == token, ImportPreview.company_id == actor.company_id, ImportPreview.user_id == actor.user_id).with_for_update())
    if pv is None or pv.expires_at <= datetime.now(UTC):
        raise Conflict("This preview has expired. Please upload the file again.", code="IMPORT_EXPIRED")
    kind, rows = pv.type, pv.rows
    errors, lk = await validate(db, actor, kind, rows)
    if errors:
        raise AppError("This file has blocking errors. Nothing was imported.", code="IMPORT_INVALID", status_code=422, details=errors[:200])
    batch = ImportBatch(company_id=actor.company_id, type=kind, file_name=pv.file_name, file_hash=pv.file_hash, user_id=actor.user_id, user_name=actor.full_name,
                        total_rows=len(rows), imported_rows=len(rows), can_rollback=kind in ROLLBACK_TYPES)
    db.add(batch)
    await db.flush()
    created: list[str] = []
    moves = []
    for i, row in enumerate(rows):
        if kind == "PRODUCTS":
            unit = lk.units[row["base_unit"].lower()]
            tax = lk.taxes.get(row.get("tax_code", "").lower())
            category = lk.categories[row["category"].lower()]
            status = row["status"].upper()
            product = Product(company_id=actor.company_id, sku=row["sku"], name_en=row["name_en"], name_km=row.get("name_km", ""), category_id=category.id,
                              brand_id=lk.brands[row["brand"].lower()].id if row.get("brand") else None, base_unit_id=unit.id,
                              tax_code_id=tax.id if tax else category.default_tax_code_id, status="DRAFT", allow_fraction=unit.dimension != "COUNT", precision=unit.precision if unit.dimension != "COUNT" else 0,
                              created_by=actor.user_id)
            db.add(product)
            await db.flush()
            for code, field in (("RETAIL", "retail_price"), ("WHOLESALE", "wholesale_price")):
                if row.get(field) and Decimal(row[field]) > 0:
                    await pricing.set_price(db, actor, product, price=Decimal(row[field]), list_code=code)
            product.status = status
            created.append(str(product.id))
        elif kind == "BARCODES":
            product = lk.products[row["sku"].lower()]
            db.add(ProductBarcode(company_id=actor.company_id, product_id=product.id, barcode=row["barcode"], symbology=symbology(row["barcode"]), unit_id=lk.units[row["unit"].lower()].id))
        elif kind == "SUPPLIERS":
            sup = Supplier(company_id=actor.company_id, code=row["code"], name_en=row["name"], currency=row["currency"].upper(), phone=row.get("phone", ""), created_by=actor.user_id)
            db.add(sup)
            await db.flush()
            created.append(str(sup.id))
        elif kind == "CUSTOMERS":
            cust = Customer(company_id=actor.company_id, code=row["code"], name=row["name"], phone=row["phone"], phone_normalised=normalise_phone(row["phone"]), created_by=actor.user_id)
            db.add(cust)
            await db.flush()
            created.append(str(cust.id))
        elif kind == "OPENING_STOCK":
            product = lk.products[row["sku"].lower()]
            warehouse = lk.warehouses[row["warehouse"].lower()]
            location = lk.locations[(warehouse.id, row["location"].lower())]
            factor = lk.factor(product, lk.units[row["unit"].lower()]) or Decimal(1)
            moves.append(stock.Move(product, Decimal(row["quantity"]) * factor, "OPENING", "IMPORT", str(batch.id), f"IMPORT:{batch.id}:{i}", to_location=location,
                                    unit_cost=Decimal(row["unit_cost"]) / factor, source_no=pv.file_name[:60], reason="OPENING", unit_id=lk.units[row["unit"].lower()].id,
                                    quantity_entered=Decimal(row["quantity"])))
        elif kind == "PRICES":
            product = await db.scalar(select(Product).where(Product.id == lk.products[row["sku"].lower()].id).with_for_update())
            start = datetime.fromisoformat(row["effective_from"][:10]).replace(tzinfo=UTC)
            branch = lk.branches.get(row.get("branch", "").lower())
            await pricing.set_price(db, actor, product, price=Decimal(row["price"]), unit_id=lk.units[row["unit"].lower()].id, price_list_id=lk.price_lists[row["price_list"].lower()].id,
                                    branch_id=branch.id if branch else None, effective_from=max(start, datetime.now(UTC)))
        elif kind == "STOCK_COUNT":
            count = lk.counts[row["count_no"].lower()]
            product = lk.products[row["sku"].lower()]
            location = lk.locations[(count.warehouse_id, row["location"].lower())]
            line = await db.scalar(select(StockCountLine).where(StockCountLine.count_id == count.id, StockCountLine.product_id == product.id, StockCountLine.location_id == location.id))
            line.counted_qty, line.counted_at, line.counted_by = Decimal(row["counted_quantity"]), datetime.now(UTC), actor.full_name
    if moves:
        # Products imported in the same company may share balance rows, so the ledger posts them together.
        for product_id, location_id in {(m.product.id, m.to_location.id) for m in moves}:
            if (product_id, location_id) in lk.openings:
                raise ValidationFailed("sku", "Opening stock was already posted for a row in this file.")
        await stock.post(db, actor, moves)
    batch.created_ids = created
    await db.delete(pv)
    await record_audit(db, actor, "IMPORT_COMMITTED", "IMP", "import", batch.id, after={"type": kind, "rows": len(rows), "file": pv.file_name})
    await db.commit()
    await db.refresh(batch)
    return batch_view(batch)


def batch_view(b: ImportBatch) -> dict:
    return {f: getattr(b, f) for f in ("id", "type", "file_name", "file_hash", "user_name", "at", "total_rows", "imported_rows", "status", "created_ids")} | {
        "can_rollback": b.can_rollback and b.status == "COMMITTED"}


async def list_batches(db: AsyncSession, actor: Principal) -> list[dict]:
    return [batch_view(b) for b in await db.scalars(select(ImportBatch).where(ImportBatch.company_id == actor.company_id).order_by(ImportBatch.at.desc()).limit(200))]


async def rollback(db: AsyncSession, actor: Principal, batch_id: uuid.UUID) -> dict:
    b = await db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.company_id == actor.company_id).with_for_update())
    if b is None:
        raise NotFound("Import")
    if b.status != "COMMITTED" or not b.can_rollback:
        raise InvalidStateTransition("This import cannot be rolled back. Correct stock with adjustments and prices with new prices.")
    ids = [uuid.UUID(x) for x in b.created_ids]
    if b.type == "PRODUCTS":
        if await db.scalar(select(Product.id).where(Product.id.in_(ids), Product.has_movements.is_(True)).limit(1)):
            raise Conflict("Some imported products already have stock movements.", code="IN_USE")
        for p in await db.scalars(select(Product).where(Product.id.in_(ids))):
            p.deleted_at, p.status = func.now(), "INACTIVE"
        for bc in await db.scalars(select(ProductBarcode).where(ProductBarcode.product_id.in_(ids), ProductBarcode.active)):
            bc.active = False
    elif b.type == "CUSTOMERS":
        if await db.scalar(select(Sale.id).where(Sale.customer_id.in_(ids)).limit(1)):
            raise Conflict("Some imported customers already have sales.", code="IN_USE")
        await db.execute(delete(Customer).where(Customer.id.in_(ids)))
    elif b.type == "SUPPLIERS":
        if await db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.supplier_id.in_(ids)).limit(1)):
            raise Conflict("Some imported suppliers already have purchase orders.", code="IN_USE")
        for sup in await db.scalars(select(Supplier).where(Supplier.id.in_(ids))):
            sup.deleted_at, sup.status = func.now(), "INACTIVE"
    b.status = "ROLLED_BACK"
    await record_audit(db, actor, "IMPORT_ROLLED_BACK", "IMP", "import", b.id, after={"type": b.type, "records": len(ids)}, flagged=True)
    await db.commit()
    await db.refresh(b)
    return batch_view(b)
