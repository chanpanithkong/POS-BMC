"""Organisation and settings endpoints (ORG, BRN; Phase 3).

Reads are open to any signed-in user (POS and every screen need branches, tax codes,
rates and settings) and are filtered to the caller's branch and warehouse scope.
Changes need settings.settings.manage.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Response, status

from app.api.deps import CurrentPrincipal, DbSession, require
from app.models import PaymentMethod, ReceiptTemplate, TaxCode
from app.schemas import org as s
from app.schemas.common import ListResponse, error_responses
from app.services import org as service
from app.services.principal import Principal

router = APIRouter(tags=["Organisation"])
Admin = Annotated[Principal, Depends(require("settings.settings.manage"))]
ERR = error_responses(401, 403, 404, 409, 422)


def page(items: list) -> dict:
    return {"items": items, "total": len(items)}


@router.get("/companies/current", response_model=s.CompanyOut, summary="Current company profile", responses=ERR)
async def get_company(actor: CurrentPrincipal, db: DbSession) -> dict:
    return service.company_view(await service.get_company(db, actor))


@router.patch("/companies/current", response_model=s.CompanyOut, summary="Update company profile", responses=ERR)
async def update_company(body: s.CompanyUpdate, actor: Admin, db: DbSession) -> dict:
    return await service.update_company(db, actor, body)


@router.get("/settings", response_model=s.SystemSettings, summary="Company settings", responses=ERR)
async def get_settings(actor: CurrentPrincipal, db: DbSession) -> s.SystemSettings:
    return await service.get_company_settings(db, actor)


@router.patch("/settings", response_model=s.SystemSettings, summary="Change company settings", responses=ERR,
              description="Partial update. Unknown keys are rejected. Costing is fixed to weighted average at company level (D-05). Turning on negative stock or reduced separation of duties is flagged in the audit log.")
async def update_settings(actor: Admin, db: DbSession, body: Annotated[dict[str, Any], Body()]) -> s.SystemSettings:
    return await service.update_company_settings(db, actor, body)


@router.get("/branches", response_model=ListResponse[s.BranchOut], summary="Branches you can access", responses=ERR)
async def list_branches(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await service.list_branches(db, actor))


@router.post("/branches", response_model=s.BranchOut, status_code=status.HTTP_201_CREATED, summary="Create a branch (and its store warehouse)", responses=ERR)
async def create_branch(body: s.BranchCreate, actor: Admin, db: DbSession) -> Any:
    return await service.create_branch(db, actor, body)


@router.patch("/branches/{branch_id}", response_model=s.BranchOut, summary="Update a branch", responses=ERR)
async def update_branch(branch_id: uuid.UUID, body: s.BranchUpdate, actor: Admin, db: DbSession) -> Any:
    return await service.update_branch(db, actor, branch_id, body)


@router.get("/warehouses", response_model=ListResponse[s.WarehouseOut], summary="Warehouses you can access", responses=ERR)
async def list_warehouses(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await service.list_warehouses(db, actor))


@router.post("/warehouses", response_model=s.WarehouseOut, status_code=status.HTTP_201_CREATED, summary="Create a warehouse", responses=ERR)
async def create_warehouse(body: s.WarehouseCreate, actor: Admin, db: DbSession) -> dict:
    return await service.create_warehouse(db, actor, body)


@router.patch("/warehouses/{warehouse_id}", response_model=s.WarehouseOut, summary="Update a warehouse", responses=ERR)
async def update_warehouse(warehouse_id: uuid.UUID, body: s.WarehouseUpdate, actor: Admin, db: DbSession) -> dict:
    return await service.update_warehouse(db, actor, warehouse_id, body)


@router.get("/locations", response_model=ListResponse[s.LocationOut], summary="Stock locations you can access", responses=ERR)
async def list_locations(actor: CurrentPrincipal, db: DbSession, warehouse_id: uuid.UUID | None = None) -> dict:
    return page(await service.list_locations(db, actor, warehouse_id))


@router.post("/locations", response_model=s.LocationOut, status_code=status.HTTP_201_CREATED, summary="Create a stock location", responses=ERR,
             description="In-transit locations are system-managed and cannot be created. Damaged, expired, quarantine, receiving and returns locations are never sellable.")
async def create_location(body: s.LocationCreate, actor: Admin, db: DbSession) -> dict:
    return await service.create_location(db, actor, body)


@router.patch("/locations/{location_id}", response_model=s.LocationOut, summary="Update a stock location", responses=ERR)
async def update_location(location_id: uuid.UUID, body: s.LocationUpdate, actor: Admin, db: DbSession) -> dict:
    return await service.update_location(db, actor, location_id, body)


@router.get("/terminals", response_model=ListResponse[s.TerminalOut], summary="POS terminals in your branches", responses=ERR)
async def list_terminals(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await service.list_terminals(db, actor))


@router.post("/terminals", response_model=s.TerminalOut, status_code=status.HTTP_201_CREATED, summary="Register a POS terminal", responses=ERR)
async def create_terminal(body: s.TerminalCreate, actor: Admin, db: DbSession) -> dict:
    return await service.create_terminal(db, actor, body)


@router.patch("/terminals/{terminal_id}", response_model=s.TerminalOut, summary="Update a POS terminal and its cashiers", responses=ERR)
async def update_terminal(terminal_id: uuid.UUID, body: s.TerminalUpdate, actor: Admin, db: DbSession) -> dict:
    return await service.update_terminal(db, actor, terminal_id, body)


@router.get("/tax-codes", response_model=ListResponse[s.TaxCodeOut], summary="Tax codes", responses=ERR)
async def list_tax_codes(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await service.list_records(db, actor, TaxCode, TaxCode.code))


@router.post("/tax-codes", response_model=s.TaxCodeOut, status_code=status.HTTP_201_CREATED, summary="Create a tax code", responses=ERR,
             description="Rates are configuration to be confirmed with an accountant (V-01); none are seeded.")
async def create_tax_code(body: s.TaxCodeCreate, actor: Admin, db: DbSession) -> Any:
    return await service.create_record(db, actor, TaxCode, body, "tax_code")


@router.patch("/tax-codes/{tax_code_id}", response_model=s.TaxCodeOut, summary="Update a tax code (rate changes are flagged)", responses=ERR)
async def update_tax_code(tax_code_id: uuid.UUID, body: s.TaxCodeUpdate, actor: Admin, db: DbSession) -> Any:
    return await service.update_record(db, actor, TaxCode, tax_code_id, body, "tax_code", "Tax code")


@router.get("/payment-methods", response_model=ListResponse[s.PaymentMethodOut], summary="Payment methods", responses=ERR)
async def list_payment_methods(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await service.list_records(db, actor, PaymentMethod, PaymentMethod.code))


@router.post("/payment-methods", response_model=s.PaymentMethodOut, status_code=status.HTTP_201_CREATED, summary="Add a payment method", responses=ERR)
async def create_payment_method(body: s.PaymentMethodCreate, actor: Admin, db: DbSession) -> Any:
    return await service.create_record(db, actor, PaymentMethod, body, "payment_method")


@router.patch("/payment-methods/{method_id}", response_model=s.PaymentMethodOut, summary="Update a payment method", responses=ERR)
async def update_payment_method(method_id: uuid.UUID, body: s.PaymentMethodUpdate, actor: Admin, db: DbSession) -> Any:
    return await service.update_record(db, actor, PaymentMethod, method_id, body, "payment_method", "Payment method", unique=None)


@router.get("/currencies/rates", response_model=ListResponse[s.ExchangeRateOut], summary="Exchange rate history, newest first", responses=ERR)
async def list_rates(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await service.list_rates(db, actor))


@router.post("/currencies/rates", response_model=s.ExchangeRateOut, status_code=status.HTTP_201_CREATED, summary="Set a new USD to KHR rate", responses=ERR,
             description="Applies to new sales from now on. Completed sales keep the rate they were made with.")
async def create_rate(body: s.ExchangeRateCreate, actor: Admin, db: DbSession) -> dict:
    return await service.create_rate(db, actor, body)


@router.get("/document-sequences", response_model=ListResponse[s.SequenceOut], summary="Document numbering formats", responses=ERR)
async def list_sequences(actor: Admin, db: DbSession) -> dict:
    return page(await service.list_sequences(db, actor))


@router.patch("/document-sequences/{doc_type}", response_model=s.SequenceOut, summary="Change a numbering format", responses=ERR,
              description="The counter can only move forward, so a number is never issued twice.")
async def update_sequence(doc_type: str, body: s.SequenceUpdate, actor: Admin, db: DbSession) -> dict:
    return await service.update_sequence(db, actor, doc_type.upper(), body)


@router.get("/receipt-templates", response_model=ListResponse[s.ReceiptTemplateOut], summary="Receipt templates", responses=ERR)
async def list_receipt_templates(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await service.list_records(db, actor, ReceiptTemplate, ReceiptTemplate.name))


@router.post("/receipt-templates", response_model=s.ReceiptTemplateOut, status_code=status.HTTP_201_CREATED, summary="Create a receipt template", responses=ERR)
async def create_receipt_template(body: s.ReceiptTemplateCreate, actor: Admin, db: DbSession) -> Any:
    return await service.create_record(db, actor, ReceiptTemplate, body, "receipt_template", unique=None)


@router.patch("/receipt-templates/{template_id}", response_model=s.ReceiptTemplateOut, summary="Update a receipt template", responses=ERR)
async def update_receipt_template(template_id: uuid.UUID, body: s.ReceiptTemplateUpdate, actor: Admin, db: DbSession) -> Any:
    return await service.update_record(db, actor, ReceiptTemplate, template_id, body, "receipt_template", "Receipt template", unique=None)


@router.delete("/receipt-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a receipt template", responses=ERR)
async def delete_receipt_template(template_id: uuid.UUID, actor: Admin, db: DbSession) -> Response:
    await service.delete_receipt_template(db, actor, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
