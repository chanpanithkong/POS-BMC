"""Products, variants, unit conversions, barcodes and images (PRD; Phase 3).

Rules enforced here:
- SKU unique per company (case-insensitive); generated from the SKU sequence when SKU mode is AUTO.
- An active barcode belongs to exactly one product unit; check digits are validated (BR-PRD-001).
- The base unit cannot change once the product has stock movements (BR-PRD-002).
- Weighed products use fractional quantities; non-fractional products use precision 0.
- Activating a product needs a retail price, an active category and an active base unit.
- Only draft products without movements can be deleted; others are deactivated or discontinued.
- Cost fields are returned only to users with inventory.cost.view (BR-SEC-003).
"""

import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, InvalidStateTransition, NotFound, ValidationFailed
from app.models import (
    AuditLog,
    Branch,
    Brand,
    Category,
    Company,
    InventoryBalance,
    Product,
    ProductBarcode,
    ProductBranchSetting,
    ProductSupplier,
    ProductWarehouseSetting,
    Supplier,
    TaxCode,
    Unit,
    UnitConversion,
    Warehouse,
    WarehouseLocation,
)
from app.schemas import catalog as s
from app.services import files, pricing
from app.services.common import allocate, ensure_unique, next_number, owned, plain, record_audit
from app.services.principal import Principal

MODULE = "PRD"
TRANSITIONS = {
    "DRAFT": {"DRAFT", "ACTIVE", "INACTIVE", "DISCONTINUED"},
    "ACTIVE": {"ACTIVE", "INACTIVE", "DISCONTINUED"},
    "INACTIVE": {"INACTIVE", "ACTIVE", "DISCONTINUED"},
    "DISCONTINUED": {"DISCONTINUED"},
}
SCALAR_FIELDS = ("sku", "name_en", "name_km", "description", "type", "category_id", "brand_id", "base_unit_id", "allow_fraction", "precision", "tax_code_id",
                 "status", "min_selling_price", "track_expiry", "is_favourite")
MAX_IMAGE_BYTES = 2 * 1024 * 1024
IMAGE_URL_PREFIX = "/api/v1/files/products/"


# Barcodes

def check_digit(body: str) -> int:
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10


def barcode_problem(code: str, symbology: str) -> str | None:
    lengths = {"EAN13": 13, "EAN8": 8, "UPCA": 12}
    if symbology in lengths:
        if not code.isdigit() or len(code) != lengths[symbology]:
            return f"{symbology} barcodes have {lengths[symbology]} digits."
        if check_digit(code[:-1]) != int(code[-1]):
            return "The check digit is wrong."
        return None
    if not re.fullmatch(r"[\x20-\x7e]{1,64}", code):
        return "Barcodes may only contain printable ASCII characters."
    return None


async def generate_barcode(db: AsyncSession, actor: Principal) -> dict:
    """In-store EAN-13 (prefix 20) from the BARCODE sequence, skipping any value already in use."""
    for _ in range(20):
        template, _parts, value = await allocate(db, actor.company_id, "BARCODE")
        body = (template.prefix + str(value).zfill(template.padding))[:12].ljust(12, "0")
        code = body + str(check_digit(body))
        if not await db.scalar(select(ProductBarcode.id).where(ProductBarcode.company_id == actor.company_id, ProductBarcode.barcode == code).limit(1)):
            await db.commit()
            return {"barcode": code, "symbology": "EAN13"}
    raise AppError("Could not generate a free barcode.", code="CONFIGURATION_ERROR", status_code=500)


# Images

def normalise_image(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("data:"):
        return files.store_data_url("products", value, field="image", allowed=("jpg", "png", "webp"), max_bytes=MAX_IMAGE_BYTES)
    if value.startswith(IMAGE_URL_PREFIX) or re.fullmatch(r"https://[^\s]{1,490}", value):
        return value
    raise ValidationFailed("image", "Use an https:// image URL or upload an image.")


# Views

def _settings_view(row: Any) -> dict:
    return {k: getattr(row, k) for k in ("reorder_level", "min_level", "max_level", "reorder_qty")}


async def product_view(db: AsyncSession, actor: Principal, product: Product) -> dict:
    conversions = list(await db.scalars(select(UnitConversion).where(UnitConversion.product_id == product.id).order_by(UnitConversion.factor)))
    barcodes = list(await db.scalars(select(ProductBarcode).where(ProductBarcode.product_id == product.id).order_by(ProductBarcode.created_at)))
    warehouses = await db.scalars(select(ProductWarehouseSetting).where(ProductWarehouseSetting.product_id == product.id))
    branches = await db.scalars(select(ProductBranchSetting).where(ProductBranchSetting.product_id == product.id))
    category = await db.get(Category, product.category_id)
    brand = await db.get(Brand, product.brand_id) if product.brand_id else None
    unit = await db.get(Unit, product.base_unit_id)
    view = {f: getattr(product, f) for f in (*SCALAR_FIELDS, "id", "parent_id", "variant_attrs", "has_movements", "created_at", "updated_at", "version")}
    view.update(
        image=product.image_url,
        conversions=conversions,
        barcodes=barcodes,
        retail_price=await pricing.list_price(db, product, "RETAIL") or Decimal("0"),
        wholesale_price=await pricing.list_price(db, product, "WHOLESALE") or Decimal("0"),
        last_purchase_cost=product.last_purchase_cost if actor.sees_cost else None,
        avg_cost=product.avg_cost if actor.sees_cost else None,
        stock_settings=_settings_view(product),
        warehouse_settings={w.warehouse_id: _settings_view(w) for w in warehouses},
        branch_activation={b.branch_id: b.active for b in branches},
        suppliers=[{"supplier_id": x.supplier_id, "supplier_sku": x.supplier_sku, "purchase_unit_id": x.purchase_unit_id, "cost": x.cost if actor.sees_cost or actor.can("purchasing.order.create") else None,
                    "lead_time_days": x.lead_time_days, "preferred": x.preferred} for x in await db.scalars(select(ProductSupplier).where(ProductSupplier.product_id == product.id))],
        category_name=category.name_en if category else "",
        brand_name=brand.name if brand else "",
        unit_code=unit.code if unit else "",
        **await _stock_totals(db, actor, product.id),
    )
    return view


async def _stock_totals(db: AsyncSession, actor: Principal, product_id: uuid.UUID) -> dict[str, Decimal]:
    """On hand across the caller's warehouses (in transit excluded) and sellable quantity at sellable locations."""
    from app.services.stock import visible_warehouses

    row = (await db.execute(
        select(func.coalesce(func.sum(InventoryBalance.on_hand), 0),
               func.coalesce(func.sum(case((WarehouseLocation.is_available_for_sale, InventoryBalance.on_hand - InventoryBalance.reserved), else_=0)), 0))
        .join(WarehouseLocation, WarehouseLocation.id == InventoryBalance.location_id)
        .where(InventoryBalance.product_id == product_id, InventoryBalance.warehouse_id.in_(visible_warehouses(actor)))
    )).one()
    return {"on_hand": Decimal(row[0]), "available": Decimal(row[1])}


# Validation helpers

async def _active(db: AsyncSession, actor: Principal, model: type, record_id: uuid.UUID | None, what: str, field: str) -> Any:
    if record_id is None:
        return None
    record = await owned(db, model, record_id, actor, what)
    if getattr(record, "status", "ACTIVE") != "ACTIVE":
        raise ValidationFailed(field, f"This {what.lower()} is inactive.")
    return record


async def _company_settings(db: AsyncSession, actor: Principal) -> dict:
    company = await db.get(Company, actor.company_id)
    return (company.settings or {}) if company else {}


def _check_type_rules(values: dict) -> None:
    if values["type"] == "WEIGHED":
        values["allow_fraction"] = True
        if values["precision"] == 0:
            values["precision"] = 3
    if not values["allow_fraction"]:
        values["precision"] = 0
    elif values["precision"] == 0:
        raise ValidationFailed("precision", "Fractional products need a precision of 1 to 4 decimal places.")
    if values["type"] in ("SERVICE", "VARIANT_PARENT") and values["track_expiry"]:
        raise ValidationFailed("track_expiry", "Services and variant parents do not hold stock.")


async def _replace_conversions(db: AsyncSession, actor: Principal, product: Product, items: list[s.ConversionIn]) -> None:
    seen: set[uuid.UUID] = set()
    for item in items:
        if item.unit_id == product.base_unit_id:
            raise ValidationFailed("conversions", "The base unit does not need a conversion.")
        if item.unit_id in seen:
            raise ValidationFailed("conversions", "Each unit can have only one conversion.")
        seen.add(item.unit_id)
        await _active(db, actor, Unit, item.unit_id, "Unit", "conversions")
    if sum(i.is_purchase_default for i in items) > 1 or sum(i.is_sales_default for i in items) > 1:
        raise ValidationFailed("conversions", "Only one default purchase unit and one default sales unit are allowed.")
    existing = {c.unit_id: c for c in await db.scalars(select(UnitConversion).where(UnitConversion.product_id == product.id))}
    if product.has_movements:
        changed = [u for u, c in existing.items() if u not in seen or next(i.factor for i in items if i.unit_id == u) != c.factor]
        if changed:
            raise ValidationFailed("conversions", "Conversion factors cannot change after stock movements; add a new unit instead.")
    removed = set(existing) - seen
    if removed:
        in_use = await db.scalar(select(ProductBarcode.id).where(ProductBarcode.product_id == product.id, ProductBarcode.unit_id.in_(removed), ProductBarcode.active).limit(1))
        if in_use:
            raise ValidationFailed("conversions", "Deactivate the barcodes for a unit before removing its conversion.")
        await db.execute(delete(UnitConversion).where(UnitConversion.product_id == product.id, UnitConversion.unit_id.in_(removed)))
    for item in items:
        row = existing.get(item.unit_id)
        if row is None:
            db.add(UnitConversion(product_id=product.id, unit_id=item.unit_id, factor=item.factor, is_purchase_default=item.is_purchase_default, is_sales_default=item.is_sales_default))
        else:
            row.factor, row.is_purchase_default, row.is_sales_default = item.factor, item.is_purchase_default, item.is_sales_default
    await db.flush()


async def _replace_barcodes(db: AsyncSession, actor: Principal, product: Product, items: list[s.BarcodeIn]) -> None:
    """Barcodes are matched by value. Ones left out are deactivated, never deleted, so history stays readable."""
    units = {product.base_unit_id, *await db.scalars(select(UnitConversion.unit_id).where(UnitConversion.product_id == product.id))}
    wanted: dict[str, s.BarcodeIn] = {}
    for item in items:
        code = item.barcode.strip()
        if code in wanted:
            raise ValidationFailed("barcodes", f"Barcode {code} is listed twice.")
        if item.unit_id not in units:
            raise ValidationFailed("barcodes", f"Barcode {code} uses a unit the product does not have.")
        if item.active and (problem := barcode_problem(code, item.symbology)):
            raise ValidationFailed("barcodes", f"{code}: {problem}")
        wanted[code] = item
    active_codes = [c for c, i in wanted.items() if i.active]
    if active_codes:
        clash = await db.execute(
            select(ProductBarcode.barcode, Product.sku).join(Product, Product.id == ProductBarcode.product_id)
            .where(ProductBarcode.company_id == actor.company_id, ProductBarcode.active, ProductBarcode.barcode.in_(active_codes), ProductBarcode.product_id != product.id)
        )
        for code, sku in clash:
            raise AppError(f"Barcode {code} is already used by {sku}.", code="DUPLICATE_BARCODE", status_code=409, details=[{"field": "barcodes", "message": f"{code} belongs to {sku}"}])
    existing = {b.barcode: b for b in await db.scalars(select(ProductBarcode).where(ProductBarcode.product_id == product.id))}
    for code, row in existing.items():
        if code not in wanted:
            row.active = False
    await db.flush()
    for code, item in wanted.items():
        row = existing.get(code)
        if row is None:
            db.add(ProductBarcode(company_id=actor.company_id, product_id=product.id, barcode=code, symbology=item.symbology, unit_id=item.unit_id, active=item.active))
        else:
            row.symbology, row.unit_id, row.active = item.symbology, item.unit_id, item.active
    await db.flush()


async def _replace_settings(db: AsyncSession, actor: Principal, product: Product, data: s.ProductFields) -> None:
    if data.stock_settings is not None:
        for k, v in data.stock_settings.model_dump().items():
            setattr(product, k, v)
    if data.warehouse_settings is not None:
        ids = list(data.warehouse_settings)
        if ids:
            found = set(await db.scalars(select(Warehouse.id).where(Warehouse.id.in_(ids), Warehouse.company_id == actor.company_id, Warehouse.is_system.is_(False))))
            if found != set(ids):
                raise ValidationFailed("warehouse_settings", "One or more warehouses do not exist.")
        await db.execute(delete(ProductWarehouseSetting).where(ProductWarehouseSetting.product_id == product.id))
        db.add_all(ProductWarehouseSetting(product_id=product.id, warehouse_id=w, **v.model_dump()) for w, v in data.warehouse_settings.items())
    if data.branch_activation is not None:
        ids = list(data.branch_activation)
        if ids:
            found = set(await db.scalars(select(Branch.id).where(Branch.id.in_(ids), Branch.company_id == actor.company_id)))
            if found != set(ids):
                raise ValidationFailed("branch_activation", "One or more branches do not exist.")
        await db.execute(delete(ProductBranchSetting).where(ProductBranchSetting.product_id == product.id))
        db.add_all(ProductBranchSetting(product_id=product.id, branch_id=b, active=a) for b, a in data.branch_activation.items())
    if data.suppliers is not None:
        await _replace_suppliers(db, actor, product, data.suppliers)
    await db.flush()


async def _replace_suppliers(db: AsyncSession, actor: Principal, product: Product, links: list[s.SupplierLinkIn]) -> None:
    if sum(link.preferred for link in links) > 1:
        raise ValidationFailed("suppliers", "Only one supplier can be preferred.")
    units = {product.base_unit_id, *await db.scalars(select(UnitConversion.unit_id).where(UnitConversion.product_id == product.id))}
    seen = set()
    for link in links:
        if link.supplier_id in seen:
            raise ValidationFailed("suppliers", "A supplier is listed twice.")
        seen.add(link.supplier_id)
        await owned(db, Supplier, link.supplier_id, actor, "Supplier")
        if link.purchase_unit_id and link.purchase_unit_id not in units:
            raise ValidationFailed("suppliers", "The purchase unit must be the base unit or one of the product's conversions.")
    await db.execute(delete(ProductSupplier).where(ProductSupplier.product_id == product.id))
    await db.flush()
    db.add_all(ProductSupplier(product_id=product.id, supplier_id=link.supplier_id, supplier_sku=link.supplier_sku, purchase_unit_id=link.purchase_unit_id or product.base_unit_id,
                               cost=link.cost, lead_time_days=link.lead_time_days, preferred=link.preferred) for link in links)
    await db.flush()


async def _check_references(db: AsyncSession, actor: Principal, values: dict) -> None:
    category = await _active(db, actor, Category, values["category_id"], "Category", "category_id")
    await _active(db, actor, Brand, values.get("brand_id"), "Brand", "brand_id")
    unit = await _active(db, actor, Unit, values["base_unit_id"], "Unit", "base_unit_id")
    await _active(db, actor, TaxCode, values.get("tax_code_id"), "Tax code", "tax_code_id")
    if values["type"] == "WEIGHED" and unit and unit.dimension == "COUNT":
        raise ValidationFailed("base_unit_id", "Weighed products need a weight, volume or length unit.")
    if values.get("tax_code_id") is None and category and category.default_tax_code_id:
        values["tax_code_id"] = category.default_tax_code_id


async def _check_activation(db: AsyncSession, product: Product) -> None:
    if product.status != "ACTIVE" or product.type == "VARIANT_PARENT":
        return
    retail = await pricing.list_price(db, product, "RETAIL")
    if retail is None and product.type != "SERVICE":
        raise ValidationFailed("retail_price", "Set a retail price before activating the product.")


async def _apply_prices(db: AsyncSession, actor: Principal, product: Product, retail: Decimal | None, wholesale: Decimal | None) -> None:
    if (retail is not None or wholesale is not None) and not actor.can("pricing.price.edit") and not actor.can("products.product.create"):
        raise AppError("You do not have permission to change prices.", code="FORBIDDEN", status_code=403)
    for code, value in (("RETAIL", retail), ("WHOLESALE", wholesale)):
        if value is None:
            continue
        current = await pricing.list_price(db, product, code)
        if current is None and value == 0 and code == "WHOLESALE":
            continue  # a zero wholesale price means "not sold wholesale"
        if current != value:
            if current is not None and not actor.can("pricing.price.edit"):
                raise AppError("Changing an existing price needs pricing.price.edit.", code="FORBIDDEN", status_code=403)
            await pricing.set_price(db, actor, product, price=value, list_code=code)


# Commands

async def _new_sku(db: AsyncSession, actor: Principal, requested: str | None) -> str:
    sku = (requested or "").strip()
    if sku:
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,60}", sku):
            raise ValidationFailed("sku", "SKU may contain letters, digits, '.', '_', '/' and '-' only.")
        await ensure_unique(db, Product, actor, "sku", sku)
        return sku
    settings = await _company_settings(db, actor)
    if settings.get("sku_mode", "AUTO") != "AUTO":
        raise ValidationFailed("sku", "SKU is required.")
    for _ in range(20):
        sku = await next_number(db, actor.company_id, "SKU")
        if not await db.scalar(select(Product.id).where(Product.company_id == actor.company_id, func.lower(Product.sku) == sku.lower(), Product.deleted_at.is_(None))):
            return sku
    raise AppError("Could not generate a free SKU.", code="CONFIGURATION_ERROR", status_code=500)


def _clean_attrs(attrs: dict[str, str]) -> dict[str, str]:
    # The frontend's camel-to-snake conversion turns "Colour" into "_colour"; restore a readable label.
    return {k.lstrip("_").replace("_", " ").title(): v.strip() for k, v in attrs.items() if v.strip()}


async def create_product(db: AsyncSession, actor: Principal, data: s.ProductCreate) -> dict:
    values = data.model_dump(include=set(SCALAR_FIELDS))
    values.update({k: v for k, v in {"name_km": "", "description": "", "allow_fraction": False, "precision": 0, "track_expiry": False, "is_favourite": False}.items() if values.get(k) is None})
    values["sku"] = await _new_sku(db, actor, data.sku)
    _check_type_rules(values)
    await _check_references(db, actor, values)
    if data.type == "VARIANT_PARENT" and not data.variants:
        raise ValidationFailed("variants", "A variant parent needs at least one variant.")
    if data.type != "VARIANT_PARENT" and data.variants:
        raise ValidationFailed("variants", "Only variant parents have variants.")
    requested_status = values["status"]
    values["status"] = "DRAFT"
    product = Product(company_id=actor.company_id, created_by=actor.user_id, image_url=normalise_image(data.image), **values)
    db.add(product)
    await db.flush()
    await _replace_conversions(db, actor, product, data.conversions or [])
    await _replace_barcodes(db, actor, product, data.barcodes or [])
    await _replace_settings(db, actor, product, data)
    if data.type != "VARIANT_PARENT":
        await _apply_prices(db, actor, product, data.retail_price, data.wholesale_price)
    product.status = requested_status
    await _check_activation(db, product)

    for variant in data.variants:
        attrs = _clean_attrs(variant.attrs)
        child_values = {**values, "type": "STANDARD", "status": "DRAFT", "sku": await _new_sku(db, actor, variant.sku or None), "name_en": f"{values['name_en']} {' '.join(attrs.values())}".strip()[:200]}
        child = Product(company_id=actor.company_id, created_by=actor.user_id, parent_id=product.id, variant_attrs=attrs, image_url=product.image_url, **child_values)
        _check_type_rules({**child_values, "track_expiry": child.track_expiry})
        db.add(child)
        await db.flush()
        await _replace_conversions(db, actor, child, data.conversions or [])
        if variant.barcode:
            symbology = "EAN13" if len(variant.barcode) == 13 and variant.barcode.isdigit() else "CODE128"
            await _replace_barcodes(db, actor, child, [s.BarcodeIn(barcode=variant.barcode, symbology=symbology, unit_id=child.base_unit_id)])
        await _apply_prices(db, actor, child, data.retail_price, data.wholesale_price)
        child.status = requested_status
        await _check_activation(db, child)

    await db.flush()
    await record_audit(db, actor, "PRODUCT_CREATED", MODULE, "product", product.id, after=plain({**values, "status": requested_status, "variants": len(data.variants)}))
    await db.commit()
    return await product_view(db, actor, product)


async def get_product(db: AsyncSession, actor: Principal, product_id: uuid.UUID) -> dict:
    return await product_view(db, actor, await owned(db, Product, product_id, actor, "Product"))


async def update_product(db: AsyncSession, actor: Principal, product_id: uuid.UUID, data: s.ProductUpdate) -> dict:
    product = await owned(db, Product, product_id, actor, "Product", lock=True)
    changes = data.model_dump(include=set(SCALAR_FIELDS), exclude_unset=True)
    for key in ("name_en", "type", "category_id", "base_unit_id", "status", "allow_fraction", "precision", "track_expiry", "is_favourite"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    if "sku" in changes:
        sku = (changes["sku"] or "").strip()
        if not sku or sku.lower() == product.sku.lower():
            changes.pop("sku")
        else:
            await ensure_unique(db, Product, actor, "sku", sku, exclude=product.id)
            changes["sku"] = sku
    if "type" in changes and changes["type"] != product.type and (product.has_movements or product.type == "VARIANT_PARENT" or changes["type"] == "VARIANT_PARENT"):
        raise ValidationFailed("type", "The product type cannot change after stock movements or for variant parents.")
    if "base_unit_id" in changes and changes["base_unit_id"] != product.base_unit_id and product.has_movements:
        raise ValidationFailed("base_unit_id", "The base unit is locked because the product has stock movements.")
    new_status = changes.get("status", product.status)
    if new_status not in TRANSITIONS[product.status]:
        raise InvalidStateTransition(f"A {product.status.lower()} product cannot become {new_status.lower()}.")
    values = {f: changes.get(f, getattr(product, f)) for f in SCALAR_FIELDS}
    _check_type_rules(values)
    await _check_references(db, actor, values)
    changes.update({k: values[k] for k in ("allow_fraction", "precision", "tax_code_id")})
    before = {k: plain(getattr(product, k)) for k in changes if getattr(product, k) != changes[k]}
    for k, v in changes.items():
        setattr(product, k, v)
    if "image" in data.model_fields_set:
        new_image = normalise_image(data.image)
        if new_image != product.image_url:
            before["image"] = product.image_url
            product.image_url = new_image
    if data.conversions is not None:
        await _replace_conversions(db, actor, product, data.conversions)
    if data.barcodes is not None:
        old = sorted(b for b in await db.scalars(select(ProductBarcode.barcode).where(ProductBarcode.product_id == product.id, ProductBarcode.active)))
        await _replace_barcodes(db, actor, product, data.barcodes)
        new = sorted(b.barcode.strip() for b in data.barcodes if b.active)
        if old != new:
            before["barcodes"] = ", ".join(old)
            changes["barcodes"] = ", ".join(new)
    await _replace_settings(db, actor, product, data)
    if product.type != "VARIANT_PARENT":
        await _apply_prices(db, actor, product, data.retail_price, data.wholesale_price)
    await _check_activation(db, product)
    product.updated_by = actor.user_id
    after = {k: plain(changes[k]) if k in changes else plain(product.image_url) for k in before}
    if after:
        await record_audit(db, actor, "PRODUCT_UPDATED", MODULE, "product", product.id, before=before, after=after)
    await db.flush()
    await db.commit()
    await db.refresh(product)
    return await product_view(db, actor, product)


async def delete_product(db: AsyncSession, actor: Principal, product_id: uuid.UUID) -> None:
    product = await owned(db, Product, product_id, actor, "Product", lock=True)
    if product.has_movements or product.status != "DRAFT":
        raise Conflict("Only draft products without stock movements can be deleted. Deactivate or discontinue it instead.", code="PRODUCT_IN_USE")
    if await db.scalar(select(Product.id).where(Product.parent_id == product.id, Product.deleted_at.is_(None)).limit(1)):
        raise Conflict("Delete or move the variants first.", code="PRODUCT_IN_USE")
    product.deleted_at = func.now()
    product.status = "INACTIVE"
    for barcode in await db.scalars(select(ProductBarcode).where(ProductBarcode.product_id == product.id, ProductBarcode.active)):
        barcode.active = False  # frees the barcode for reuse
    await record_audit(db, actor, "PRODUCT_DELETED", MODULE, "product", product.id, before={"sku": product.sku})
    await db.commit()


async def duplicate_product(db: AsyncSession, actor: Principal, product_id: uuid.UUID) -> dict:
    source = await owned(db, Product, product_id, actor, "Product")
    if source.type == "VARIANT_PARENT":
        raise ValidationFailed("type", "Variant parents cannot be duplicated; create a new product with its variants.")
    values = {f: getattr(source, f) for f in SCALAR_FIELDS}
    values.update(sku=await _new_sku(db, actor, None) if (await _company_settings(db, actor)).get("sku_mode", "AUTO") == "AUTO" else f"{source.sku}-COPY"[:60],
                  name_en=f"{source.name_en} (copy)"[:200], status="DRAFT")
    await ensure_unique(db, Product, actor, "sku", values["sku"])
    copy = Product(company_id=actor.company_id, created_by=actor.user_id, image_url=source.image_url, **values,
                   **{k: getattr(source, k) for k in ("reorder_level", "min_level", "max_level", "reorder_qty")})
    db.add(copy)
    await db.flush()
    conversions = await db.scalars(select(UnitConversion).where(UnitConversion.product_id == source.id))
    db.add_all(UnitConversion(product_id=copy.id, unit_id=c.unit_id, factor=c.factor, is_purchase_default=c.is_purchase_default, is_sales_default=c.is_sales_default) for c in conversions)
    await db.flush()
    # Barcodes are not copied (each must be unique); prices are, as new rows starting now.
    for code in ("RETAIL", "WHOLESALE"):
        price = await pricing.list_price(db, source, code)
        if price is not None:
            await pricing.set_price(db, actor, copy, price=price, list_code=code)
    await record_audit(db, actor, "PRODUCT_DUPLICATED", MODULE, "product", copy.id, after={"from": source.sku, "sku": copy.sku})
    await db.commit()
    return await product_view(db, actor, copy)


# Queries

def _search(query: Any, q: str | None) -> Any:
    if not q:
        return query
    like = f"%{q.strip().lower()}%"
    barcode_match = select(ProductBarcode.product_id).where(ProductBarcode.barcode == q.strip(), ProductBarcode.active)
    return query.where(or_(func.lower(Product.name_en).like(like), func.lower(Product.name_km).like(like), func.lower(Product.sku).like(like), Product.id.in_(barcode_match)))


async def list_products(db: AsyncSession, actor: Principal, *, q: str | None, category_id: uuid.UUID | None, brand_id: uuid.UUID | None, status: str | None,
                        type_: str | None, sellable: bool, limit: int, offset: int) -> tuple[list[dict], int]:
    query = _search(select(Product).where(Product.company_id == actor.company_id, Product.deleted_at.is_(None)), q)
    for column, value in ((Product.category_id, category_id), (Product.brand_id, brand_id), (Product.status, status), (Product.type, type_)):
        if value is not None:
            query = query.where(column == value)
    if sellable:
        query = query.where(Product.status == "ACTIVE", Product.type != "VARIANT_PARENT")
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    products = await db.scalars(query.order_by(Product.is_favourite.desc(), Product.name_en).limit(limit).offset(offset))
    return [await product_view(db, actor, p) for p in products], total


async def scan(db: AsyncSession, actor: Principal, barcode: str, branch_id: uuid.UUID | None) -> dict:
    """POS barcode lookup: product, scanned unit and resolved unit price (FR-POS-002)."""
    row = await db.scalar(select(ProductBarcode).where(ProductBarcode.company_id == actor.company_id, ProductBarcode.barcode == barcode.strip(), ProductBarcode.active))
    product = await db.get(Product, row.product_id) if row else None
    if row is None or product is None or product.deleted_at is not None:
        raise NotFound("Product for this barcode")
    if branch_id:
        actor.assert_branch(branch_id)
        setting = await db.get(ProductBranchSetting, (product.id, branch_id))
        if setting is not None and not setting.active:
            raise AppError("This product is not sold at this branch.", code="PRODUCT_NOT_SELLABLE", status_code=422)
    if product.status != "ACTIVE" or product.type == "VARIANT_PARENT":
        raise AppError(f"{product.name_en} is {product.status.lower()} and cannot be sold.", code="PRODUCT_NOT_SELLABLE", status_code=422)
    resolved = await pricing.resolve(db, product, row.unit_id, branch_id=branch_id)
    factor = await pricing.unit_factor(db, product, row.unit_id) or Decimal("1")
    return {**await product_view(db, actor, product), "scanned_barcode": row.barcode, "scanned_unit_id": row.unit_id, "unit_factor": factor, "unit_price": resolved.price, "price_source": resolved.source}


async def list_barcodes(db: AsyncSession, actor: Principal, q: str | None, limit: int, offset: int) -> list[dict]:
    query = (
        select(ProductBarcode, Product.sku, Product.name_en, Unit.code)
        .join(Product, Product.id == ProductBarcode.product_id).join(Unit, Unit.id == ProductBarcode.unit_id)
        .where(ProductBarcode.company_id == actor.company_id, Product.deleted_at.is_(None))
    )
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(ProductBarcode.barcode.like(like), func.lower(Product.sku).like(like), func.lower(Product.name_en).like(like)))
    rows = await db.execute(query.order_by(Product.sku, ProductBarcode.created_at).limit(limit).offset(offset))
    return [{**{f: getattr(b, f) for f in ("id", "barcode", "symbology", "unit_id", "active", "created_at", "product_id")}, "sku": sku, "product_name": name, "unit_code": unit} for b, sku, name, unit in rows]


async def history(db: AsyncSession, actor: Principal, product_id: uuid.UUID) -> list[dict]:
    """Field-level change history, read from the audit log (FR-PRD-008)."""
    await owned(db, Product, product_id, actor, "Product")
    logs = await db.scalars(select(AuditLog).where(AuditLog.company_id == actor.company_id, AuditLog.entity_type == "product", AuditLog.entity_id == str(product_id)).order_by(AuditLog.id.desc()))
    rows: list[dict] = []
    for log in logs:
        before, after = log.before or {}, log.after or {}
        fields = sorted(set(before) | set(after)) or ["(record)"]
        for field in fields:
            rows.append({"id": f"{log.id}-{field}", "product_id": product_id, "at": log.occurred_at, "user_name": log.user_name, "field": field if field != "(record)" else log.action.lower(),
                         "before": "" if before.get(field) is None else str(before.get(field)), "after": "" if after.get(field) is None else str(after.get(field))})
    return rows
