"""POS, payments, cashier sessions, sales history, receipts, returns and refunds (Phase 5).

POS requests send `X-Terminal-Id` (the registered terminal). Commands that move money or
stock require an `Idempotency-Key` header (IK) so a retried request never runs twice.
"""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.api.deps import CurrentPrincipal, DbSession, require
from app.schemas import sales as s
from app.schemas.common import ListResponse, error_responses
from app.services import cash_sessions, idempotency, returns
from app.services import sales as service
from app.services.principal import Principal

router = APIRouter(prefix="/sales", tags=["POS and sales"])
payments_router = APIRouter(prefix="/payments", tags=["Payments"])
sessions_router = APIRouter(prefix="/cashier-sessions", tags=["Cashier sessions"])
returns_router = APIRouter(tags=["Returns and refunds"])
ERR = error_responses(401, 403, 404, 409, 422)
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", description="Required: one key per command; a retry with the same key returns the first result")]
Seller = Annotated[Principal, Depends(require("pos.sale.create", "pos.sale.hold"))]
Cashier = Annotated[Principal, Depends(require("pos.sale.create"))]
Viewer = Annotated[Principal, Depends(require("sales.sale.view", "pos.sale.create", "pos.sale.hold"))]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


def page(items: list, total: int | None = None) -> dict:
    return {"items": items, "total": len(items) if total is None else total}


# Sales

@router.get("", response_model=ListResponse[s.SaleOut], summary="Sales history", responses=ERR,
            description="Without sales.sale.view_all you see your own sales, plus an exact receipt-number lookup for returns.")
async def list_sales(actor: Viewer, db: DbSession, q: str | None = None, status_filter: Annotated[str | None, Query(alias="status")] = None, branch_id: uuid.UUID | None = None,
                     terminal_id: uuid.UUID | None = None, cashier_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None, limit: Limit = 50, offset: Offset = 0) -> dict:
    items, total = await service.list_sales(db, actor, q=q, status=status_filter, branch_id=branch_id, terminal_id=terminal_id, cashier_id=cashier_id, date_from=date_from, date_to=date_to, limit=limit, offset=offset)
    return page(items, total)


@router.post("", response_model=s.SaleOut, status_code=201, summary="Start a sale on this terminal (IK)", responses=ERR)
async def create_sale(request: Request, actor: Seller, db: DbSession, body: s.SaleCreate | None = None, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, body or {}, lambda: service.create_sale(db, actor), response_model=s.SaleOut, status_code=201)


@router.get("/current", response_model=s.SaleOut | None, summary="Your open sale on this terminal, if any", responses=ERR)
async def current_sale(actor: Seller, db: DbSession) -> dict | None:
    return await service.current_sale(db, actor)


@router.get("/held", response_model=ListResponse[s.SaleOut], summary="Held sales: this terminal's branch, or the caller's branches in the back office", responses=ERR)
async def held_sales(actor: Viewer, db: DbSession, branch_id: uuid.UUID | None = None) -> dict:
    return page(await service.held_sales(db, actor, branch_id))


@router.get("/{sale_id}", response_model=s.SaleOut, summary="Sale detail", responses=ERR)
async def get_sale(sale_id: uuid.UUID, actor: Viewer, db: DbSession) -> dict:
    return await service.sale_view(db, actor, await service.get_sale(db, actor, sale_id))


@router.patch("/{sale_id}", response_model=s.SaleOut, summary="Change a sale: add, quantity, unit, remove, discounts, override, hold, resume", responses=ERR,
              description="Operations run in order in one transaction and the sale is re-priced by the server. A 403 APPROVAL_REQUIRED names the action; repeat with approval_token from /auth/approvals/verify.")
async def apply_ops(sale_id: uuid.UUID, body: s.SaleOps, actor: Seller, db: DbSession) -> dict:
    return await service.apply_ops(db, actor, sale_id, body)


@router.post("/{sale_id}/hold", response_model=s.SaleOut, summary="Hold a sale", responses=ERR)
async def hold(sale_id: uuid.UUID, actor: Annotated[Principal, Depends(require("pos.sale.hold"))], db: DbSession, label: str = "") -> dict:
    return await service.apply_ops(db, actor, sale_id, s.SaleOps(ops=[s.Hold(type="hold", label=label)]))


@router.post("/{sale_id}/resume", response_model=s.SaleOut, summary="Resume a held sale on this terminal (re-priced)", responses=ERR)
async def resume(sale_id: uuid.UUID, actor: Seller, db: DbSession) -> dict:
    return await service.apply_ops(db, actor, sale_id, s.SaleOps(ops=[s.Resume(type="resume")]))


@router.post("/{sale_id}/payments", response_model=s.SaleOut, summary="Record a payment (IK)", responses=ERR,
             description="Cash completes at once and gets change. Card completes with its approval code; QR and bank transfer complete with a reference, otherwise they stay PENDING and stock is reserved for 5 minutes.")
async def add_payment(sale_id: uuid.UUID, body: s.PaymentIn, request: Request, actor: Cashier, db: DbSession, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, body, lambda: service.add_payment(db, actor, sale_id, body), response_model=s.SaleOut)


@router.post("/{sale_id}/payments/{payment_id}/resolve", response_model=s.SaleOut, summary="Confirm, fail or cancel a pending payment", responses=ERR)
async def resolve_payment(sale_id: uuid.UUID, payment_id: uuid.UUID, body: s.PaymentResolve, actor: Cashier, db: DbSession) -> dict:
    return await service.resolve_payment(db, actor, sale_id, payment_id, body)


@router.post("/{sale_id}/finalize", response_model=s.SaleOut, summary="Finalize: deduct stock, assign the receipt number (IK)", responses=ERR)
async def finalize(sale_id: uuid.UUID, request: Request, actor: Cashier, db: DbSession, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, {}, lambda: service.finalize(db, actor, sale_id), response_model=s.SaleOut)


@router.post("/{sale_id}/cancel", response_model=s.SaleOut, summary="Cancel an unfinished sale (IK)", responses=ERR)
async def cancel(sale_id: uuid.UUID, body: s.SaleCancel, request: Request, actor: Seller, db: DbSession, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, body, lambda: service.cancel(db, actor, sale_id, body), response_model=s.SaleOut)


@router.post("/{sale_id}/void", response_model=s.SaleOut, summary="Void a finalized sale in its open session (IK)", responses=ERR)
async def void(sale_id: uuid.UUID, body: s.SaleCancel, request: Request, actor: Viewer, db: DbSession, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, body, lambda: service.void(db, actor, sale_id, body), response_model=s.SaleOut)


@router.get("/{sale_id}/receipt", response_model=s.Receipt, summary="Receipt data for printing", responses=ERR)
async def receipt(sale_id: uuid.UUID, actor: Viewer, db: DbSession) -> dict:
    return await service.receipt(db, actor, sale_id)


@router.post("/{sale_id}/reprint", response_model=s.SaleOut, summary="Reprint a receipt (marked COPY)", responses=ERR)
async def reprint(sale_id: uuid.UUID, actor: Viewer, db: DbSession) -> dict:
    return await service.reprint(db, actor, sale_id)


@router.post("/{sale_id}/invoice", response_model=s.SaleOut, summary="Issue an invoice number", responses=ERR)
async def invoice(sale_id: uuid.UUID, actor: Viewer, db: DbSession) -> dict:
    return await service.invoice(db, actor, sale_id)


@router.post("/{sale_id}/returns/quote", response_model=s.ReturnQuote, summary="Preview a return's refund and approvals", responses=ERR)
async def quote_return(sale_id: uuid.UUID, body: s.ReturnIn, actor: Annotated[Principal, Depends(require("sales.return.create"))], db: DbSession) -> dict:
    return await returns.quote(db, actor, sale_id, body)


@router.post("/{sale_id}/returns", response_model=s.ReturnOut, status_code=201, summary="Return or exchange items (IK)", responses=ERR)
async def create_return(sale_id: uuid.UUID, body: s.ReturnIn, request: Request, actor: Annotated[Principal, Depends(require("sales.return.create"))], db: DbSession, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, body, lambda: returns.create_return(db, actor, sale_id, body), response_model=s.ReturnOut, status_code=201)


# Payments

@payments_router.get("", response_model=ListResponse[s.PaymentRow], summary="Payments for reconciliation", responses=ERR)
async def list_payments(actor: Annotated[Principal, Depends(require("payments.payment.view", "payments.payment.reconcile"))], db: DbSession, method: str | None = None,
                        status_filter: Annotated[str | None, Query(alias="status")] = None, reconciled: bool | None = None, date_from: date | None = None, date_to: date | None = None,
                        limit: Limit = 200, offset: Offset = 0) -> dict:
    return page(await service.list_payments(db, actor, method=method, status=status_filter, reconciled=reconciled, date_from=date_from, date_to=date_to, limit=limit, offset=offset))


@payments_router.post("/{payment_id}/reconcile", response_model=s.SalePaymentOut, summary="Mark a payment reconciled", responses=ERR)
async def reconcile(payment_id: uuid.UUID, body: s.ReconcileIn, actor: Annotated[Principal, Depends(require("payments.payment.reconcile"))], db: DbSession) -> dict:
    return await service.reconcile_payment(db, actor, payment_id, body.reconciled)


# Cashier sessions

SessionViewer = Annotated[Principal, Depends(require("cash.session.view", "cash.session.open", "cash.session.view_all"))]


@sessions_router.get("", response_model=ListResponse[s.CashSessionOut], summary="Cashier sessions", responses=ERR)
async def list_sessions(actor: SessionViewer, db: DbSession, status_filter: Annotated[str | None, Query(alias="status")] = None, terminal_id: uuid.UUID | None = None,
                        limit: Limit = 100, offset: Offset = 0) -> dict:
    return page(await cash_sessions.list_sessions(db, actor, status=status_filter, terminal_id=terminal_id, limit=limit, offset=offset))


@sessions_router.get("/current", response_model=s.CashSessionOut | None, summary="Your open session on this terminal", responses=ERR)
async def current_session(actor: CurrentPrincipal, db: DbSession) -> dict | None:
    return await cash_sessions.current(db, actor)


@sessions_router.post("/open", response_model=s.CashSessionOut, status_code=201, summary="Open a session with the opening float (IK)", responses=ERR)
async def open_session(body: s.SessionOpen, request: Request, actor: Annotated[Principal, Depends(require("cash.session.open"))], db: DbSession, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, body, lambda: cash_sessions.open_session(db, actor, body), response_model=s.CashSessionOut, status_code=201)


@sessions_router.get("/{session_id}/summary", response_model=s.SessionSummary, summary="Session (X/Z) summary; expected cash hidden from the cashier until counted", responses=ERR)
async def session_summary(session_id: uuid.UUID, actor: SessionViewer, db: DbSession) -> dict:
    return await cash_sessions.summary(db, actor, session_id)


@sessions_router.post("/{session_id}/movements", response_model=s.CashMovementOut, status_code=201, summary="Cash in, cash out, paid-out or drop", responses=ERR)
async def add_movement(session_id: uuid.UUID, body: s.CashMovementIn, actor: Annotated[Principal, Depends(require("cash.session.open", "cash.session.approve"))], db: DbSession) -> dict:
    return await cash_sessions.add_movement(db, actor, session_id, body)


@sessions_router.post("/{session_id}/close", response_model=s.CashSessionOut, summary="Submit the blind count and close (IK)", responses=ERR)
async def close_session(session_id: uuid.UUID, body: s.SessionClose, request: Request, actor: Annotated[Principal, Depends(require("cash.session.close"))], db: DbSession, key: IdempotencyKey = None) -> Any:
    return await idempotency.run(request, actor, key, body, lambda: cash_sessions.close(db, actor, session_id, body), response_model=s.CashSessionOut)


@sessions_router.post("/{session_id}/approve", response_model=s.CashSessionOut, summary="Approve a variance beyond tolerance", responses=ERR)
async def approve_session(session_id: uuid.UUID, body: s.ReasonIn, actor: Annotated[Principal, Depends(require("cash.session.approve"))], db: DbSession) -> dict:
    return await cash_sessions.approve(db, actor, session_id, body.reason)


@sessions_router.post("/{session_id}/force-close", response_model=s.CashSessionOut, summary="Force-close an abandoned session", responses=ERR)
async def force_close(session_id: uuid.UUID, body: s.ReasonIn, actor: Annotated[Principal, Depends(require("cash.session.approve"))], db: DbSession) -> dict:
    return await cash_sessions.force_close(db, actor, session_id, body.reason)


# Returns and refunds

ReturnViewer = Annotated[Principal, Depends(require("sales.sale.view", "sales.return.create", "sales.refund.process"))]


@returns_router.get("/returns", response_model=ListResponse[s.ReturnOut], summary="Returns and exchanges", responses=ERR)
async def list_returns(actor: ReturnViewer, db: DbSession, limit: Limit = 100, offset: Offset = 0) -> dict:
    return page(await returns.list_returns(db, actor, limit, offset))


@returns_router.get("/returns/{return_id}", response_model=s.ReturnOut, summary="Return detail", responses=ERR)
async def get_return(return_id: uuid.UUID, actor: ReturnViewer, db: DbSession) -> dict:
    return await returns.return_view(db, actor, await returns.get_return(db, actor, return_id))


@returns_router.post("/returns/{return_id}/confirm-refund", response_model=s.ReturnOut, summary="Confirm a pending electronic refund with its reference", responses=ERR)
async def confirm_return_refund(return_id: uuid.UUID, body: s.ConfirmRefund, actor: ReturnViewer, db: DbSession) -> dict:
    ret = await returns.get_return(db, actor, return_id)
    await returns.confirm_refunds(db, actor, return_id=ret.id, reference=body.reference)
    return await returns.return_view(db, actor, await returns.get_return(db, actor, return_id))


@returns_router.get("/refunds", response_model=ListResponse[s.RefundOut], summary="Refunds (returns, voids, cancellations)", responses=ERR)
async def list_refunds(actor: ReturnViewer, db: DbSession, status_filter: Annotated[str | None, Query(alias="status")] = None, limit: Limit = 200, offset: Offset = 0) -> dict:
    return page(await returns.list_refunds(db, actor, status_filter, limit, offset))


@returns_router.post("/refunds/{refund_id}/confirm", status_code=status.HTTP_204_NO_CONTENT, summary="Confirm a pending refund (e.g. from a void) with its reference", responses=ERR)
async def confirm_refund(refund_id: uuid.UUID, body: s.ConfirmRefund, actor: ReturnViewer, db: DbSession) -> Response:
    await returns.confirm_refunds(db, actor, refund_id=refund_id, reference=body.reference)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

