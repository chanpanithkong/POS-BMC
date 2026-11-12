"""Inventory endpoints (INV, CST, ADJ, TRF, ALR; Phase 4).

Commands that move stock require an `Idempotency-Key` header (marked IK), so a
retried request never posts twice.
"""

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request
from pydantic import ValidationError

from app.api.deps import DbSession, require
from app.core.exceptions import AppError, NotFound
from app.schemas import inventory as s
from app.schemas.common import ListResponse, error_responses
from app.services import alerts, idempotency, inventory_docs, stock
from app.services.principal import Principal

router = APIRouter(prefix="/inventory", tags=["Inventory"])
alerts_router = APIRouter(prefix="/alerts", tags=["Inventory alerts"])
ERR = error_responses(401, 403, 404, 409, 422)
StockViewer = Annotated[Principal, Depends(require("inventory.stock.view"))]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", description="Required: a unique key per command so retries never post twice")]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]
ADJUSTMENT_VERBS = ("submit", "approve", "reject", "post", "cancel")
TRANSFER_VERBS = ("approve", "dispatch", "receive", "close", "cancel")
COUNT_VERBS = ("submit", "recount", "approve", "post", "cancel")


def page(items: list, total: int | None = None) -> dict:
    return {"items": items, "total": len(items) if total is None else total}


def _parse(model: type, body: dict[str, Any] | None) -> Any:
    try:
        return model.model_validate(body or {})
    except ValidationError as exc:
        details = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        raise AppError("Invalid request", code="VALIDATION_ERROR", status_code=422, details=details) from exc


# Balances and ledger

@router.get("/balances", response_model=ListResponse[s.StockOverviewRow], summary="Stock overview per product", responses=ERR,
            description="On hand, reserved, available (sellable locations), in transit to the selected warehouses, status against reorder and maximum levels, and per-location detail. Cost and value need inventory.cost.view.")
async def balances(actor: StockViewer, db: DbSession, branch_id: uuid.UUID | None = None, warehouse_id: uuid.UUID | None = None,
                   location_type: Annotated[str | None, Query(pattern="^(SELLABLE|STORAGE|RECEIVING|DAMAGED|EXPIRED|QUARANTINE|RETURNS)$")] = None,
                   q: str | None = None, category_id: uuid.UUID | None = None, product_id: uuid.UUID | None = None, limit: Limit = 100, offset: Offset = 0) -> dict:
    rows, total = await stock.overview(db, actor, branch_id=branch_id, warehouse_id=warehouse_id, location_type=location_type, q=q, category_id=category_id, product_id=product_id, limit=limit, offset=offset)
    return page(rows, total)


@router.get("/availability", response_model=ListResponse[s.Availability], summary="Sellable quantity for products", responses=ERR)
async def availability(actor: Annotated[Principal, Depends(require("inventory.stock.view", "pos.sale.create"))], db: DbSession,
                       product_ids: Annotated[list[uuid.UUID], Query(max_length=200)], branch_id: uuid.UUID | None = None, location_id: uuid.UUID | None = None) -> dict:
    return page(await stock.availability(db, actor, product_ids, branch_id=branch_id, location_id=location_id))


@router.get("/movements", response_model=ListResponse[s.MovementOut], summary="Stock movement ledger, newest first", responses=ERR)
async def movements(actor: StockViewer, db: DbSession, product_id: uuid.UUID | None = None, warehouse_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None,
                    location_id: uuid.UUID | None = None, type_filter: Annotated[str | None, Query(alias="type")] = None, source_id: str | None = None,
                    date_from: date | None = None, date_to: date | None = None, limit: Limit = 200, offset: Offset = 0) -> dict:
    if branch_id:
        actor.assert_branch(branch_id)
    rows, total = await stock.movement_rows(db, actor, product_id=product_id, warehouse_id=warehouse_id, branch_id=branch_id, location_id=location_id, movement_type=type_filter,
                                            source_id=source_id, date_from=date_from, date_to=date_to, limit=limit, offset=offset)
    return page(rows, total)


async def _movement(db: DbSession, actor: Principal, movement_id: int) -> dict:
    rows, _ = await stock.movement_rows(db, actor, movement_id=movement_id, limit=1)
    if not rows:
        raise NotFound("Movement")
    return rows[0]


@router.post("/movements/{movement_id}/reverse", response_model=s.MovementOut, summary="Reverse a movement (IK)", responses=ERR,
             description="Posts an equal and opposite REVERSAL movement; the original is never changed. Sales, returns and transfers are corrected through their own documents.")
async def reverse(movement_id: int, body: s.ReverseIn, request: Request, actor: Annotated[Principal, Depends(require("inventory.movement.reverse"))], db: DbSession, key: IdempotencyKey = None) -> Any:
    async def command() -> dict:
        movement = await stock.reverse(db, actor, movement_id, body.reason)
        return await _movement(db, actor, movement.id)

    return await idempotency.run(request, actor, key, body, command, response_model=s.MovementOut)


@router.post("/relocations", response_model=s.MovementOut, summary="Move stock between locations in one warehouse (IK)", responses=ERR)
async def relocate(body: s.RelocationIn, request: Request, actor: Annotated[Principal, Depends(require("inventory.transfer.create"))], db: DbSession, key: IdempotencyKey = None) -> Any:
    async def command() -> dict:
        movement = await stock.relocate(db, actor, product_id=body.product_id, from_location_id=body.from_location_id, to_location_id=body.to_location_id, quantity=body.quantity, reason=body.reason, key=key or "")
        return await _movement(db, actor, movement.id)

    return await idempotency.run(request, actor, key, body, command, response_model=s.MovementOut)


@router.post("/opening-balances", response_model=s.MovementOut, summary="Post opening stock for a product that has never moved (IK)", responses=ERR,
             description="For go-live. Sets the first weighted-average cost. Products with any movement must use an adjustment instead.")
async def opening_balance(body: s.OpeningBalanceIn, request: Request, actor: Annotated[Principal, Depends(require("inventory.adjustment.approve"))], db: DbSession, key: IdempotencyKey = None) -> Any:
    async def command() -> dict:
        movement = await stock.opening_balance(db, actor, product_id=body.product_id, location_id=body.location_id, quantity=body.quantity, unit_cost=body.unit_cost,
                                               batch_no=body.batch_no, expiry_date=body.expiry_date, key=key or "")
        return await _movement(db, actor, movement.id)

    return await idempotency.run(request, actor, key, body, command, response_model=s.MovementOut, status_code=201)


@router.post("/reconciliation", response_model=s.ReconciliationResult, summary="Check every balance against the sum of its movements", responses=ERR)
async def reconciliation(actor: StockViewer, db: DbSession) -> dict:
    return await stock.reconcile(db, actor)


@router.get("/batches", response_model=ListResponse[s.BatchRow], summary="Batches with expiry dates, soonest first", responses=ERR)
async def batches(actor: StockViewer, db: DbSession, within_days: Annotated[int | None, Query(ge=0, le=3650)] = None) -> dict:
    return page(await stock.batches(db, actor, within_days=within_days))


@router.get("/reorder-suggestions", response_model=ListResponse[s.ReorderSuggestion], summary="Products at or below their reorder level", responses=ERR)
async def reorder_suggestions(actor: Annotated[Principal, Depends(require("purchasing.order.create", "inventory.stock.view"))], db: DbSession,
                              warehouse_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None) -> dict:
    return page(await stock.reorder_suggestions(db, actor, warehouse_id=warehouse_id, branch_id=branch_id))


# Adjustments

AdjustmentViewer = Annotated[Principal, Depends(require("inventory.adjustment.create", "inventory.adjustment.approve", "inventory.stock.view"))]


@router.get("/adjustments", response_model=ListResponse[s.AdjustmentOut], summary="Stock adjustments", responses=ERR)
async def list_adjustments(actor: AdjustmentViewer, db: DbSession, status: str | None = None, limit: Limit = 100, offset: Offset = 0) -> dict:
    return page(await inventory_docs.list_adjustments(db, actor, status, limit, offset))


@router.post("/adjustments", response_model=s.AdjustmentOut, status_code=201, summary="Create a draft adjustment", responses=ERR)
async def create_adjustment(body: s.AdjustmentCreate, actor: Annotated[Principal, Depends(require("inventory.adjustment.create"))], db: DbSession) -> dict:
    return await inventory_docs.create_adjustment(db, actor, body)


@router.patch("/adjustments/{adjustment_id}", response_model=s.AdjustmentOut, summary="Edit a draft or rejected adjustment", responses=ERR)
async def update_adjustment(adjustment_id: uuid.UUID, body: s.AdjustmentUpdate, actor: Annotated[Principal, Depends(require("inventory.adjustment.create"))], db: DbSession) -> dict:
    return await inventory_docs.update_adjustment(db, actor, adjustment_id, body)


@router.delete("/adjustments/{adjustment_id}", response_model=s.AdjustmentOut, summary="Cancel an unposted adjustment (kept for the record)", responses=ERR)
async def cancel_adjustment(adjustment_id: uuid.UUID, actor: Annotated[Principal, Depends(require("inventory.adjustment.create"))], db: DbSession) -> dict:
    return await inventory_docs.adjustment_action(db, actor, adjustment_id, "cancel", s.DocumentAction())


@router.post("/adjustments/{adjustment_id}/{verb}", response_model=s.AdjustmentOut, summary="Adjustment workflow: submit, approve, reject, post, cancel (IK)", responses=ERR)
async def adjustment_action(adjustment_id: uuid.UUID, verb: str, request: Request, actor: AdjustmentViewer, db: DbSession,
                            body: Annotated[dict[str, Any] | None, Body()] = None, key: IdempotencyKey = None) -> Any:
    if verb not in ADJUSTMENT_VERBS:
        raise NotFound("Action")
    data = _parse(s.DocumentAction, body)
    return await idempotency.run(request, actor, key, data, lambda: inventory_docs.adjustment_action(db, actor, adjustment_id, verb, data), response_model=s.AdjustmentOut)


# Transfers

TransferUser = Annotated[Principal, Depends(require("inventory.transfer.create", "inventory.transfer.approve"))]


@router.get("/transfers", response_model=ListResponse[s.TransferOut], summary="Stock transfers to or from your warehouses", responses=ERR)
async def list_transfers(actor: TransferUser, db: DbSession, status: str | None = None, limit: Limit = 100, offset: Offset = 0) -> dict:
    return page(await inventory_docs.list_transfers(db, actor, status, limit, offset))


@router.post("/transfers", response_model=s.TransferOut, status_code=201, summary="Request a transfer", responses=ERR)
async def create_transfer(body: s.TransferCreate, actor: Annotated[Principal, Depends(require("inventory.transfer.create"))], db: DbSession) -> dict:
    return await inventory_docs.create_transfer(db, actor, body)


@router.post("/transfers/{transfer_id}/{verb}", response_model=s.TransferOut, summary="Transfer workflow: approve, dispatch, receive, close, cancel (IK)", responses=ERR,
             description="dispatch: `{lines: [{line_id, quantity}]}` (omit lines to send everything requested). receive: `{lines: [{line_id, received, damaged, short, excess}]}`.")
async def transfer_action(transfer_id: uuid.UUID, verb: str, request: Request, actor: TransferUser, db: DbSession,
                          body: Annotated[dict[str, Any] | None, Body()] = None, key: IdempotencyKey = None) -> Any:
    if verb not in TRANSFER_VERBS:
        raise NotFound("Action")
    data = _parse(s.TRANSFER_BODIES.get(verb, s.TransferAction), body)
    return await idempotency.run(request, actor, key, data, lambda: inventory_docs.transfer_action(db, actor, transfer_id, verb, data), response_model=s.TransferOut)


# Counts

CountUser = Annotated[Principal, Depends(require("inventory.count.create", "inventory.count.approve"))]


@router.get("/counts", response_model=ListResponse[s.CountOut], summary="Stock counts", responses=ERR)
async def list_counts(actor: CountUser, db: DbSession, status: str | None = None, limit: Limit = 100, offset: Offset = 0) -> dict:
    return page(await inventory_docs.list_counts(db, actor, status, limit, offset))


@router.post("/counts", response_model=s.CountOut, status_code=201, summary="Start a stock count (snapshot taken now)", responses=ERR)
async def create_count(body: s.CountCreate, actor: Annotated[Principal, Depends(require("inventory.count.create"))], db: DbSession) -> dict:
    return await inventory_docs.create_count(db, actor, body)


@router.patch("/counts/{count_id}/lines", response_model=s.CountOut, summary="Enter counted quantities", responses=ERR)
async def set_count_lines(count_id: uuid.UUID, body: s.CountLinesUpdate, actor: Annotated[Principal, Depends(require("inventory.count.create"))], db: DbSession) -> dict:
    return await inventory_docs.set_count_lines(db, actor, count_id, body)


@router.post("/counts/{count_id}/{verb}", response_model=s.CountOut, summary="Count workflow: submit, recount, approve, post, cancel (IK)", responses=ERR)
async def count_action(count_id: uuid.UUID, verb: str, request: Request, actor: CountUser, db: DbSession,
                       body: Annotated[dict[str, Any] | None, Body()] = None, key: IdempotencyKey = None) -> Any:
    if verb not in COUNT_VERBS:
        raise NotFound("Action")
    data = _parse(s.CountAction, body)
    return await idempotency.run(request, actor, key, data, lambda: inventory_docs.count_action(db, actor, count_id, verb, data), response_model=s.CountOut)


# Alerts

@alerts_router.get("", response_model=ListResponse[s.AlertOut], summary="Inventory alerts", responses=ERR)
async def list_alerts(actor: Annotated[Principal, Depends(require("inventory.alert.view", "inventory.alert.manage"))], db: DbSession, status: str | None = None, include_resolved: bool = False) -> dict:
    return page(await alerts.list_alerts(db, actor, status, include_resolved))


@alerts_router.post("/evaluate", response_model=s.EvaluateResult, summary="Re-check stock levels, expiry and slow movers now", responses=ERR)
async def evaluate(actor: Annotated[Principal, Depends(require("inventory.alert.manage"))], db: DbSession) -> dict:
    return await alerts.evaluate(db, actor)


@alerts_router.post("/{alert_id}/action", response_model=s.AlertOut, summary="Acknowledge, resolve, snooze or assign an alert", responses=ERR)
async def alert_action(alert_id: uuid.UUID, body: s.AlertAction, actor: Annotated[Principal, Depends(require("inventory.alert.manage"))], db: DbSession) -> dict:
    return await alerts.act(db, actor, alert_id, body.action, body.note, body.assigned_to, body.days)
