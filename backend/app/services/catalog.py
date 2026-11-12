"""Categories, brands and units of measure (CAT; Phase 3)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, ValidationFailed
from app.models import Brand, Category, Company, Product, ProductBarcode, ProductPrice, TaxCode, Unit, UnitConversion
from app.schemas import catalog as s
from app.services.common import apply_changes, ensure_unique, owned, plain, record_audit
from app.services.principal import Principal

MODULE = "CAT"
MAX_CATEGORY_DEPTH = 4


async def list_categories(db: AsyncSession, actor: Principal) -> list[Category]:
    return list(await db.scalars(select(Category).where(Category.company_id == actor.company_id).order_by(Category.code)))


async def _depth_and_cycle(db: AsyncSession, actor: Principal, category_id: uuid.UUID | None, parent_id: uuid.UUID | None) -> None:
    """Parent chain must not contain the category itself, and the tree is at most four levels (FR-CAT-001)."""
    depth, current = 1, parent_id
    while current is not None:
        if current == category_id:
            raise ValidationFailed("parent_id", "A category cannot be placed under itself or one of its subcategories.")
        parent = await owned(db, Category, current, actor, "Parent category")
        depth += 1
        current = parent.parent_id
    below = 0
    if category_id is not None:
        level = [category_id]
        while level:
            level = list(await db.scalars(select(Category.id).where(Category.parent_id.in_(level))))
            below += 1 if level else 0
    if depth + below > MAX_CATEGORY_DEPTH:
        raise ValidationFailed("parent_id", f"Categories can be at most {MAX_CATEGORY_DEPTH} levels deep.")


async def _check_tax(db: AsyncSession, actor: Principal, tax_code_id: uuid.UUID | None, field: str = "default_tax_code_id") -> None:
    if tax_code_id is not None:
        tax = await owned(db, TaxCode, tax_code_id, actor, "Tax code")
        if tax.status != "ACTIVE":
            raise ValidationFailed(field, "This tax code is inactive.")


async def _check_negative_stock(db: AsyncSession, actor: Principal, allow: bool | None) -> None:
    if allow:
        company = await db.get(Company, actor.company_id)
        if not (company and (company.settings or {}).get("negative_stock_allowed")):
            # D-06: negative stock is blocked company-wide unless the setting is turned on first.
            raise ValidationFailed("allow_negative_stock", "Negative stock is turned off for the company. Turn it on in settings first.")


async def create_category(db: AsyncSession, actor: Principal, data: s.CategoryCreate) -> Category:
    await ensure_unique(db, Category, actor, "code", data.code)
    await _depth_and_cycle(db, actor, None, data.parent_id)
    await _check_tax(db, actor, data.default_tax_code_id)
    await _check_negative_stock(db, actor, data.allow_negative_stock)
    category = Category(company_id=actor.company_id, created_by=actor.user_id, **data.model_dump())
    db.add(category)
    await db.flush()
    await record_audit(db, actor, "CATEGORY_CREATED", MODULE, "category", category.id, after=plain(data.model_dump()))
    await db.commit()
    return category


async def update_category(db: AsyncSession, actor: Principal, category_id: uuid.UUID, data: s.CategoryUpdate) -> Category:
    category = await owned(db, Category, category_id, actor, "Category")
    changes = data.model_dump(exclude_unset=True)
    await ensure_unique(db, Category, actor, "code", changes.get("code"), exclude=category.id)
    if "parent_id" in changes:
        await _depth_and_cycle(db, actor, category.id, changes["parent_id"])
    if "default_tax_code_id" in changes:
        await _check_tax(db, actor, changes["default_tax_code_id"])
    await _check_negative_stock(db, actor, changes.get("allow_negative_stock"))
    if changes.get("status") == "INACTIVE" and await db.scalar(select(Category.id).where(Category.parent_id == category.id, Category.status == "ACTIVE").limit(1)):
        raise Conflict("Deactivate the active subcategories first.", code="CATEGORY_IN_USE")
    before, after = apply_changes(category, changes)
    category.updated_by = actor.user_id
    if after:
        await record_audit(db, actor, "CATEGORY_UPDATED", MODULE, "category", category.id, before=before, after=after)
    await db.commit()
    return category


async def delete_category(db: AsyncSession, actor: Principal, category_id: uuid.UUID) -> None:
    category = await owned(db, Category, category_id, actor, "Category")
    if await db.scalar(select(Category.id).where(Category.parent_id == category.id).limit(1)):
        raise Conflict("This category has subcategories.", code="CATEGORY_IN_USE")
    if await db.scalar(select(Product.id).where(Product.category_id == category.id).limit(1)):
        raise Conflict("Products use this category. Move them or deactivate the category instead.", code="CATEGORY_IN_USE")
    await db.delete(category)
    await record_audit(db, actor, "CATEGORY_DELETED", MODULE, "category", category_id, before={"code": category.code})
    await db.commit()


async def list_brands(db: AsyncSession, actor: Principal) -> list[Brand]:
    return list(await db.scalars(select(Brand).where(Brand.company_id == actor.company_id).order_by(Brand.name)))


async def create_brand(db: AsyncSession, actor: Principal, data: s.BrandCreate) -> Brand:
    await ensure_unique(db, Brand, actor, "code", data.code)
    brand = Brand(company_id=actor.company_id, created_by=actor.user_id, **data.model_dump())
    db.add(brand)
    await db.flush()
    await record_audit(db, actor, "BRAND_CREATED", MODULE, "brand", brand.id, after=plain(data.model_dump()))
    await db.commit()
    return brand


async def update_brand(db: AsyncSession, actor: Principal, brand_id: uuid.UUID, data: s.BrandUpdate) -> Brand:
    brand = await owned(db, Brand, brand_id, actor, "Brand")
    changes = data.model_dump(exclude_unset=True)
    await ensure_unique(db, Brand, actor, "code", changes.get("code"), exclude=brand.id)
    before, after = apply_changes(brand, changes)
    brand.updated_by = actor.user_id
    if after:
        await record_audit(db, actor, "BRAND_UPDATED", MODULE, "brand", brand.id, before=before, after=after)
    await db.commit()
    return brand


async def delete_brand(db: AsyncSession, actor: Principal, brand_id: uuid.UUID) -> None:
    brand = await owned(db, Brand, brand_id, actor, "Brand")
    if await db.scalar(select(Product.id).where(Product.brand_id == brand.id).limit(1)):
        raise Conflict("Products use this brand. Deactivate it instead.", code="BRAND_IN_USE")
    await db.delete(brand)
    await record_audit(db, actor, "BRAND_DELETED", MODULE, "brand", brand_id, before={"code": brand.code})
    await db.commit()


async def list_units(db: AsyncSession, actor: Principal) -> list[Unit]:
    return list(await db.scalars(select(Unit).where(Unit.company_id == actor.company_id).order_by(Unit.code)))


async def _unit_in_use(db: AsyncSession, unit_id: uuid.UUID) -> bool:
    checks = (
        select(Product.id).where(Product.base_unit_id == unit_id),
        select(UnitConversion.id).where(UnitConversion.unit_id == unit_id),
        select(ProductBarcode.id).where(ProductBarcode.unit_id == unit_id),
        select(ProductPrice.id).where(ProductPrice.unit_id == unit_id),
    )
    for query in checks:
        if await db.scalar(query.limit(1)):
            return True
    return False


async def create_unit(db: AsyncSession, actor: Principal, data: s.UnitCreate) -> Unit:
    await ensure_unique(db, Unit, actor, "code", data.code)
    unit = Unit(company_id=actor.company_id, created_by=actor.user_id, **data.model_dump())
    db.add(unit)
    await db.flush()
    await record_audit(db, actor, "UNIT_CREATED", MODULE, "unit", unit.id, after=plain(data.model_dump()))
    await db.commit()
    return unit


async def update_unit(db: AsyncSession, actor: Principal, unit_id: uuid.UUID, data: s.UnitUpdate) -> Unit:
    unit = await owned(db, Unit, unit_id, actor, "Unit")
    changes = data.model_dump(exclude_unset=True)
    await ensure_unique(db, Unit, actor, "code", changes.get("code"), exclude=unit.id)
    if ("dimension" in changes and changes["dimension"] != unit.dimension) and await _unit_in_use(db, unit.id):
        raise Conflict("The dimension of a unit in use cannot change.", code="UNIT_IN_USE")
    before, after = apply_changes(unit, changes)
    unit.updated_by = actor.user_id
    if after:
        await record_audit(db, actor, "UNIT_UPDATED", MODULE, "unit", unit.id, before=before, after=after)
    await db.commit()
    return unit


async def delete_unit(db: AsyncSession, actor: Principal, unit_id: uuid.UUID) -> None:
    unit = await owned(db, Unit, unit_id, actor, "Unit")
    if await _unit_in_use(db, unit.id):
        raise Conflict("This unit is used by products, barcodes or prices. Deactivate it instead.", code="UNIT_IN_USE")
    await db.delete(unit)
    await record_audit(db, actor, "UNIT_DELETED", MODULE, "unit", unit_id, before={"code": unit.code})
    await db.commit()


