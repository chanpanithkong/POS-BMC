"""Prices: resolution, effective-dated changes, history and bulk updates (PRC; Phase 3).

Resolution order for a product unit at a moment (FR-PRC-002):
  1. customer-group price (from Phase 6, when customer groups exist)
  2. branch price on the Retail list (when branch pricing is enabled)
  3. company Retail price
If the unit has no price of its own, the base-unit price times the unit factor is used.
Promotions (Phase 7) apply on top of the resolved price.

A price row is never edited once it takes effect. Setting a new price closes the
current row at the new start time and inserts a new row, so history is complete.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, ValidationFailed
from app.models import Branch, Company, PriceChange, PriceList, Product, ProductPrice, UnitConversion, User
from app.schemas.catalog import BulkPriceInput, PriceCreate
from app.services.common import owned, record_audit
from app.services.principal import Principal

CLOCK_SKEW = timedelta(minutes=1)
CENT = Decimal("0.01")


@dataclass
class Resolved:
    price: Decimal | None
    source: str | None


def now() -> datetime:
    return datetime.now(UTC)


async def price_list(db: AsyncSession, company_id: uuid.UUID, code: str) -> PriceList:
    found = await db.scalar(select(PriceList).where(PriceList.company_id == company_id, PriceList.code == code))
    if found is None:
        raise AppError(f"The {code} price list is missing.", code="CONFIGURATION_ERROR", status_code=500)
    return found


def _active_at(at: datetime):
    return and_(ProductPrice.effective_from <= at, or_(ProductPrice.effective_to.is_(None), ProductPrice.effective_to > at))


async def _row_price(db: AsyncSession, product_id: uuid.UUID, unit_id: uuid.UUID, list_id: uuid.UUID, branch_id: uuid.UUID | None, group_id: uuid.UUID | None, at: datetime) -> Decimal | None:
    query = select(ProductPrice.price).where(
        ProductPrice.product_id == product_id, ProductPrice.unit_id == unit_id, ProductPrice.price_list_id == list_id, _active_at(at),
        ProductPrice.branch_id.is_(None) if branch_id is None else ProductPrice.branch_id == branch_id,
        ProductPrice.customer_group_id.is_(None) if group_id is None else ProductPrice.customer_group_id == group_id,
    )
    return await db.scalar(query.limit(1))


async def unit_factor(db: AsyncSession, product: Product, unit_id: uuid.UUID) -> Decimal | None:
    if unit_id == product.base_unit_id:
        return Decimal("1")
    return await db.scalar(select(UnitConversion.factor).where(UnitConversion.product_id == product.id, UnitConversion.unit_id == unit_id))


async def list_price(db: AsyncSession, product: Product, code: str, *, at: datetime | None = None) -> Decimal | None:
    """Company-level price on a list for the base unit (used for product views)."""
    plist = await price_list(db, product.company_id, code)
    return await _row_price(db, product.id, product.base_unit_id, plist.id, None, None, at or now())


async def resolve(db: AsyncSession, product: Product, unit_id: uuid.UUID, *, branch_id: uuid.UUID | None = None, customer_group_id: uuid.UUID | None = None, at: datetime | None = None) -> Resolved:
    at = at or now()
    factor = await unit_factor(db, product, unit_id)
    if factor is None:
        raise ValidationFailed("unit_id", "This unit is not set up for the product.")
    company = await db.get(Company, product.company_id)
    branch_pricing = bool(company and (company.settings or {}).get("branch_pricing_enabled", True))
    retail = await price_list(db, product.company_id, "RETAIL")
    candidates: list[tuple[str, uuid.UUID, uuid.UUID | None, uuid.UUID | None]] = []
    if customer_group_id:
        group_lists = await db.scalars(select(PriceList.id).where(PriceList.company_id == product.company_id, PriceList.type == "GROUP", PriceList.status == "ACTIVE"))
        candidates += [("CUSTOMER_GROUP", lid, None, customer_group_id) for lid in group_lists]
    if branch_id and branch_pricing:
        candidates.append(("BRANCH", retail.id, branch_id, None))
    candidates.append(("RETAIL", retail.id, None, None))
    for source, list_id, scope_branch, group in candidates:
        price = await _row_price(db, product.id, unit_id, list_id, scope_branch, group, at)
        if price is not None:
            return Resolved(price, source)
        if unit_id != product.base_unit_id:
            base = await _row_price(db, product.id, product.base_unit_id, list_id, scope_branch, group, at)
            if base is not None:
                return Resolved((base * factor).quantize(Decimal("0.0001"), ROUND_HALF_UP), f"{source}_BASE_UNIT")
    return Resolved(None, None)


async def _scope_label(db: AsyncSession, plist: PriceList, branch_id: uuid.UUID | None, group_id: uuid.UUID | None) -> str:
    label = plist.name
    if branch_id:
        branch = await db.get(Branch, branch_id)
        label += f" / {branch.name_en if branch else branch_id}"
    if group_id:
        label += f" / group {group_id}"
    return label


async def _check_min_price(db: AsyncSession, product: Product, unit_id: uuid.UUID, price: Decimal) -> None:
    if product.min_selling_price is None:
        return
    factor = await unit_factor(db, product, unit_id) or Decimal("1")
    floor = product.min_selling_price * factor
    if price < floor:
        raise ValidationFailed("price", f"Price is below the minimum selling price ({floor.normalize()}).")


async def set_price(
    db: AsyncSession, actor: Principal, product: Product, *, price: Decimal, unit_id: uuid.UUID | None = None, list_code: str | None = None, price_list_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None, customer_group_id: uuid.UUID | None = None, effective_from: datetime | None = None, effective_to: datetime | None = None,
) -> ProductPrice | None:
    """Starts a new price for one scope. Caller holds a lock on the product row and commits. Returns None when unchanged."""
    unit_id = unit_id or product.base_unit_id
    if await unit_factor(db, product, unit_id) is None:
        raise ValidationFailed("unit_id", "This unit is not set up for the product.")
    if customer_group_id is not None:
        raise ValidationFailed("customer_group_id", "Customer-group prices arrive with customers (Phase 6).")
    plist = await owned(db, PriceList, price_list_id, actor, "Price list") if price_list_id else await price_list(db, actor.company_id, list_code or "RETAIL")
    if plist.status != "ACTIVE":
        raise ValidationFailed("price_list_id", "This price list is inactive.")
    if branch_id is not None:
        await owned(db, Branch, branch_id, actor, "Branch")
        actor.assert_branch(branch_id)
        company = await db.get(Company, actor.company_id)
        if not (company and (company.settings or {}).get("branch_pricing_enabled", True)):
            raise ValidationFailed("branch_id", "Branch pricing is turned off in settings.")
    start = effective_from or now()
    if start < now() - CLOCK_SKEW:
        raise ValidationFailed("effective_from", "Prices cannot be backdated.")
    if effective_to is not None and effective_to <= start:
        raise ValidationFailed("effective_to", "The end must be after the start.")
    await _check_min_price(db, product, unit_id, price)

    scope = [
        ProductPrice.product_id == product.id, ProductPrice.unit_id == unit_id, ProductPrice.price_list_id == plist.id,
        ProductPrice.branch_id.is_(None) if branch_id is None else ProductPrice.branch_id == branch_id,
        ProductPrice.customer_group_id.is_(None),
    ]
    overlapping = list(await db.scalars(
        select(ProductPrice).where(*scope, or_(ProductPrice.effective_to.is_(None), ProductPrice.effective_to > start), *([ProductPrice.effective_from < effective_to] if effective_to else []))
        .order_by(ProductPrice.effective_from).with_for_update()
    ))
    current = None
    for row in overlapping:
        if row.effective_from >= start:
            raise Conflict(f"A price is already scheduled from {row.effective_from:%Y-%m-%d %H:%M} UTC. Remove it first.", code="PRICE_SCHEDULE_CONFLICT")
        if effective_to is not None and (row.effective_to is None or row.effective_to > effective_to):
            raise Conflict("A temporary price inside an existing price period is a promotion; use Promotions instead.", code="PRICE_SCHEDULE_CONFLICT")
        current = row
    if current is not None and current.price == price and effective_to is None and current.effective_to is None:
        return None
    if current is not None:
        current.effective_to = start
    row = ProductPrice(
        company_id=actor.company_id, product_id=product.id, unit_id=unit_id, price_list_id=plist.id, branch_id=branch_id,
        price=price, effective_from=start, effective_to=effective_to, created_by=actor.user_id,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:  # the EXCLUDE constraint is the final guard against overlaps
        raise Conflict("This price overlaps another price for the same scope.", code="PRICE_SCHEDULE_CONFLICT") from exc
    label = await _scope_label(db, plist, branch_id, None)
    db.add(PriceChange(company_id=actor.company_id, product_id=product.id, price_id=row.id, scope=label, old_price=current.price if current else None, new_price=price,
                       effective_from=start, user_id=actor.user_id, user_name=actor.full_name))
    await record_audit(db, actor, "PRICE_CHANGED", "PRC", "product", product.id, before={"scope": label, "price": str(current.price)} if current else None,
                       after={"scope": label, "price": str(price), "effective_from": start.isoformat()}, branch_id=branch_id)
    return row


async def _locked_product(db: AsyncSession, actor: Principal, product_id: uuid.UUID) -> Product:
    return await owned(db, Product, product_id, actor, "Product", lock=True)


async def create_price(db: AsyncSession, actor: Principal, data: PriceCreate) -> dict:
    product = await _locked_product(db, actor, data.product_id)
    row = await set_price(db, actor, product, price=data.price, unit_id=data.unit_id, price_list_id=data.price_list_id, branch_id=data.branch_id,
                          customer_group_id=data.customer_group_id, effective_from=data.effective_from, effective_to=data.effective_to)
    if row is None:
        raise Conflict("This is already the current price.", code="NO_CHANGE")
    await db.commit()
    return (await list_prices(db, actor, price_id=row.id))[0]


async def delete_price(db: AsyncSession, actor: Principal, price_id: uuid.UUID) -> None:
    """Only a price that has not started can be removed; the price it replaced is reopened."""
    row = await owned(db, ProductPrice, price_id, actor, "Price")
    product = await _locked_product(db, actor, row.product_id)
    actor.assert_branch(row.branch_id)
    if row.effective_from <= now():
        raise Conflict("This price is already in effect. Set a new price instead.", code="PRICE_IN_EFFECT")
    previous = await db.scalar(select(ProductPrice).where(
        ProductPrice.product_id == row.product_id, ProductPrice.unit_id == row.unit_id, ProductPrice.price_list_id == row.price_list_id,
        ProductPrice.branch_id.is_(None) if row.branch_id is None else ProductPrice.branch_id == row.branch_id,
        ProductPrice.customer_group_id.is_(None), ProductPrice.effective_to == row.effective_from,
    ).with_for_update())
    plist = await db.get(PriceList, row.price_list_id)
    assert plist is not None
    label = await _scope_label(db, plist, row.branch_id, None)
    db.add(PriceChange(company_id=actor.company_id, product_id=product.id, price_id=None, scope=label + " (scheduled price removed)", old_price=row.price,
                       new_price=previous.price if previous else None, effective_from=row.effective_from, user_id=actor.user_id, user_name=actor.full_name))
    await db.delete(row)
    await db.flush()
    if previous is not None:
        previous.effective_to = row.effective_to
    await record_audit(db, actor, "SCHEDULED_PRICE_REMOVED", "PRC", "product", product.id, before={"scope": label, "price": str(row.price), "effective_from": row.effective_from.isoformat()}, branch_id=row.branch_id)
    await db.commit()


async def list_prices(db: AsyncSession, actor: Principal, *, product_id: uuid.UUID | None = None, price_list_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None,
                      current_only: bool = False, price_id: uuid.UUID | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    query = (
        select(ProductPrice, Product.sku, Product.name_en, PriceList, User.full_name)
        .join(Product, Product.id == ProductPrice.product_id).join(PriceList, PriceList.id == ProductPrice.price_list_id)
        .outerjoin(User, User.id == ProductPrice.created_by)
        .where(ProductPrice.company_id == actor.company_id, Product.deleted_at.is_(None))
    )
    for column, value in ((ProductPrice.id, price_id), (ProductPrice.product_id, product_id), (ProductPrice.price_list_id, price_list_id), (ProductPrice.branch_id, branch_id)):
        if value is not None:
            query = query.where(column == value)
    if actor.branch_ids is not None:
        query = query.where(ProductPrice.branch_id.is_(None) | ProductPrice.branch_id.in_(actor.branch_ids))
    if current_only:
        query = query.where(or_(ProductPrice.effective_to.is_(None), ProductPrice.effective_to > now()))
    rows = await db.execute(query.order_by(Product.sku, ProductPrice.effective_from.desc()).limit(limit).offset(offset))
    out = []
    for price, sku, name, plist, user_name in rows:
        out.append({
            **{f: getattr(price, f) for f in ("id", "product_id", "unit_id", "price_list_id", "branch_id", "customer_group_id", "price", "effective_from", "effective_to")},
            "created_by": user_name or "System", "sku": sku, "product_name": name, "scope_label": await _scope_label(db, plist, price.branch_id, price.customer_group_id),
        })
    return out


async def history(db: AsyncSession, actor: Principal, product_id: uuid.UUID | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    query = select(PriceChange, Product.sku, Product.name_en).join(Product, Product.id == PriceChange.product_id).where(PriceChange.company_id == actor.company_id)
    if product_id:
        query = query.where(PriceChange.product_id == product_id)
    rows = await db.execute(query.order_by(PriceChange.at.desc(), PriceChange.id.desc()).limit(limit).offset(offset))
    return [{**{f: getattr(c, f) for f in ("id", "product_id", "scope", "old_price", "new_price", "effective_from", "user_name", "at", "approved_by")}, "sku": sku, "product_name": name} for c, sku, name in rows]


# Bulk updates (FR-PRC-004)

async def _bulk_rows(db: AsyncSession, actor: Principal, data: BulkPriceInput) -> list[dict]:
    if data.category_id is None and data.brand_id is None:
        raise ValidationFailed("category_id", "Choose a category or a brand.")
    if data.mode == "PERCENT" and not Decimal("-90") <= data.value <= Decimal("1000"):
        raise ValidationFailed("value", "A percentage change must be between -90 and 1000.")
    query = select(Product).where(Product.company_id == actor.company_id, Product.deleted_at.is_(None), Product.type != "VARIANT_PARENT", Product.status != "DISCONTINUED")
    if data.category_id:
        query = query.where(Product.category_id == data.category_id)
    if data.brand_id:
        query = query.where(Product.brand_id == data.brand_id)
    rows = []
    for product in await db.scalars(query.order_by(Product.sku)):
        current = await list_price(db, product, "RETAIL")
        if current is None:
            continue
        new = current * (1 + data.value / 100) if data.mode == "PERCENT" else current + data.value
        new = max(new, Decimal("0")).quantize(CENT, ROUND_HALF_UP)
        margin = None
        if actor.sees_cost and product.avg_cost > 0 and new > 0:
            margin = ((new - product.avg_cost) / new * 100).quantize(CENT, ROUND_HALF_UP)
        below = product.min_selling_price is not None and new < product.min_selling_price
        rows.append({"product": product, "product_id": product.id, "sku": product.sku, "product_name": product.name_en, "current_price": current, "new_price": new, "margin_pct": margin, "below_min": below})
    return rows


async def bulk_preview(db: AsyncSession, actor: Principal, data: BulkPriceInput) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "product"} for r in await _bulk_rows(db, actor, data)]


async def bulk_apply(db: AsyncSession, actor: Principal, data: BulkPriceInput) -> dict:
    rows = await _bulk_rows(db, actor, data)
    below = [r["sku"] for r in rows if r["below_min"]]
    if below:
        raise AppError("Some new prices are below the minimum selling price.", code="VALIDATION_ERROR", status_code=422,
                       details=[{"field": "value", "message": f"{sku} would be below its minimum selling price."} for sku in below[:50]])
    start = data.effective_from or now()
    updated = 0
    for r in rows:
        product = await _locked_product(db, actor, r["product_id"])
        if await set_price(db, actor, product, price=r["new_price"], list_code="RETAIL", effective_from=start) is not None:
            updated += 1
    await record_audit(db, actor, "BULK_PRICE_CHANGE", "PRC", "price_list", "RETAIL", after={**{k: str(v) for k, v in data.model_dump().items()}, "updated": updated})
    await db.commit()
    return {"updated": updated, "scheduled": start > now() + CLOCK_SKEW}


async def resolve_for(db: AsyncSession, actor: Principal, product_id: uuid.UUID, unit_id: uuid.UUID | None, branch_id: uuid.UUID | None) -> dict:
    product = await owned(db, Product, product_id, actor, "Product")
    if branch_id:
        actor.assert_branch(branch_id)
    unit = unit_id or product.base_unit_id
    result = await resolve(db, product, unit, branch_id=branch_id)
    return {"product_id": product.id, "unit_id": unit, "branch_id": branch_id, "price": result.price, "source": result.source}


