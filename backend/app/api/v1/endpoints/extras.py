"""Expenses, promotions, coupons, notifications and imports (EXP, PRM, NTF, IMP; Phase 8)."""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Request, Response
from fastapi.responses import FileResponse

from app.api.deps import CurrentPrincipal, DbSession, require
from app.core.exceptions import NotFound
from app.schemas import extras as s
from app.schemas.auth import MessageResponse
from app.schemas.common import ListResponse, error_responses
from app.services import expenses, files, idempotency, imports, notifications, promotions
from app.services.principal import Principal

router = APIRouter()
ERR = error_responses(401, 403, 404, 409, 422)
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


def page(items: list) -> dict:
    return {"items": items, "total": len(items)}


# Expenses

ExpenseViewer = Annotated[Principal, Depends(require("expenses.expense.view", "expenses.expense.create", "expenses.expense.approve", "cash.session.open"))]
ExpenseCreator = Annotated[Principal, Depends(require("expenses.expense.create"))]
CategoryAdmin = Annotated[Principal, Depends(require("expenses.expense.approve", "settings.settings.manage"))]


@router.get("/expense-categories", response_model=ListResponse[s.ExpenseCategoryOut], tags=["Expenses"], summary="Expense categories", responses=ERR)
async def list_categories(actor: ExpenseViewer, db: DbSession) -> dict:
    return page(await expenses.list_categories(db, actor))


@router.post("/expense-categories", response_model=s.ExpenseCategoryOut, status_code=201, tags=["Expenses"], summary="Create an expense category", responses=ERR)
async def create_category(body: s.ExpenseCategoryIn, actor: CategoryAdmin, db: DbSession) -> Any:
    return await expenses.create_category(db, actor, body)


@router.patch("/expense-categories/{category_id}", response_model=s.ExpenseCategoryOut, tags=["Expenses"], summary="Update an expense category", responses=ERR)
async def update_category(category_id: uuid.UUID, body: s.ExpenseCategoryIn, actor: CategoryAdmin, db: DbSession) -> Any:
    return await expenses.update_category(db, actor, category_id, body)


@router.delete("/expense-categories/{category_id}", status_code=204, tags=["Expenses"], summary="Delete an unused expense category", responses=ERR)
async def delete_category(category_id: uuid.UUID, actor: CategoryAdmin, db: DbSession) -> Response:
    await expenses.delete_category(db, actor, category_id)
    return Response(status_code=204)


@router.get("/expenses", response_model=ListResponse[s.ExpenseOut], tags=["Expenses"], summary="Expenses in your branches", responses=ERR)
async def list_expenses(actor: Annotated[Principal, Depends(require("expenses.expense.view", "expenses.expense.create", "expenses.expense.approve"))], db: DbSession,
                        status: str | None = None, branch_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None) -> dict:
    return page(await expenses.list_expenses(db, actor, status=status, branch_id=branch_id, date_from=date_from, date_to=date_to))


@router.post("/expenses", response_model=s.ExpenseOut, status_code=201, tags=["Expenses"], summary="Record an expense", responses=ERR,
             description="Approved automatically up to the approval threshold; above it another user approves. A document is required above the attachment threshold.")
async def create_expense(body: s.ExpenseIn, actor: ExpenseCreator, db: DbSession) -> dict:
    return await expenses.create_expense(db, actor, body)


@router.patch("/expenses/{expense_id}", response_model=s.ExpenseOut, tags=["Expenses"], summary="Edit an unapproved expense", responses=ERR)
async def update_expense(expense_id: uuid.UUID, body: s.ExpenseIn, actor: ExpenseCreator, db: DbSession) -> dict:
    return await expenses.update_expense(db, actor, expense_id, body)


@router.delete("/expenses/{expense_id}", status_code=204, tags=["Expenses"], summary="Delete an unapproved expense", responses=ERR)
async def delete_expense(expense_id: uuid.UUID, actor: ExpenseCreator, db: DbSession) -> Response:
    await expenses.delete_expense(db, actor, expense_id)
    return Response(status_code=204)


@router.post("/expenses/{expense_id}/{verb}", response_model=s.ExpenseOut, tags=["Expenses"], summary="Approve or reject an expense", responses=ERR)
async def expense_action(expense_id: uuid.UUID, verb: str, actor: Annotated[Principal, Depends(require("expenses.expense.approve"))], db: DbSession,
                         body: Annotated[s.ReasonIn | None, Body()] = None) -> dict:
    if verb not in ("approve", "reject"):
        raise NotFound("Action")
    return await expenses.action(db, actor, expense_id, verb, body.reason if body else None)


@router.get("/files/expenses/{name}", tags=["Expenses"], summary="Expense attachment", responses=ERR)
async def expense_file(name: str, actor: Annotated[Principal, Depends(require("expenses.expense.view", "expenses.expense.approve", "expenses.expense.create"))]) -> FileResponse:
    path = files.stored_path("expenses", name)
    if path is None:
        raise NotFound("File")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


# Promotions and coupons

PromoViewer = Annotated[Principal, Depends(require("promotions.promotion.view", "promotions.promotion.manage"))]
PromoAdmin = Annotated[Principal, Depends(require("promotions.promotion.manage"))]


@router.get("/promotions", response_model=ListResponse[s.PromotionOut], tags=["Promotions"], summary="Promotions", responses=ERR)
async def list_promotions(actor: PromoViewer, db: DbSession) -> dict:
    return page(await promotions.list_promotions(db, actor))


@router.post("/promotions", response_model=s.PromotionOut, status_code=201, tags=["Promotions"], summary="Create a promotion (needs approval before it applies)", responses=ERR)
async def create_promotion(body: s.PromotionIn, actor: PromoAdmin, db: DbSession) -> dict:
    return await promotions.create_promotion(db, actor, body)


@router.patch("/promotions/{promotion_id}", response_model=s.PromotionOut, tags=["Promotions"], summary="Edit a promotion (sends it back for approval)", responses=ERR)
async def update_promotion(promotion_id: uuid.UUID, body: s.PromotionIn, actor: PromoAdmin, db: DbSession) -> dict:
    return await promotions.update_promotion(db, actor, promotion_id, body)


@router.post("/promotions/{promotion_id}/{verb}", response_model=s.PromotionOut, tags=["Promotions"], summary="Approve (another user) or disable a promotion", responses=ERR)
async def promotion_action(promotion_id: uuid.UUID, verb: str, actor: PromoAdmin, db: DbSession) -> dict:
    if verb not in ("approve", "disable"):
        raise NotFound("Action")
    return await promotions.promotion_action(db, actor, promotion_id, verb)


@router.delete("/promotions/{promotion_id}", status_code=204, tags=["Promotions"], summary="Delete an unused promotion", responses=ERR)
async def delete_promotion(promotion_id: uuid.UUID, actor: PromoAdmin, db: DbSession) -> Response:
    await promotions.delete_promotion(db, actor, promotion_id)
    return Response(status_code=204)


@router.get("/coupons", response_model=ListResponse[s.CouponOut], tags=["Promotions"], summary="Coupons", responses=ERR)
async def list_coupons(actor: Annotated[Principal, Depends(require("promotions.promotion.view", "promotions.promotion.manage", "pos.sale.create"))], db: DbSession) -> dict:
    return page(await promotions.list_coupons(db, actor))


@router.post("/coupons", response_model=s.CouponOut, status_code=201, tags=["Promotions"], summary="Create a coupon", responses=ERR)
async def create_coupon(body: s.CouponIn, actor: PromoAdmin, db: DbSession) -> Any:
    return await promotions.create_coupon(db, actor, body)


@router.patch("/coupons/{coupon_id}", response_model=s.CouponOut, tags=["Promotions"], summary="Update a coupon", responses=ERR)
async def update_coupon(coupon_id: uuid.UUID, body: s.CouponIn, actor: PromoAdmin, db: DbSession) -> Any:
    return await promotions.update_coupon(db, actor, coupon_id, body)


@router.delete("/coupons/{coupon_id}", status_code=204, tags=["Promotions"], summary="Delete an unused coupon", responses=ERR)
async def delete_coupon(coupon_id: uuid.UUID, actor: PromoAdmin, db: DbSession) -> Response:
    await promotions.delete_coupon(db, actor, coupon_id)
    return Response(status_code=204)


# Notifications

@router.get("/notifications", response_model=ListResponse[s.NotificationOut], tags=["Notifications"], summary="Your notifications, newest first", responses=ERR)
async def list_notifications(actor: CurrentPrincipal, db: DbSession, unread: bool = False) -> dict:
    return page(await notifications.list_for(db, actor, unread_only=unread))


@router.post("/notifications/read", response_model=MessageResponse, tags=["Notifications"], summary="Mark notifications read (all when ids is omitted)", responses=ERR)
async def mark_read(body: s.MarkRead, actor: CurrentPrincipal, db: DbSession) -> dict:
    count = await notifications.mark_read(db, actor, body.ids)
    return {"message": f"{count} notification(s) marked read."}


# Imports

ImportAdmin = Annotated[Principal, Depends(require("imports.import.manage"))]


@router.get("/imports/templates/{kind}", tags=["Imports"], summary="Columns for an import file", responses=ERR)
async def template(kind: str, actor: ImportAdmin) -> dict:
    if kind not in imports.COLUMNS:
        raise NotFound("Import type")
    return {"columns": imports.COLUMNS[kind], "required": imports.REQUIRED[kind]}


@router.post("/imports/preview", response_model=s.ImportPreviewOut, tags=["Imports"], summary="Validate a file and keep it for one hour", responses=ERR,
             description="Rows are parsed in the browser and sent as objects keyed by column name. Nothing is imported until commit.")
async def preview(body: s.ImportPreviewIn, actor: ImportAdmin, db: DbSession) -> dict:
    return await imports.preview(db, actor, body.type, body.file_name, body.file_hash, body.rows)


@router.post("/imports/commit", response_model=s.ImportBatchOut, tags=["Imports"], summary="Import every row or none (IK)", responses=ERR)
async def commit(body: s.ImportCommit, request: Request, actor: ImportAdmin, db: DbSession, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, body, lambda: imports.commit(db, actor, body.token), response_model=s.ImportBatchOut)


@router.get("/imports", response_model=ListResponse[s.ImportBatchOut], tags=["Imports"], summary="Import history", responses=ERR)
async def list_imports(actor: ImportAdmin, db: DbSession) -> dict:
    return page(await imports.list_batches(db, actor))


@router.post("/imports/{batch_id}/rollback", response_model=s.ImportBatchOut, tags=["Imports"], summary="Undo a products, suppliers or customers import while unused", responses=ERR)
async def rollback(batch_id: uuid.UUID, actor: ImportAdmin, db: DbSession) -> dict:
    return await imports.rollback(db, actor, batch_id)


