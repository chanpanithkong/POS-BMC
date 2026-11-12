"""Promotions and coupons (PRM; Phase 8).

Promotions need approval by someone other than their creator before they apply. In the
POS they are applied by the server during re-pricing:
  - PRODUCT, CATEGORY and TIME_BASED promotions lower the unit price (source PROMOTION);
  - BOGO gives every second unit free as an automatic line discount;
  - ORDER promotions and coupons become the order discount.
A manual discount entered by the cashier always wins over an automatic one. The best
promotion is chosen by priority, then by value to the customer. Usage limits are checked
again and counted when the sale is finalized.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, InvalidStateTransition, NotFound, ValidationFailed
from app.models import Branch, Company, Coupon, Product, Promotion, Sale
from app.schemas import extras as s
from app.services.approvals import SodViolation
from app.services.common import ensure_unique, plain, record_audit
from app.services.principal import Principal

CENT = Decimal("0.01")


def _today(branch: Branch | None) -> datetime:
    return datetime.now(UTC).astimezone(ZoneInfo(branch.timezone if branch else "Asia/Phnom_Penh"))


def promotion_view(p: Promotion, user_names: dict) -> dict:
    status = "EXPIRED" if p.status == "ACTIVE" and p.end_date < datetime.now(UTC).date() else p.status
    return {
        **{f: getattr(p, f) for f in ("id", "code", "name", "type", "discount_pct", "discount_amount", "start_date", "end_date", "start_time", "end_time", "priority", "combinable",
                                      "usage_limit", "usage_count")},
        "product_ids": p.product_ids or [], "category_ids": p.category_ids or [], "branch_ids": p.branch_ids or [], "customer_group_ids": p.customer_group_ids or [],
        "status": status, "created_by": user_names.get(p.created_by, ""), "approved_by": p.approved_by_name,
    }


async def _names(db: AsyncSession) -> dict:
    from app.models import User

    return {u.id: u.full_name for u in await db.scalars(select(User))}


async def list_promotions(db: AsyncSession, actor: Principal) -> list[dict]:
    names = await _names(db)
    return [promotion_view(p, names) for p in await db.scalars(select(Promotion).where(Promotion.company_id == actor.company_id).order_by(Promotion.start_date.desc()))]


def _validate(values: dict) -> None:
    if values.get("start_date") and values.get("end_date") and values["end_date"] < values["start_date"]:
        raise ValidationFailed("end_date", "End date must be on or after the start date.")
    if bool(values.get("start_time")) != bool(values.get("end_time")):
        raise ValidationFailed("end_time", "Give both a start and an end time, or neither.")
    if values.get("type") != "BOGO" and not (values.get("discount_pct") or values.get("discount_amount")):
        raise ValidationFailed("discount_pct", "Give a discount percentage or amount.")
    if values.get("type") in ("PRODUCT", "BOGO") and not values.get("product_ids") and not values.get("category_ids"):
        raise ValidationFailed("product_ids", "Choose the products (or categories) this promotion applies to.")
    if values.get("type") == "CATEGORY" and not values.get("category_ids"):
        raise ValidationFailed("category_ids", "Choose the categories this promotion applies to.")


FIELDS = ("code", "name", "type", "discount_pct", "discount_amount", "product_ids", "category_ids", "branch_ids", "customer_group_ids", "start_date", "end_date", "start_time",
          "end_time", "priority", "combinable", "usage_limit")


def _clean(data: s.PromotionIn, *, partial: bool) -> dict:
    values = data.model_dump(include=set(FIELDS), exclude_unset=partial)
    for key in ("product_ids", "category_ids", "branch_ids", "customer_group_ids"):
        if key in values:
            values[key] = [str(x) for x in (values[key] or [])]
    return values


async def create_promotion(db: AsyncSession, actor: Principal, data: s.PromotionIn) -> dict:
    values = _clean(data, partial=False)
    for required in ("code", "name", "type", "start_date", "end_date"):
        if not values.get(required):
            raise ValidationFailed(required, "This field is required.")
    values = {k: v for k, v in values.items() if v is not None} | {"discount_pct": values.get("discount_pct") or Decimal(0), "discount_amount": values.get("discount_amount") or Decimal(0)}
    _validate(values)
    await ensure_unique(db, Promotion, actor, "code", values["code"])
    p = Promotion(company_id=actor.company_id, status="PENDING_APPROVAL", created_by=actor.user_id, **values)
    db.add(p)
    await db.flush()
    await record_audit(db, actor, "PROMOTION_CREATED", "PRM", "promotion", p.id, after=plain({k: v for k, v in values.items() if k in ("code", "type", "discount_pct", "discount_amount")}))
    await db.commit()
    await db.refresh(p)
    return promotion_view(p, await _names(db))


async def _get(db: AsyncSession, actor: Principal, promotion_id: uuid.UUID) -> Promotion:
    p = await db.scalar(select(Promotion).where(Promotion.id == promotion_id, Promotion.company_id == actor.company_id).with_for_update())
    if p is None:
        raise NotFound("Promotion")
    return p


async def update_promotion(db: AsyncSession, actor: Principal, promotion_id: uuid.UUID, data: s.PromotionIn) -> dict:
    p = await _get(db, actor, promotion_id)
    changes = {k: v for k, v in _clean(data, partial=True).items() if v is not None or k in ("start_time", "end_time", "usage_limit")}
    merged = {f: getattr(p, f) for f in FIELDS} | changes
    _validate(merged)
    await ensure_unique(db, Promotion, actor, "code", changes.get("code"), exclude=p.id)
    for k, v in changes.items():
        setattr(p, k, v)
    # Any change needs approval again.
    p.status, p.approved_by_name, p.updated_by = "PENDING_APPROVAL", None, actor.user_id
    await record_audit(db, actor, "PROMOTION_UPDATED", "PRM", "promotion", p.id, after={"fields": sorted(changes)})
    await db.commit()
    await db.refresh(p)
    return promotion_view(p, await _names(db))


async def promotion_action(db: AsyncSession, actor: Principal, promotion_id: uuid.UUID, verb: str) -> dict:
    p = await _get(db, actor, promotion_id)
    flagged = False
    if verb == "approve":
        if p.status != "PENDING_APPROVAL":
            raise InvalidStateTransition("Only a pending promotion can be approved.")
        if p.created_by == actor.user_id:
            company = await db.get(Company, actor.company_id)
            if not (company and (company.settings or {}).get("reduced_sod_mode")):
                raise SodViolation("You cannot approve your own promotion.")
            flagged = True
        p.status, p.approved_by_name = "ACTIVE", actor.full_name
    elif verb == "disable":
        p.status = "DISABLED"
    else:
        raise NotFound("Action")
    await record_audit(db, actor, f"PROMOTION_{verb.upper()}D", "PRM", "promotion", p.id, after={"code": p.code, "status": p.status}, flagged=flagged)
    await db.commit()
    await db.refresh(p)
    return promotion_view(p, await _names(db))


async def delete_promotion(db: AsyncSession, actor: Principal, promotion_id: uuid.UUID) -> None:
    p = await _get(db, actor, promotion_id)
    if p.usage_count > 0:
        raise Conflict("A promotion that has been used cannot be deleted. Disable it instead.", code="IN_USE")
    await db.delete(p)
    await record_audit(db, actor, "PROMOTION_DELETED", "PRM", "promotion", promotion_id, before={"code": p.code})
    await db.commit()


# Coupons

COUPON_FIELDS = ("code", "description", "discount_pct", "discount_amount", "min_spend", "start_date", "end_date", "usage_limit", "per_customer_limit", "status")


async def list_coupons(db: AsyncSession, actor: Principal) -> list[Coupon]:
    return list(await db.scalars(select(Coupon).where(Coupon.company_id == actor.company_id).order_by(Coupon.code)))


def _coupon_check(values: dict) -> None:
    if values.get("start_date") and values.get("end_date") and values["end_date"] < values["start_date"]:
        raise ValidationFailed("end_date", "End date must be on or after the start date.")
    if not (values.get("discount_pct") or values.get("discount_amount")):
        raise ValidationFailed("discount_pct", "Give a discount percentage or amount.")


async def create_coupon(db: AsyncSession, actor: Principal, data: s.CouponIn) -> Coupon:
    values = {k: v for k, v in data.model_dump(include=set(COUPON_FIELDS)).items() if v is not None}
    for required in ("code", "start_date", "end_date"):
        if not values.get(required):
            raise ValidationFailed(required, "This field is required.")
    values["code"] = values["code"].upper()
    _coupon_check(values)
    if await db.scalar(select(Coupon.id).where(Coupon.company_id == actor.company_id, func.upper(Coupon.code) == values["code"])):
        raise Conflict("This coupon code already exists.", code="DUPLICATE")
    c = Coupon(company_id=actor.company_id, created_by=actor.user_id, **values)
    db.add(c)
    await db.flush()
    await record_audit(db, actor, "COUPON_CREATED", "PRM", "coupon", c.id, after=plain({k: values.get(k) for k in ("code", "discount_pct", "discount_amount", "usage_limit")}))
    await db.commit()
    await db.refresh(c)
    return c


async def update_coupon(db: AsyncSession, actor: Principal, coupon_id: uuid.UUID, data: s.CouponIn) -> Coupon:
    c = await db.scalar(select(Coupon).where(Coupon.id == coupon_id, Coupon.company_id == actor.company_id).with_for_update())
    if c is None:
        raise NotFound("Coupon")
    changes = {k: v for k, v in data.model_dump(include=set(COUPON_FIELDS), exclude_unset=True).items() if v is not None}
    if "code" in changes:
        changes["code"] = changes["code"].upper()
        if await db.scalar(select(Coupon.id).where(Coupon.company_id == actor.company_id, func.upper(Coupon.code) == changes["code"], Coupon.id != c.id)):
            raise Conflict("This coupon code already exists.", code="DUPLICATE")
    _coupon_check({f: getattr(c, f) for f in COUPON_FIELDS} | changes)
    for k, v in changes.items():
        setattr(c, k, v)
    await record_audit(db, actor, "COUPON_UPDATED", "PRM", "coupon", c.id, after={"fields": sorted(changes)})
    await db.commit()
    await db.refresh(c)
    return c


async def delete_coupon(db: AsyncSession, actor: Principal, coupon_id: uuid.UUID) -> None:
    c = await db.scalar(select(Coupon).where(Coupon.id == coupon_id, Coupon.company_id == actor.company_id))
    if c is None:
        raise NotFound("Coupon")
    if c.usage_count > 0:
        raise Conflict("A redeemed coupon cannot be deleted. Deactivate it instead.", code="IN_USE")
    await db.delete(c)
    await record_audit(db, actor, "COUPON_DELETED", "PRM", "coupon", coupon_id, before={"code": c.code})
    await db.commit()


# POS application

def _applies(p: Promotion, product: Product, branch_id: uuid.UUID, group_id: uuid.UUID | None, now: datetime) -> bool:
    today = now.date()
    if p.status != "ACTIVE" or today < p.start_date or today > p.end_date:
        return False
    if p.start_time and p.end_time and not (p.start_time <= now.time().replace(tzinfo=None) <= p.end_time):
        return False
    if p.branch_ids and str(branch_id) not in p.branch_ids:
        return False
    if p.customer_group_ids and (group_id is None or str(group_id) not in p.customer_group_ids):
        return False
    if p.usage_limit is not None and p.usage_count >= p.usage_limit:
        return False
    if p.type == "ORDER":
        return False
    by_product = str(product.id) in (p.product_ids or [])
    by_category = str(product.category_id) in (p.category_ids or [])
    return by_product or by_category or (p.type == "TIME_BASED" and not p.product_ids and not p.category_ids)


async def active_promotions(db: AsyncSession, company_id: uuid.UUID) -> list[Promotion]:
    today = datetime.now(UTC).date()
    return list(await db.scalars(select(Promotion).where(Promotion.company_id == company_id, Promotion.status == "ACTIVE", Promotion.start_date <= today, Promotion.end_date >= today)))


def best_for(promos: list[Promotion], product: Product, branch_id: uuid.UUID, group_id: uuid.UUID | None, now: datetime, base: Decimal) -> Promotion | None:
    def value(p: Promotion) -> Decimal:
        return base / 2 if p.type == "BOGO" else base * p.discount_pct / 100 + p.discount_amount

    candidates = [p for p in promos if _applies(p, product, branch_id, group_id, now)]
    candidates.sort(key=lambda p: (-p.priority, -value(p)))
    return candidates[0] if candidates else None


async def order_discount(db: AsyncSession, sale: Sale, promos: list[Promotion], now: datetime) -> dict | None:
    if sale.coupon_code:
        coupon = await db.scalar(select(Coupon).where(Coupon.company_id == sale.company_id, func.upper(Coupon.code) == sale.coupon_code.upper()))
        if coupon is not None:
            kind, value = ("PERCENT", coupon.discount_pct) if coupon.discount_pct else ("AMOUNT", coupon.discount_amount)
            return {"type": kind, "value": str(value), "reason": f"Coupon {coupon.code}", "source": "COUPON", "approved_by": None, "coupon_id": str(coupon.id)}
    today = now.date()
    candidates = [p for p in promos if p.type == "ORDER" and p.status == "ACTIVE" and p.start_date <= today <= p.end_date and (not p.branch_ids or str(sale.branch_id) in p.branch_ids)
                  and (p.usage_limit is None or p.usage_count < p.usage_limit)]
    candidates.sort(key=lambda p: -p.priority)
    if not candidates:
        return None
    p = candidates[0]
    kind, value = ("PERCENT", p.discount_pct) if p.discount_pct else ("AMOUNT", p.discount_amount)
    return {"type": kind, "value": str(value), "reason": p.name, "source": "PROMOTION", "approved_by": None, "promotion_id": str(p.id)}


async def validate_coupon(db: AsyncSession, sale: Sale, code: str, subtotal: Decimal) -> Coupon:
    coupon = await db.scalar(select(Coupon).where(Coupon.company_id == sale.company_id, func.upper(Coupon.code) == code.strip().upper(), Coupon.status == "ACTIVE"))
    branch = await db.get(Branch, sale.branch_id)
    today: date = _today(branch).date()
    if coupon is None or today < coupon.start_date or today > coupon.end_date:
        raise ValidationFailed("code", "This coupon is not valid.")
    if coupon.usage_limit and coupon.usage_count >= coupon.usage_limit:
        raise AppError("This coupon has reached its usage limit.", code="PROMO_LIMIT_REACHED", status_code=422)
    if subtotal < coupon.min_spend:
        raise ValidationFailed("code", f"This coupon needs a minimum spend of {coupon.min_spend.quantize(CENT)} USD.")
    if coupon.per_customer_limit:
        if sale.customer_id is None:
            raise ValidationFailed("code", "This coupon is limited per customer: choose the customer first.")
        used = await db.scalar(select(func.count()).select_from(Sale).where(Sale.customer_id == sale.customer_id, func.upper(Sale.coupon_code) == coupon.code.upper(), Sale.status == "FINALIZED")) or 0
        if used >= coupon.per_customer_limit:
            raise AppError("This customer has already used this coupon.", code="PROMO_LIMIT_REACHED", status_code=422)
    return coupon


async def count_usage(db: AsyncSession, sale: Sale, promotion_ids: set[uuid.UUID]) -> None:
    """At finalize: lock and count promotion and coupon use, refusing when a limit was reached meanwhile."""
    for pid in sorted(promotion_ids, key=str):
        p = await db.scalar(select(Promotion).where(Promotion.id == pid).with_for_update())
        if p is None:
            continue
        if p.usage_limit is not None and p.usage_count >= p.usage_limit:
            raise AppError(f"Promotion {p.name} has reached its usage limit. Review the sale.", code="PROMO_LIMIT_REACHED", status_code=409)
        p.usage_count += 1
    if sale.coupon_code:
        c = await db.scalar(select(Coupon).where(Coupon.company_id == sale.company_id, func.upper(Coupon.code) == sale.coupon_code.upper()).with_for_update())
        if c is not None:
            if c.usage_limit and c.usage_count >= c.usage_limit:
                raise AppError("This coupon has reached its usage limit.", code="PROMO_LIMIT_REACHED", status_code=409)
            c.usage_count += 1


def promo_price(price: Decimal, p: Promotion, factor: Decimal) -> Decimal:
    return max(Decimal(0), (price * (1 - p.discount_pct / 100) - p.discount_amount * factor)).quantize(Decimal("0.0001"), ROUND_HALF_UP)


