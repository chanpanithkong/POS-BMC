"""Customers, customer groups, store credit and loyalty (CUS; Phase 6).

Personal data (phone, email, address, notes) is masked for users without
customers.personal_data.view (BR-CUS-001). Anonymising a customer removes personal
data but keeps their sales, which still reference the record.
"""

import re
import uuid
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, Conflict, ValidationFailed
from app.models import Company, Customer, CustomerGroup, PriceList, Sale, StoreCreditEntry
from app.schemas import purchasing as s
from app.services.common import apply_changes, ensure_unique, next_number, num, owned, plain, record_audit
from app.services.principal import Principal

PERSONAL = ("phone", "email", "address", "notes")


def normalise_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return "0" + digits[3:] if digits.startswith("855") else digits


def _mask(value: str) -> str:
    return "" if not value else value[:2] + "•" * max(len(value) - 4, 2) + value[-2:]


async def customer_view(db: AsyncSession, actor: Principal, c: Customer) -> dict:
    await db.refresh(c)
    group = await db.get(CustomerGroup, c.group_id) if c.group_id else None
    view = {f: getattr(c, f) for f in ("id", "code", "name", "phone", "email", "address", "group_id", "notes", "consent_marketing", "loyalty_points", "tier", "store_credit",
                                         "credit_limit", "last_purchase_at", "total_spent", "status", "anonymized", "created_at")}
    view["group_name"] = group.name if group else None
    if not actor.can("customers.personal_data.view"):
        view.update(phone=_mask(c.phone), email=_mask(c.email), address="", notes="")
    return view


async def list_customers(db: AsyncSession, actor: Principal, *, q: str | None, group_id: uuid.UUID | None, status: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
    query = select(Customer).where(Customer.company_id == actor.company_id)
    if q:
        like = f"%{q.lower()}%"
        phone = normalise_phone(q)
        query = query.where(or_(func.lower(Customer.name).like(like), func.lower(Customer.code).like(like), *( [Customer.phone_normalised.like(f"%{phone}%")] if len(phone) >= 3 else [])))
    if group_id:
        query = query.where(Customer.group_id == group_id)
    if status:
        query = query.where(Customer.status == status)
    total = int(await db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = await db.scalars(query.order_by(Customer.name).limit(limit).offset(offset))
    return [await customer_view(db, actor, c) for c in rows], total


async def _group(db: AsyncSession, actor: Principal, group_id: uuid.UUID | None) -> None:
    if group_id is not None:
        group = await owned(db, CustomerGroup, group_id, actor, "Customer group")
        if group.status != "ACTIVE":
            raise ValidationFailed("group_id", "This customer group is inactive.")


async def create_customer(db: AsyncSession, actor: Principal, data: s.CustomerCreate) -> dict:
    await _group(db, actor, data.group_id)
    code = (data.code or "").strip() or await next_number(db, actor.company_id, "CUSTOMER")
    await ensure_unique(db, Customer, actor, "code", code)
    values = {k: v for k, v in data.model_dump(exclude={"code"}).items() if v is not None}
    customer = Customer(company_id=actor.company_id, code=code, phone_normalised=normalise_phone(data.phone or ""), created_by=actor.user_id, **values)
    db.add(customer)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("A customer with this phone number already exists.", code="DUPLICATE", details=[{"field": "phone", "message": "Phone number already in use."}]) from exc
    await record_audit(db, actor, "CUSTOMER_CREATED", "CUS", "customer", customer.id, after={"code": code})  # personal data is not copied into the audit log
    await db.commit()
    return await customer_view(db, actor, customer)


async def get_customer(db: AsyncSession, actor: Principal, customer_id: uuid.UUID) -> Customer:
    return await owned(db, Customer, customer_id, actor, "Customer")


async def update_customer(db: AsyncSession, actor: Principal, customer_id: uuid.UUID, data: s.CustomerFields) -> dict:
    customer = await get_customer(db, actor, customer_id)
    if customer.anonymized:
        raise Conflict("An anonymised customer cannot be edited.", code="ANONYMIZED")
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k == "group_id"}
    if "group_id" in changes:
        await _group(db, actor, changes["group_id"])
    if "code" in changes:
        await ensure_unique(db, Customer, actor, "code", changes["code"], exclude=customer.id)
    if set(changes) & set(PERSONAL) and not actor.can("customers.personal_data.view"):
        raise AppError("Changing contact details needs access to personal data.", code="FORBIDDEN", status_code=403)
    if "phone" in changes:
        changes["phone_normalised"] = normalise_phone(changes["phone"] or "")
    before, after = apply_changes(customer, changes)
    customer.updated_by = actor.user_id
    try:
        await db.flush()
    except IntegrityError as exc:
        raise Conflict("A customer with this phone number already exists.", code="DUPLICATE") from exc
    if after:
        await record_audit(db, actor, "CUSTOMER_UPDATED", "CUS", "customer", customer.id, after={"fields": sorted(after)})
    await db.commit()
    return await customer_view(db, actor, customer)


async def delete_customer(db: AsyncSession, actor: Principal, customer_id: uuid.UUID) -> None:
    customer = await get_customer(db, actor, customer_id)
    if await db.scalar(select(Sale.id).where(Sale.customer_id == customer.id).limit(1)) or customer.store_credit > 0:
        raise Conflict("This customer has sales or store credit. Deactivate or anonymise instead.", code="CUSTOMER_IN_USE")
    await db.delete(customer)
    await record_audit(db, actor, "CUSTOMER_DELETED", "CUS", "customer", customer_id, before={"code": customer.code})
    await db.commit()


async def anonymize(db: AsyncSession, actor: Principal, customer_id: uuid.UUID) -> dict:
    actor.require("customers.personal_data.view")
    customer = await get_customer(db, actor, customer_id)
    if customer.store_credit > 0:
        raise Conflict("Use or refund the customer's store credit before anonymising.", code="HAS_STORE_CREDIT")
    customer.name, customer.phone, customer.phone_normalised, customer.email, customer.address, customer.notes = "Anonymised customer", "", "", "", "", ""
    customer.consent_marketing, customer.anonymized, customer.status = False, True, "INACTIVE"
    await record_audit(db, actor, "CUSTOMER_ANONYMIZED", "CUS", "customer", customer.id, after={"code": customer.code}, flagged=True)
    await db.commit()
    return await customer_view(db, actor, customer)


# Groups

async def list_groups(db: AsyncSession, actor: Principal) -> list[CustomerGroup]:
    return list(await db.scalars(select(CustomerGroup).where(CustomerGroup.company_id == actor.company_id).order_by(CustomerGroup.name)))


async def _price_list(db: AsyncSession, actor: Principal, price_list_id: uuid.UUID | None) -> None:
    if price_list_id is not None:
        plist = await owned(db, PriceList, price_list_id, actor, "Price list")
        if plist.type != "GROUP":
            raise ValidationFailed("price_list_id", "Choose a customer-group price list.")


async def create_group(db: AsyncSession, actor: Principal, data: s.GroupCreate) -> CustomerGroup:
    await ensure_unique(db, CustomerGroup, actor, "code", data.code)
    values = {k: v for k, v in data.model_dump().items() if v is not None}
    if "price_list_id" not in values:
        # Each group gets its own GROUP price list so group prices can be set right away.
        plist = PriceList(company_id=actor.company_id, code=f"GRP-{data.code}"[:30].upper(), name=f"{data.name} prices", type="GROUP", created_by=actor.user_id)
        db.add(plist)
        await db.flush()
        values["price_list_id"] = plist.id
    else:
        await _price_list(db, actor, values["price_list_id"])
    group = CustomerGroup(company_id=actor.company_id, created_by=actor.user_id, **values)
    db.add(group)
    await db.flush()
    await record_audit(db, actor, "CUSTOMER_GROUP_CREATED", "CUS", "customer_group", group.id, after=plain(values))
    await db.commit()
    await db.refresh(group)
    return group


async def update_group(db: AsyncSession, actor: Principal, group_id: uuid.UUID, data: s.GroupFields) -> CustomerGroup:
    group = await owned(db, CustomerGroup, group_id, actor, "Customer group")
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    await ensure_unique(db, CustomerGroup, actor, "code", changes.get("code"), exclude=group.id)
    if "price_list_id" in changes:
        await _price_list(db, actor, changes["price_list_id"])
    before, after = apply_changes(group, changes)
    if after:
        await record_audit(db, actor, "CUSTOMER_GROUP_UPDATED", "CUS", "customer_group", group.id, before=before, after=after)
    await db.commit()
    await db.refresh(group)
    return group


async def delete_group(db: AsyncSession, actor: Principal, group_id: uuid.UUID) -> None:
    group = await owned(db, CustomerGroup, group_id, actor, "Customer group")
    if await db.scalar(select(Customer.id).where(Customer.group_id == group.id).limit(1)):
        raise Conflict("Customers belong to this group. Move them or deactivate the group.", code="GROUP_IN_USE")
    await db.delete(group)
    await record_audit(db, actor, "CUSTOMER_GROUP_DELETED", "CUS", "customer_group", group_id, before={"code": group.code})
    await db.commit()


# Store credit and loyalty (used by sales and returns)

async def change_credit(db: AsyncSession, actor: Principal, customer: Customer, amount: Decimal, reason: str, *, sale_id: uuid.UUID | None = None, return_id: uuid.UUID | None = None) -> None:
    company = await db.get(Company, actor.company_id)
    if not (company and (company.settings or {}).get("store_credit_enabled")):
        raise ValidationFailed("method", "Store credit is turned off in settings.")
    new_balance = customer.store_credit + amount
    if new_balance < 0:
        raise ValidationFailed("amount_tendered", f"{customer.name} has only {num(customer.store_credit)} store credit.")
    customer.store_credit = new_balance
    db.add(StoreCreditEntry(company_id=actor.company_id, customer_id=customer.id, amount=amount, balance_after=new_balance, reason=reason, sale_id=sale_id, return_id=return_id, user_id=actor.user_id))
    await record_audit(db, actor, "STORE_CREDIT_CHANGED", "CUS", "customer", customer.id, after={"amount": str(amount), "balance": str(new_balance), "reason": reason})


async def record_purchase(db: AsyncSession, customer_id: uuid.UUID, total: Decimal, settings: dict) -> Decimal:
    """Updates spend and earns loyalty points on finalize. Returns the points earned."""
    customer = await db.scalar(select(Customer).where(Customer.id == customer_id).with_for_update())
    if customer is None:
        return Decimal(0)
    customer.total_spent += total
    customer.last_purchase_at = datetime.now(UTC)
    if not settings.get("loyalty_enabled"):
        return Decimal(0)
    points = (total * Decimal(str(settings.get("loyalty_points_per_usd", "1")))).quantize(Decimal(1), ROUND_DOWN)
    customer.loyalty_points += points
    return points
