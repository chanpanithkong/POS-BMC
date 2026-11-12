"""Expenses, promotions, coupons, notifications and imports schemas (frontend `misc.ts` and `catalog.ts`)."""

import datetime as dt
import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator

from app.schemas.common import Command, Out

Status = Literal["ACTIVE", "INACTIVE"]


def _blank(value: Any) -> Any:
    return None if value == "" else value


# Expenses

class ExpenseCategoryIn(Command):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: Status | None = None


class ExpenseCategoryOut(Out):
    id: uuid.UUID
    code: str
    name: str
    status: str


class ExpenseIn(Command):
    date: dt.date | None = None
    category_id: uuid.UUID | None = None
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    amount: Decimal | None = Field(default=None, gt=0, max_digits=19, decimal_places=4)
    currency: Literal["USD", "KHR"] | None = None
    payment_method: str | None = Field(default=None, max_length=30)
    branch_id: uuid.UUID | None = None
    attachment: str | None = Field(default=None, max_length=8_000_000, description="URL or data: URL (JPEG, PNG, WebP or PDF up to 5 MB)")

    _blank = field_validator("category_id", "branch_id", "attachment", mode="before")(_blank)


class ExpenseOut(Out):
    id: uuid.UUID
    expense_no: str
    date: dt.date
    category_id: uuid.UUID
    category_name: str
    description: str
    amount: Decimal
    currency: str
    amount_base: Decimal
    payment_method: str
    branch_id: uuid.UUID
    branch_name: str
    attachment: str | None
    status: str
    reject_reason: str | None
    session_id: uuid.UUID | None
    created_by: str
    created_by_id: uuid.UUID | None
    approved_by: str | None
    created_at: datetime


class ReasonIn(Command):
    reason: str | None = Field(default=None, max_length=500)


# Promotions and coupons

class PromotionIn(Command):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: Literal["PRODUCT", "CATEGORY", "BOGO", "ORDER", "TIME_BASED"] | None = None
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    discount_amount: Decimal | None = Field(default=None, ge=0)
    product_ids: list[uuid.UUID] | None = None
    category_ids: list[uuid.UUID] | None = None
    branch_ids: list[uuid.UUID] | None = None
    customer_group_ids: list[uuid.UUID] | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    start_time: time | None = None
    end_time: time | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    combinable: bool | None = None
    usage_limit: int | None = Field(default=None, ge=0)
    # Read-only fields the frontend may echo back; ignored.
    id: str | None = None
    usage_count: int | None = None
    status: str | None = None
    created_by: str | None = None
    approved_by: str | None = None

    _blank = field_validator("start_time", "end_time", mode="before")(_blank)


class PromotionOut(Out):
    id: uuid.UUID
    code: str
    name: str
    type: str
    discount_pct: Decimal
    discount_amount: Decimal
    product_ids: list[uuid.UUID]
    category_ids: list[uuid.UUID]
    branch_ids: list[uuid.UUID]
    customer_group_ids: list[uuid.UUID]
    start_date: dt.date
    end_date: dt.date
    start_time: time | None
    end_time: time | None
    priority: int
    combinable: bool
    usage_limit: int | None
    usage_count: int
    status: str
    created_by: str
    approved_by: str | None


class CouponIn(Command):
    code: str | None = Field(default=None, min_length=2, max_length=30, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=200)
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    discount_amount: Decimal | None = Field(default=None, ge=0)
    min_spend: Decimal | None = Field(default=None, ge=0)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    usage_limit: int | None = Field(default=None, ge=0)
    per_customer_limit: int | None = Field(default=None, ge=0)
    status: Status | None = None
    id: str | None = None
    usage_count: int | None = None


class CouponOut(Out):
    id: uuid.UUID
    code: str
    description: str
    discount_pct: Decimal
    discount_amount: Decimal
    min_spend: Decimal
    start_date: dt.date
    end_date: dt.date
    usage_limit: int
    usage_count: int
    per_customer_limit: int
    status: str


# Notifications

class NotificationOut(Out):
    id: uuid.UUID
    kind: str
    title: str
    message: str
    link: str | None
    read: bool
    created_at: datetime
    audience_permission: str | None
    branch_id: uuid.UUID | None


class MarkRead(Command):
    ids: list[uuid.UUID] | None = None


# Imports

ImportType = Literal["PRODUCTS", "BARCODES", "SUPPLIERS", "CUSTOMERS", "OPENING_STOCK", "PRICES", "STOCK_COUNT"]


class ImportPreviewIn(Command):
    type: ImportType
    file_name: str = Field(min_length=1, max_length=200)
    file_hash: str = Field(default="", max_length=128)
    rows: list[dict[str, str | int | float | None]] = Field(max_length=50_000)


class ImportErrorOut(Out):
    row: int
    field: str
    value: str
    message: str


class ImportPreviewOut(Out):
    type: str
    file_name: str
    total_rows: int
    valid_rows: int
    errors: list[ImportErrorOut]
    sample: list[dict[str, Any]]
    columns: list[str]
    token: str


class ImportCommit(Command):
    token: str = Field(min_length=8, max_length=64)


class ImportBatchOut(Out):
    id: uuid.UUID
    type: str
    file_name: str
    file_hash: str
    user_name: str
    at: datetime
    total_rows: int
    imported_rows: int
    status: str
    created_ids: list[str]
    can_rollback: bool
