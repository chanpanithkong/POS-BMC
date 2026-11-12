"""Suppliers, purchase orders, goods receipts, supplier invoices, purchase returns, customers and groups (Phase 6)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response, status
from pydantic import ValidationError

from app.api.deps import DbSession, require
from app.core.exceptions import AppError, NotFound
from app.models import Supplier
from app.schemas import purchasing as s
from app.schemas.common import ListResponse, error_responses
from app.services import customers, idempotency, purchasing
from app.services.common import owned
from app.services.principal import Principal

router = APIRouter(tags=["Purchasing"])
customers_router = APIRouter(tags=["Customers"])
ERR = error_responses(401, 403, 404, 409, 422)
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key", description="Required for posting actions; a retry with the same key returns the first result")]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]
PO_VERBS = ("submit", "approve", "reject", "send", "cancel", "close", "short-close")
GRN_VERBS = ("post", "approve", "reject")
PR_VERBS = ("approve", "dispatch", "credit", "cancel")


def page(items: list, total: int | None = None) -> dict:
    return {"items": items, "total": len(items) if total is None else total}


def _action_body(body: dict[str, Any] | None) -> s.DocAction:
    try:
        return s.DocAction.model_validate(body or {})
    except ValidationError as exc:
        raise AppError("Invalid request", code="VALIDATION_ERROR", status_code=422, details=[{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]) from exc


# Suppliers

SupplierViewer = Annotated[Principal, Depends(require("purchasing.supplier.view", "purchasing.supplier.manage", "purchasing.order.create", "purchasing.receipt.create"))]
SupplierAdmin = Annotated[Principal, Depends(require("purchasing.supplier.manage"))]


@router.get("/suppliers", response_model=ListResponse[s.SupplierOut], summary="Suppliers with performance figures", responses=ERR)
async def list_suppliers(actor: SupplierViewer, db: DbSession, q: str | None = None, status_filter: Annotated[str | None, Query(alias="status")] = None) -> dict:
    return page(await purchasing.list_suppliers(db, actor, q, status_filter))


@router.post("/suppliers", response_model=s.SupplierOut, status_code=201, summary="Create a supplier", responses=ERR)
async def create_supplier(body: s.SupplierCreate, actor: SupplierAdmin, db: DbSession) -> dict:
    return await purchasing.create_supplier(db, actor, body)


@router.get("/suppliers/{supplier_id}", response_model=s.SupplierOut, summary="Supplier detail", responses=ERR)
async def get_supplier(supplier_id: uuid.UUID, actor: SupplierViewer, db: DbSession) -> dict:
    return await purchasing.supplier_view(db, await owned(db, Supplier, supplier_id, actor, "Supplier"))


@router.patch("/suppliers/{supplier_id}", response_model=s.SupplierOut, summary="Update a supplier and its contacts", responses=ERR)
async def update_supplier(supplier_id: uuid.UUID, body: s.SupplierUpdate, actor: SupplierAdmin, db: DbSession) -> dict:
    return await purchasing.update_supplier(db, actor, supplier_id, body)


@router.delete("/suppliers/{supplier_id}", status_code=204, summary="Remove a supplier without open orders", responses=ERR)
async def delete_supplier(supplier_id: uuid.UUID, actor: SupplierAdmin, db: DbSession) -> Response:
    await purchasing.delete_supplier(db, actor, supplier_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Purchase orders

PoViewer = Annotated[Principal, Depends(require("purchasing.order.view", "purchasing.order.create", "purchasing.order.approve", "purchasing.receipt.create"))]
PoCreator = Annotated[Principal, Depends(require("purchasing.order.create"))]


@router.get("/purchase-orders", response_model=ListResponse[s.PoOut], summary="Purchase orders", responses=ERR)
async def list_pos(actor: PoViewer, db: DbSession, status_filter: Annotated[str | None, Query(alias="status")] = None, supplier_id: uuid.UUID | None = None,
                   branch_id: uuid.UUID | None = None, limit: Limit = 100, offset: Offset = 0) -> dict:
    return page(await purchasing.list_pos(db, actor, status=status_filter, supplier_id=supplier_id, branch_id=branch_id, limit=limit, offset=offset))


@router.post("/purchase-orders", response_model=s.PoOut, status_code=201, summary="Create a draft purchase order", responses=ERR)
async def create_po(body: s.PoCreate, actor: PoCreator, db: DbSession) -> dict:
    return await purchasing.create_po(db, actor, body)


@router.get("/purchase-orders/{po_id}", response_model=s.PoOut, summary="Purchase order detail", responses=ERR)
async def get_po(po_id: uuid.UUID, actor: PoViewer, db: DbSession) -> dict:
    return await purchasing.po_view(db, actor, await purchasing._locked(db, actor, purchasing.PurchaseOrder, po_id, "Purchase order"))


@router.patch("/purchase-orders/{po_id}", response_model=s.PoOut, summary="Edit a purchase order (approved orders need approval again)", responses=ERR)
async def update_po(po_id: uuid.UUID, body: s.PoUpdate, actor: PoCreator, db: DbSession) -> dict:
    return await purchasing.update_po(db, actor, po_id, body)


@router.delete("/purchase-orders/{po_id}", status_code=204, summary="Delete a draft purchase order", responses=ERR)
async def delete_po(po_id: uuid.UUID, actor: PoCreator, db: DbSession) -> Response:
    await purchasing.delete_po(db, actor, po_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/purchase-orders/{po_id}/{verb}", response_model=s.PoOut, summary="PO workflow: submit, approve, reject, send, cancel, close (IK)", responses=ERR)
async def po_action(po_id: uuid.UUID, verb: str, request: Request, actor: PoViewer, db: DbSession, body: Annotated[dict[str, Any] | None, Body()] = None, key: IdempotencyKey = None) -> Any:
    if verb not in PO_VERBS:
        raise NotFound("Action")
    data = _action_body(body)
    return await idempotency.run(request, actor, key, data, lambda: purchasing.po_action(db, actor, po_id, verb, data), response_model=s.PoOut)


# Goods receipts

GrnViewer = Annotated[Principal, Depends(require("purchasing.receipt.create", "purchasing.receipt.post", "purchasing.order.view", "inventory.adjustment.approve"))]
GrnCreator = Annotated[Principal, Depends(require("purchasing.receipt.create"))]


@router.get("/goods-receipts", response_model=ListResponse[s.GrnOut], summary="Goods receipts", responses=ERR)
async def list_grns(actor: GrnViewer, db: DbSession, status_filter: Annotated[str | None, Query(alias="status")] = None, po_id: uuid.UUID | None = None,
                    branch_id: uuid.UUID | None = None, limit: Limit = 100, offset: Offset = 0) -> dict:
    return page(await purchasing.list_grns(db, actor, status=status_filter, po_id=po_id, branch_id=branch_id, limit=limit, offset=offset))


@router.post("/goods-receipts", response_model=s.GrnOut, status_code=201, summary="Record a delivery as a draft receipt", responses=ERR,
             description="Without a PO the user needs purchasing.receipt.exception and must give a reason; the receipt is flagged and needs approval to post.")
async def create_grn(body: s.GrnCreate, actor: GrnCreator, db: DbSession) -> dict:
    return await purchasing.create_grn(db, actor, body)


@router.get("/goods-receipts/{grn_id}", response_model=s.GrnOut, summary="Goods receipt detail", responses=ERR)
async def get_grn(grn_id: uuid.UUID, actor: GrnViewer, db: DbSession) -> dict:
    return await purchasing.grn_view(db, actor, await purchasing._locked(db, actor, purchasing.GoodsReceipt, grn_id, "Goods receipt"))


@router.patch("/goods-receipts/{grn_id}", response_model=s.GrnOut, summary="Edit a draft receipt", responses=ERR)
async def update_grn(grn_id: uuid.UUID, body: s.GrnUpdate, actor: GrnCreator, db: DbSession) -> dict:
    return await purchasing.update_grn(db, actor, grn_id, body)


@router.delete("/goods-receipts/{grn_id}", status_code=204, summary="Delete a draft receipt", responses=ERR)
async def delete_grn(grn_id: uuid.UUID, actor: GrnCreator, db: DbSession) -> Response:
    await purchasing.delete_grn(db, actor, grn_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/goods-receipts/{grn_id}/{verb}", response_model=s.GrnOut, summary="Receipt workflow: post, approve, reject (IK)", responses=ERR,
             description="post increases stock once, or sends a receipt with discrepancies for approval; approve posts it; reject returns it to draft.")
async def grn_action(grn_id: uuid.UUID, verb: str, request: Request, actor: GrnViewer, db: DbSession, body: Annotated[dict[str, Any] | None, Body()] = None, key: IdempotencyKey = None) -> Any:
    if verb not in GRN_VERBS:
        raise NotFound("Action")
    data = _action_body(body)
    return await idempotency.run(request, actor, key, data, lambda: purchasing.grn_action(db, actor, grn_id, verb, data), response_model=s.GrnOut)


# Supplier invoices

InvoiceUser = Annotated[Principal, Depends(require("purchasing.invoice.manage"))]


@router.get("/supplier-invoices", response_model=ListResponse[s.InvoiceOut], summary="Supplier invoices", responses=ERR)
async def list_invoices(actor: Annotated[Principal, Depends(require("purchasing.invoice.manage", "purchasing.order.view"))], db: DbSession, supplier_id: uuid.UUID | None = None) -> dict:
    return page(await purchasing.list_invoices(db, actor, supplier_id))


@router.post("/supplier-invoices", response_model=s.InvoiceOut, status_code=201, summary="Record a supplier invoice (matched against receipts)", responses=ERR)
async def create_invoice(body: s.InvoiceCreate, actor: InvoiceUser, db: DbSession) -> dict:
    return await purchasing.create_invoice(db, actor, body)


@router.post("/supplier-invoices/{invoice_id}/payments", response_model=s.InvoiceOut, summary="Record a payment to the supplier", responses=ERR)
async def pay_invoice(invoice_id: uuid.UUID, body: s.InvoicePaymentIn, actor: InvoiceUser, db: DbSession) -> dict:
    return await purchasing.pay_invoice(db, actor, invoice_id, body)


# Purchase returns

PrUser = Annotated[Principal, Depends(require("purchasing.return.manage", "purchasing.order.create", "purchasing.order.approve", "purchasing.receipt.post"))]


@router.get("/purchase-returns", response_model=ListResponse[s.PrOut], summary="Returns to suppliers", responses=ERR)
async def list_prs(actor: PrUser, db: DbSession) -> dict:
    return page(await purchasing.list_prs(db, actor))


@router.post("/purchase-returns", response_model=s.PrOut, status_code=201, summary="Create a return against a posted receipt", responses=ERR)
async def create_pr(body: s.PrCreate, actor: PrUser, db: DbSession) -> dict:
    return await purchasing.create_pr(db, actor, body)


@router.post("/purchase-returns/{pr_id}/{verb}", response_model=s.PrOut, summary="Return workflow: approve, dispatch, credit, cancel (IK)", responses=ERR)
async def pr_action(pr_id: uuid.UUID, verb: str, request: Request, actor: PrUser, db: DbSession, body: Annotated[dict[str, Any] | None, Body()] = None, key: IdempotencyKey = None) -> Any:
    if verb not in PR_VERBS:
        raise NotFound("Action")
    data = _action_body(body)
    return await idempotency.run(request, actor, key, data, lambda: purchasing.pr_action(db, actor, pr_id, verb, data), response_model=s.PrOut)


# Customers

CustomerViewer = Annotated[Principal, Depends(require("customers.customer.view", "customers.customer.manage", "pos.sale.create"))]
CustomerAdmin = Annotated[Principal, Depends(require("customers.customer.manage"))]


@customers_router.get("/customers", response_model=ListResponse[s.CustomerOut], summary="Search customers by name, code or phone", responses=ERR,
                      description="Phone, email and address are masked without customers.personal_data.view.")
async def list_customers(actor: CustomerViewer, db: DbSession, q: str | None = None, group_id: uuid.UUID | None = None, status_filter: Annotated[str | None, Query(alias="status")] = None,
                         limit: Limit = 50, offset: Offset = 0) -> dict:
    items, total = await customers.list_customers(db, actor, q=q, group_id=group_id, status=status_filter, limit=limit, offset=offset)
    return page(items, total)


@customers_router.post("/customers", response_model=s.CustomerOut, status_code=201, summary="Create a customer", responses=ERR)
async def create_customer(body: s.CustomerCreate, actor: Annotated[Principal, Depends(require("customers.customer.manage", "pos.sale.create"))], db: DbSession) -> dict:
    return await customers.create_customer(db, actor, body)


@customers_router.get("/customers/{customer_id}", response_model=s.CustomerOut, summary="Customer detail", responses=ERR)
async def get_customer(customer_id: uuid.UUID, actor: CustomerViewer, db: DbSession) -> dict:
    return await customers.customer_view(db, actor, await customers.get_customer(db, actor, customer_id))


@customers_router.patch("/customers/{customer_id}", response_model=s.CustomerOut, summary="Update a customer", responses=ERR)
async def update_customer(customer_id: uuid.UUID, body: s.CustomerFields, actor: CustomerAdmin, db: DbSession) -> dict:
    return await customers.update_customer(db, actor, customer_id, body)


@customers_router.delete("/customers/{customer_id}", status_code=204, summary="Delete a customer with no sales", responses=ERR)
async def delete_customer(customer_id: uuid.UUID, actor: CustomerAdmin, db: DbSession) -> Response:
    await customers.delete_customer(db, actor, customer_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@customers_router.post("/customers/{customer_id}/anonymize", response_model=s.CustomerOut, summary="Remove personal data, keep sales history", responses=ERR)
async def anonymize(customer_id: uuid.UUID, actor: CustomerAdmin, db: DbSession) -> dict:
    return await customers.anonymize(db, actor, customer_id)


@customers_router.get("/customer-groups", response_model=ListResponse[s.GroupOut], summary="Customer groups", responses=ERR)
async def list_groups(actor: CustomerViewer, db: DbSession) -> dict:
    return page(await customers.list_groups(db, actor))


@customers_router.post("/customer-groups", response_model=s.GroupOut, status_code=201, summary="Create a customer group (and its price list)", responses=ERR)
async def create_group(body: s.GroupCreate, actor: CustomerAdmin, db: DbSession) -> Any:
    return await customers.create_group(db, actor, body)


@customers_router.patch("/customer-groups/{group_id}", response_model=s.GroupOut, summary="Update a customer group", responses=ERR)
async def update_group(group_id: uuid.UUID, body: s.GroupFields, actor: CustomerAdmin, db: DbSession) -> Any:
    return await customers.update_group(db, actor, group_id, body)


@customers_router.delete("/customer-groups/{group_id}", status_code=204, summary="Delete an unused customer group", responses=ERR)
async def delete_group(group_id: uuid.UUID, actor: CustomerAdmin, db: DbSession) -> Response:
    await customers.delete_group(db, actor, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
