"""Catalogue and pricing endpoints (PRD, CAT, PRC; Phase 3)."""

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentPrincipal, DbSession, require
from app.core.config import get_settings
from app.core.exceptions import NotFound
from app.models import PriceList
from app.schemas import catalog as s
from app.schemas.common import ListResponse, error_responses
from app.services import catalog, pricing, products
from app.services.principal import Principal

router = APIRouter()
ERR = error_responses(401, 403, 404, 409, 422)
Viewer = Annotated[Principal, Depends(require("products.product.view", "pos.sale.create"))]
Creator = Annotated[Principal, Depends(require("products.product.create"))]
Editor = Annotated[Principal, Depends(require("products.product.edit"))]
Deleter = Annotated[Principal, Depends(require("products.product.delete"))]
CatalogAdmin = Annotated[Principal, Depends(require("products.category.manage"))]
PriceViewer = Annotated[Principal, Depends(require("pricing.price.view", "pricing.price.edit"))]
PriceEditor = Annotated[Principal, Depends(require("pricing.price.edit"))]
Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


def page(items: list, total: int | None = None) -> dict:
    return {"items": items, "total": len(items) if total is None else total}


# Products (static paths first so they are not read as product ids)

@router.get("/products", response_model=ListResponse[s.ProductOut], tags=["Products"], summary="Search products", responses=ERR,
            description="`q` matches name (English or Khmer), SKU or an exact barcode. `sellable=true` returns only active, sellable products for POS.")
async def list_products(actor: Viewer, db: DbSession, q: str | None = None, category_id: uuid.UUID | None = None, brand_id: uuid.UUID | None = None,
                        status_filter: Annotated[str | None, Query(alias="status", pattern="^(DRAFT|ACTIVE|INACTIVE|DISCONTINUED)$")] = None,
                        type_filter: Annotated[str | None, Query(alias="type", pattern="^(STANDARD|WEIGHED|VARIANT_PARENT|SERVICE)$")] = None,
                        sellable: bool = False, limit: Limit = 50, offset: Offset = 0) -> dict:
    items, total = await products.list_products(db, actor, q=q, category_id=category_id, brand_id=brand_id, status=status_filter, type_=type_filter, sellable=sellable, limit=limit, offset=offset)
    return page(items, total)


@router.post("/products", response_model=s.ProductOut, status_code=status.HTTP_201_CREATED, tags=["Products"], summary="Create a product (with variants)", responses=ERR)
async def create_product(body: s.ProductCreate, actor: Creator, db: DbSession) -> dict:
    return await products.create_product(db, actor, body)


@router.get("/products/barcodes", response_model=ListResponse[s.BarcodeRowOut], tags=["Products"], summary="All barcodes", responses=ERR)
async def list_barcodes(actor: Viewer, db: DbSession, q: str | None = None, limit: Limit = 500, offset: Offset = 0) -> dict:
    return page(await products.list_barcodes(db, actor, q, limit, offset))


@router.post("/products/barcodes/generate", response_model=s.GeneratedBarcode, tags=["Products"], summary="Generate an in-store EAN-13 barcode", responses=ERR)
async def generate_barcode(actor: Annotated[Principal, Depends(require("products.product.edit", "products.product.create"))], db: DbSession) -> dict:
    return await products.generate_barcode(db, actor)


@router.get("/products/barcode/{barcode}", response_model=s.ScanResult, tags=["Products"], summary="Scan: find the product, unit and price for a barcode", responses=ERR)
async def scan(barcode: str, actor: Viewer, db: DbSession, branch_id: uuid.UUID | None = None) -> dict:
    return await products.scan(db, actor, barcode, branch_id)


@router.get("/products/{product_id}", response_model=s.ProductOut, tags=["Products"], summary="Product detail", responses=ERR)
async def get_product(product_id: uuid.UUID, actor: Viewer, db: DbSession) -> dict:
    return await products.get_product(db, actor, product_id)


@router.patch("/products/{product_id}", response_model=s.ProductOut, tags=["Products"], summary="Update a product", responses=ERR,
              description="Lists sent (conversions, barcodes, warehouse settings, branch activation) replace the stored ones. Barcodes left out are deactivated, not deleted.")
async def update_product(product_id: uuid.UUID, body: s.ProductUpdate, actor: Editor, db: DbSession) -> dict:
    return await products.update_product(db, actor, product_id, body)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Products"], summary="Delete a draft product without movements", responses=ERR)
async def delete_product(product_id: uuid.UUID, actor: Deleter, db: DbSession) -> Response:
    await products.delete_product(db, actor, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/products/{product_id}/history", response_model=ListResponse[s.ProductChangeOut], tags=["Products"], summary="Field-level change history", responses=ERR)
async def product_history(product_id: uuid.UUID, actor: Viewer, db: DbSession) -> dict:
    return page(await products.history(db, actor, product_id))


@router.post("/products/{product_id}/duplicate", response_model=s.ProductOut, status_code=status.HTTP_201_CREATED, tags=["Products"], summary="Copy a product as a new draft", responses=ERR)
async def duplicate_product(product_id: uuid.UUID, actor: Creator, db: DbSession) -> dict:
    return await products.duplicate_product(db, actor, product_id)


@router.get("/products/{product_id}/price", response_model=s.ResolvedPrice, tags=["Pricing"], summary="Resolve the selling price for a unit and branch", responses=ERR)
async def resolve_price(product_id: uuid.UUID, actor: Viewer, db: DbSession, unit_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None) -> dict:
    return await pricing.resolve_for(db, actor, product_id, unit_id, branch_id)


@router.get("/files/products/{name}", tags=["Products"], summary="Product image", include_in_schema=True, responses=error_responses(404),
            description="Public so <img> tags can load it; names are random and unguessable.")
async def product_image(name: str) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{32}\.(jpg|png|webp)", name):
        raise NotFound("Image")
    path = get_settings().storage_dir / "products" / name
    if not path.is_file():
        raise NotFound("Image")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


# Categories, brands, units

@router.get("/categories", response_model=ListResponse[s.CategoryOut], tags=["Catalogue"], summary="Categories", responses=ERR)
async def list_categories(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await catalog.list_categories(db, actor))


@router.post("/categories", response_model=s.CategoryOut, status_code=status.HTTP_201_CREATED, tags=["Catalogue"], summary="Create a category", responses=ERR)
async def create_category(body: s.CategoryCreate, actor: CatalogAdmin, db: DbSession) -> Any:
    return await catalog.create_category(db, actor, body)


@router.patch("/categories/{category_id}", response_model=s.CategoryOut, tags=["Catalogue"], summary="Update a category", responses=ERR)
async def update_category(category_id: uuid.UUID, body: s.CategoryUpdate, actor: CatalogAdmin, db: DbSession) -> Any:
    return await catalog.update_category(db, actor, category_id, body)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Catalogue"], summary="Delete an unused category", responses=ERR)
async def delete_category(category_id: uuid.UUID, actor: CatalogAdmin, db: DbSession) -> Response:
    await catalog.delete_category(db, actor, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/brands", response_model=ListResponse[s.BrandOut], tags=["Catalogue"], summary="Brands", responses=ERR)
async def list_brands(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await catalog.list_brands(db, actor))


@router.post("/brands", response_model=s.BrandOut, status_code=status.HTTP_201_CREATED, tags=["Catalogue"], summary="Create a brand", responses=ERR)
async def create_brand(body: s.BrandCreate, actor: CatalogAdmin, db: DbSession) -> Any:
    return await catalog.create_brand(db, actor, body)


@router.patch("/brands/{brand_id}", response_model=s.BrandOut, tags=["Catalogue"], summary="Update a brand", responses=ERR)
async def update_brand(brand_id: uuid.UUID, body: s.BrandUpdate, actor: CatalogAdmin, db: DbSession) -> Any:
    return await catalog.update_brand(db, actor, brand_id, body)


@router.delete("/brands/{brand_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Catalogue"], summary="Delete an unused brand", responses=ERR)
async def delete_brand(brand_id: uuid.UUID, actor: CatalogAdmin, db: DbSession) -> Response:
    await catalog.delete_brand(db, actor, brand_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/units", response_model=ListResponse[s.UnitOut], tags=["Catalogue"], summary="Units of measure", responses=ERR)
async def list_units(actor: CurrentPrincipal, db: DbSession) -> dict:
    return page(await catalog.list_units(db, actor))


@router.post("/units", response_model=s.UnitOut, status_code=status.HTTP_201_CREATED, tags=["Catalogue"], summary="Create a unit", responses=ERR)
async def create_unit(body: s.UnitCreate, actor: CatalogAdmin, db: DbSession) -> Any:
    return await catalog.create_unit(db, actor, body)


@router.patch("/units/{unit_id}", response_model=s.UnitOut, tags=["Catalogue"], summary="Update a unit", responses=ERR)
async def update_unit(unit_id: uuid.UUID, body: s.UnitUpdate, actor: CatalogAdmin, db: DbSession) -> Any:
    return await catalog.update_unit(db, actor, unit_id, body)


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Catalogue"], summary="Delete an unused unit", responses=ERR)
async def delete_unit(unit_id: uuid.UUID, actor: CatalogAdmin, db: DbSession) -> Response:
    await catalog.delete_unit(db, actor, unit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Pricing

@router.get("/price-lists", response_model=ListResponse[s.PriceListOut], tags=["Pricing"], summary="Price lists", responses=ERR)
async def list_price_lists(actor: PriceViewer, db: DbSession) -> dict:
    rows = list(await db.scalars(select(PriceList).where(PriceList.company_id == actor.company_id).order_by(PriceList.code)))
    return page(rows)


@router.get("/prices", response_model=ListResponse[s.PriceOut], tags=["Pricing"], summary="Prices (current and scheduled by default)", responses=ERR)
async def list_prices(actor: PriceViewer, db: DbSession, product_id: uuid.UUID | None = None, price_list_id: uuid.UUID | None = None, branch_id: uuid.UUID | None = None,
                      include_past: bool = False, limit: Limit = 200, offset: Offset = 0) -> dict:
    return page(await pricing.list_prices(db, actor, product_id=product_id, price_list_id=price_list_id, branch_id=branch_id, current_only=not include_past, limit=limit, offset=offset))


@router.post("/prices", response_model=s.PriceOut, status_code=status.HTTP_201_CREATED, tags=["Pricing"], summary="Set a price from now or a future date", responses=ERR,
             description="Closes the current price for the same scope at the new start. Prices cannot be backdated or overlap; a temporary price inside an open period belongs in Promotions.")
async def create_price(body: s.PriceCreate, actor: PriceEditor, db: DbSession) -> dict:
    return await pricing.create_price(db, actor, body)


@router.delete("/prices/{price_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Pricing"], summary="Remove a scheduled price that has not started", responses=ERR)
async def delete_price(price_id: uuid.UUID, actor: PriceEditor, db: DbSession) -> Response:
    await pricing.delete_price(db, actor, price_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/prices/history", response_model=ListResponse[s.PriceHistoryOut], tags=["Pricing"], summary="Price change history", responses=ERR)
async def price_history(actor: PriceViewer, db: DbSession, product_id: uuid.UUID | None = None, limit: Limit = 200, offset: Offset = 0) -> dict:
    return page(await pricing.history(db, actor, product_id, limit, offset))


@router.post("/prices/bulk/preview", response_model=ListResponse[s.BulkPreviewRow], tags=["Pricing"], summary="Preview a bulk retail price change", responses=ERR)
async def bulk_preview(body: s.BulkPriceInput, actor: PriceEditor, db: DbSession) -> dict:
    return page(await pricing.bulk_preview(db, actor, body))


@router.post("/prices/bulk", response_model=s.BulkApplyResult, tags=["Pricing"], summary="Apply a bulk retail price change", responses=ERR,
             description="Rejected as a whole if any new price would fall below its product's minimum selling price.")
async def bulk_apply(body: s.BulkPriceInput, actor: PriceEditor, db: DbSession) -> dict:
    return await pricing.bulk_apply(db, actor, body)
