import type {
  BarcodeRow, BarcodeSymbology, Brand, BulkPricePreviewRow, Category, Coupon, CustomerGroup, Product, ProductBarcode, ProductListItem, ProductPrice,
  Promotion, Unit,
} from "@/types";
import { audit, branchFilter, can, canSeeCost, assertNotSelfApproval, fail, list, notFound, requirePerm, requireUser, requiredString, round, uid, validation, type Ctx } from "../core";
import { availableAt, getProduct } from "../domain/inventory";
import { resolvePrice } from "../domain/pricing";
import { getTerminal } from "../domain/sales";
import { DELETE, GET, PATCH, POST, assertUniqueCode, crud } from "../registry";
import type { MockDb } from "../db";
import { detectSymbology, ean13CheckDigit, validateBarcode } from "@/lib/barcode";

function listItem(ctx: Ctx, product: Product, locationId?: string): ProductListItem {
  const { db } = ctx;
  const filter = branchFilter({ ...ctx, query: { branchId: ctx.query.branchId } });
  const sellable = new Set(
    db.locations.filter((l) => l.availableToSell && filter(db.warehouses.find((w) => w.id === l.warehouseId)?.branchId ?? null)).map((l) => l.id),
  );
  const balances = db.balances.filter((b) => b.productId === product.id && (locationId ? b.locationId === locationId : sellable.has(b.locationId)));
  return {
    ...product,
    categoryName: db.categories.find((c) => c.id === product.categoryId)?.nameEn ?? "",
    brandName: db.brands.find((b) => b.id === product.brandId)?.name ?? "",
    unitCode: db.units.find((u) => u.id === product.baseUnitId)?.code ?? "",
    available: round(balances.reduce((s, b) => s + b.onHand - b.reserved, 0), 4),
    onHand: round(balances.reduce((s, b) => s + b.onHand, 0), 4),
  };
}

function recordChange(ctx: Ctx, product: Product, field: string, before: unknown, after: unknown) {
  if (JSON.stringify(before) === JSON.stringify(after)) return;
  ctx.db.productChanges.unshift({
    id: uid("chg"),
    productId: product.id,
    at: ctx.now.toISOString(),
    userName: requireUser(ctx).fullName,
    field,
    before: typeof before === "string" ? before : JSON.stringify(before),
    after: typeof after === "string" ? after : JSON.stringify(after),
  });
}

function assertBarcodes(db: MockDb, barcodes: Pick<ProductBarcode, "barcode" | "symbology" | "active">[], productId: string | null) {
  const seen = new Set<string>();
  for (const code of barcodes) {
    if (!code.active) continue;
    const message = validateBarcode(code.barcode, code.symbology);
    if (message) fail(422, "VALIDATION_ERROR", message, [{ field: "barcodes", message }]);
    if (seen.has(code.barcode)) fail(422, "BARCODE_IN_USE", `Barcode ${code.barcode} is entered twice.`, [{ field: "barcodes", message: "Duplicate barcode." }]);
    seen.add(code.barcode);
    const owner = db.products.find((p) => p.id !== productId && p.barcodes.some((b) => b.active && b.barcode === code.barcode));
    if (owner) {
      const message2 = `Barcode ${code.barcode} is assigned to ${owner.nameEn}`;
      fail(422, "BARCODE_IN_USE", message2, [{ field: "barcodes", message: message2 }]);
    }
  }
}

function assertConversions(db: MockDb, input: Partial<Product>) {
  for (const conversion of input.conversions ?? []) {
    if (!(conversion.factor > 0)) validation("conversions", "Conversion factor must be greater than zero.");
    const base = db.units.find((u) => u.id === input.baseUnitId);
    if (base && base.precision === 0 && !input.allowFraction && !Number.isInteger(conversion.factor)) {
      validation("conversions", "Conversion factor must be a whole number for this unit.");
    }
  }
}

function nextSku(ctx: Ctx, categoryId: string) {
  const { db } = ctx;
  const category = db.categories.find((c) => c.id === categoryId);
  const prefix = `${db.settings.skuPrefix}${category?.code ?? "GEN"}`;
  let n = db.products.filter((p) => p.sku.startsWith(prefix)).length + 1;
  while (db.products.some((p) => p.sku === `${prefix}-${String(n).padStart(4, "0")}`)) n += 1;
  return `${prefix}-${String(n).padStart(4, "0")}`;
}

export function createProduct(ctx: Ctx, input: Partial<Product>): Product {
  const { db } = ctx;
  const sku = input.sku?.trim() || (db.settings.skuMode === "AUTO" ? nextSku(ctx, input.categoryId ?? "") : "");
  if (!sku) validation("sku", "SKU is required.");
  if (db.products.some((p) => p.sku.toLowerCase() === sku.toLowerCase())) fail(409, "DUPLICATE_SKU", "SKU already exists", [{ field: "sku", message: "SKU already exists" }]);
  assertBarcodes(db, input.barcodes ?? [], null);
  assertConversions(db, input);
  const category = db.categories.find((c) => c.id === input.categoryId);
  if (!category) return validation("categoryId", "Category is required.");
  if (!db.units.some((u) => u.id === input.baseUnitId)) validation("baseUnitId", "Base unit is required.");
  const product: Product = {
    id: uid("prd"),
    sku,
    nameEn: requiredString(input.nameEn, "nameEn", "English name"),
    nameKm: input.nameKm ?? "",
    description: input.description ?? "",
    type: input.type ?? "STANDARD",
    parentId: input.parentId ?? null,
    variantAttrs: input.variantAttrs ?? null,
    categoryId: category.id,
    brandId: input.brandId ?? null,
    baseUnitId: input.baseUnitId as string,
    allowFraction: input.allowFraction ?? false,
    precision: input.precision ?? 0,
    taxCodeId: input.taxCodeId === undefined ? category.defaultTaxCodeId : input.taxCodeId,
    status: input.status ?? "DRAFT",
    image: input.image ?? null,
    conversions: input.conversions ?? [],
    barcodes: (input.barcodes ?? []).map((b) => ({ ...b, id: b.id || uid("bc"), createdAt: ctx.now.toISOString() })),
    retailPrice: input.retailPrice ?? 0,
    wholesalePrice: input.wholesalePrice ?? input.retailPrice ?? 0,
    minSellingPrice: input.minSellingPrice ?? null,
    lastPurchaseCost: input.lastPurchaseCost ?? 0,
    avgCost: input.avgCost ?? input.lastPurchaseCost ?? 0,
    stockSettings: input.stockSettings ?? { reorderLevel: 0, minLevel: 0, maxLevel: 0, reorderQty: 0 },
    warehouseSettings: input.warehouseSettings ?? {},
    suppliers: input.suppliers ?? [],
    trackExpiry: input.trackExpiry ?? category.expiryTrackingDefault,
    isFavourite: input.isFavourite ?? false,
    hasMovements: false,
    branchActivation: input.branchActivation ?? {},
    createdAt: ctx.now.toISOString(),
    updatedAt: ctx.now.toISOString(),
  };
  db.products.unshift(product);
  audit(ctx, "PRODUCT_CREATED", "PRD", "product", product.id, { after: { sku: product.sku, name: product.nameEn } });
  return product;
}

GET("/products", (ctx) => {
  requirePerm(ctx, "products.view", "pos.sell", "pos.hold");
  const { db, query } = ctx;
  let rows = db.products;
  if (query.status) rows = rows.filter((p) => p.status === query.status);
  if (query.sellable) rows = rows.filter((p) => (p.status === "ACTIVE" || p.status === "DISCONTINUED") && p.type !== "VARIANT_PARENT");
  const location = query.terminalId ? getTerminal(db, String(query.terminalId)).defaultLocationId : undefined;
  return list(rows.map((p) => listItem(ctx, p, location)));
});

GET("/products/barcodes", (ctx) => {
  requirePerm(ctx, "products.view");
  const rows: BarcodeRow[] = ctx.db.products.flatMap((p) =>
    p.barcodes.map((b) => ({ ...b, productId: p.id, sku: p.sku, productName: p.nameEn, unitCode: ctx.db.units.find((u) => u.id === b.unitId)?.code ?? "" })),
  );
  return list(rows);
});

GET("/products/barcode/:barcode", (ctx) => {
  requirePerm(ctx, "products.view", "pos.sell");
  const { db } = ctx;
  const hit = db.products.flatMap((p) => p.barcodes.filter((b) => b.active && b.barcode === ctx.params.barcode).map((b) => ({ p, b })))[0];
  if (!hit) return fail(404, "BARCODE_NOT_FOUND", "Barcode not found — search by name.");
  const terminal = ctx.query.terminalId ? db.terminals.find((t) => t.id === ctx.query.terminalId) : db.terminals[0];
  const customer = ctx.query.customerId ? db.customers.find((c) => c.id === ctx.query.customerId) ?? null : null;
  const resolved = resolvePrice(db, hit.p, hit.b.unitId, terminal?.branchId ?? db.branches[0].id, customer, ctx.now);
  return {
    product: listItem(ctx, hit.p, terminal?.defaultLocationId),
    unitId: hit.b.unitId,
    unitCode: db.units.find((u) => u.id === hit.b.unitId)?.code ?? "",
    unitPrice: resolved.price,
    priceSource: resolved.source,
    priceExplanation: resolved.explanation,
    availableQty: terminal ? availableAt(db, terminal.defaultLocationId, hit.p.id) : 0,
  };
});

POST("/products/barcodes/generate", (ctx) => {
  requirePerm(ctx, "products.edit", "products.create");
  let code = "";
  let counter = ctx.db.products.flatMap((p) => p.barcodes).length + 1000;
  do {
    const body = `200${String(counter++).padStart(9, "0")}`;
    code = body + ean13CheckDigit(body);
  } while (ctx.db.products.some((p) => p.barcodes.some((b) => b.barcode === code)));
  return { barcode: code, symbology: "EAN13" as BarcodeSymbology };
});

GET("/products/:id", (ctx) => {
  requirePerm(ctx, "products.view");
  return listItem(ctx, getProduct(ctx.db, ctx.params.id));
});

GET("/products/:id/history", (ctx) => {
  requirePerm(ctx, "products.view");
  return list(ctx.db.productChanges.filter((c) => c.productId === ctx.params.id));
});

POST("/products", (ctx) => {
  requirePerm(ctx, "products.create");
  const input = ctx.body as Partial<Product> & { variants?: { attrs: Record<string, string>; sku: string; barcode?: string; retailPrice?: number }[] };
  const { variants, ...rest } = input;
  const product = createProduct(ctx, rest);
  for (const variant of variants ?? []) {
    createProduct(ctx, {
      ...rest,
      sku: variant.sku,
      nameEn: `${product.nameEn} - ${Object.values(variant.attrs).join(" / ")}`,
      nameKm: product.nameKm,
      type: "STANDARD",
      parentId: product.id,
      variantAttrs: variant.attrs,
      retailPrice: variant.retailPrice ?? product.retailPrice,
      barcodes: variant.barcode ? [{ id: "", barcode: variant.barcode, symbology: detectSymbology(variant.barcode), unitId: product.baseUnitId, active: true, createdAt: "" }] : [],
    });
  }
  return listItem(ctx, product);
});

PATCH("/products/:id", (ctx) => {
  requirePerm(ctx, "products.edit");
  const { db } = ctx;
  const product = getProduct(db, ctx.params.id);
  const input = ctx.body as Partial<Product>;
  if (input.baseUnitId && input.baseUnitId !== product.baseUnitId && product.hasMovements) {
    return validation("baseUnitId", "Base unit cannot change after stock movements");
  }
  if (input.sku && db.products.some((p) => p.sku.toLowerCase() === input.sku!.toLowerCase() && p.id !== product.id)) {
    return fail(409, "DUPLICATE_SKU", "SKU already exists", [{ field: "sku", message: "SKU already exists" }]);
  }
  if (input.barcodes) assertBarcodes(db, input.barcodes, product.id);
  assertConversions(db, { ...product, ...input });
  // Cost fields are ledger-derived; a client cannot set them (BR-CST-001, section 13.4).
  const { avgCost: _a, lastPurchaseCost: _l, hasMovements: _h, id: _i, ...patch } = input;
  void _a; void _l; void _h; void _i;
  if (!can(ctx, "costs.view")) delete patch.suppliers;
  for (const key of Object.keys(patch) as (keyof typeof patch)[]) {
    recordChange(ctx, product, key, product[key], patch[key]);
  }
  if (input.retailPrice !== undefined && input.retailPrice !== product.retailPrice) {
    db.priceHistory.unshift({ id: uid("ph"), productId: product.id, sku: product.sku, productName: product.nameEn, scope: "Standard retail", oldPrice: product.retailPrice, newPrice: input.retailPrice, effectiveFrom: ctx.now.toISOString(), userName: requireUser(ctx).fullName, at: ctx.now.toISOString(), approvedBy: null });
  }
  if (patch.barcodes) patch.barcodes = patch.barcodes.map((b) => ({ ...b, id: b.id || uid("bc"), createdAt: b.createdAt || ctx.now.toISOString() }));
  Object.assign(product, patch, { updatedAt: ctx.now.toISOString() });
  audit(ctx, "PRODUCT_UPDATED", "PRD", "product", product.id, { after: Object.keys(patch) });
  return listItem(ctx, product);
});

POST("/products/:id/duplicate", (ctx) => {
  requirePerm(ctx, "products.create");
  const source = getProduct(ctx.db, ctx.params.id);
  return listItem(ctx, createProduct(ctx, { ...source, sku: "", nameEn: `${source.nameEn} (copy)`, barcodes: [], status: "DRAFT", avgCost: 0, lastPurchaseCost: source.lastPurchaseCost }));
});

DELETE("/products/:id", (ctx) => {
  requirePerm(ctx, "products.delete");
  const product = getProduct(ctx.db, ctx.params.id);
  if (product.status !== "DRAFT" || product.hasMovements) return fail(409, "IN_USE", "Only draft products without movements can be deleted. Deactivate this product instead.");
  ctx.db.products = ctx.db.products.filter((p) => p.id !== product.id);
  audit(ctx, "PRODUCT_DELETED", "PRD", "product", product.id, { before: { sku: product.sku } });
  return undefined;
});

crud<Category>("/categories", "categories", {
  view: ["products.view", "pos.sell", "pos.hold"],
  manage: ["products.create", "products.edit"],
  prefix: "cat",
  module: "CAT",
  validate: (ctx, input, existing) => {
    assertUniqueCode(ctx.db.categories, input.code, existing);
    if (input.parentId) {
      let depth = 1;
      let cursor = ctx.db.categories.find((c) => c.id === input.parentId);
      while (cursor) {
        if (cursor.id === existing?.id) validation("parentId", "A category cannot be nested inside itself.");
        depth += 1;
        cursor = ctx.db.categories.find((c) => c.id === cursor?.parentId);
      }
      if (depth > 4) validation("parentId", "Categories can be nested up to 4 levels.");
    }
  },
  beforeDelete: (ctx, row) => {
    if (ctx.db.products.some((p) => p.categoryId === row.id) || ctx.db.categories.some((c) => c.parentId === row.id)) {
      fail(409, "IN_USE", "This category has products or subcategories.");
    }
  },
});

crud<Brand>("/brands", "brands", {
  view: ["products.view"],
  manage: ["products.create", "products.edit"],
  prefix: "brn",
  module: "CAT",
  validate: (ctx, input, existing) => assertUniqueCode(ctx.db.brands, input.code, existing),
  beforeDelete: (ctx, row) => {
    if (ctx.db.products.some((p) => p.brandId === row.id)) fail(409, "IN_USE", "Products use this brand.");
  },
});

crud<Unit>("/units", "units", {
  view: ["products.view", "pos.sell", "purchasing.view", "inventory.view"],
  manage: ["products.create", "products.edit"],
  prefix: "unit",
  module: "CAT",
  validate: (ctx, input, existing) => assertUniqueCode(ctx.db.units, input.code, existing),
  beforeDelete: (ctx, row) => {
    if (ctx.db.products.some((p) => p.baseUnitId === row.id || p.conversions.some((c) => c.unitId === row.id))) fail(409, "IN_USE", "Products use this unit.");
  },
});

// Pricing
GET("/price-lists", (ctx) => {
  requirePerm(ctx, "pricing.view");
  return list(ctx.db.priceLists);
});

function describeScope(ctx: Ctx, price: ProductPrice) {
  const { db } = ctx;
  if (price.customerGroupId) return `Group: ${db.customerGroups.find((g) => g.id === price.customerGroupId)?.name ?? ""}`;
  if (price.branchId) return `Branch: ${db.branches.find((b) => b.id === price.branchId)?.nameEn ?? ""}`;
  return db.priceLists.find((l) => l.id === price.priceListId)?.name ?? "Standard";
}

GET("/prices", (ctx) => {
  requirePerm(ctx, "pricing.view");
  return list(ctx.db.prices.map((p) => {
    const product = ctx.db.products.find((x) => x.id === p.productId);
    return { ...p, sku: product?.sku, productName: product?.nameEn, scopeLabel: describeScope(ctx, p) };
  }));
});

GET("/prices/history", (ctx) => {
  requirePerm(ctx, "pricing.view");
  return list(ctx.db.priceHistory.slice(0, 1000));
});

function currentPriceForScope(product: Product, input: Pick<ProductPrice, "priceListId" | "branchId" | "customerGroupId">, wholesaleListId?: string) {
  if (input.priceListId === wholesaleListId) return product.wholesalePrice;
  return product.retailPrice;
}

function addPrice(ctx: Ctx, input: Omit<ProductPrice, "id" | "createdBy">) {
  const { db } = ctx;
  const product = getProduct(db, input.productId);
  if (input.price < 0) validation("price", "Price must not be negative.");
  if (input.effectiveTo && input.effectiveTo <= input.effectiveFrom) validation("effectiveTo", "End must be after start.");
  const overlap = db.prices.some(
    (p) =>
      p.productId === input.productId && p.unitId === input.unitId && p.priceListId === input.priceListId && p.branchId === input.branchId &&
      p.customerGroupId === input.customerGroupId &&
      (p.effectiveTo === null || p.effectiveTo > input.effectiveFrom) &&
      (input.effectiveTo === null || p.effectiveFrom < input.effectiveTo),
  );
  if (overlap) {
    // An open-ended price is closed by a later-starting one; true overlaps are rejected (BR-PRC-001).
    const open = db.prices.find(
      (p) =>
        p.productId === input.productId && p.unitId === input.unitId && p.priceListId === input.priceListId && p.branchId === input.branchId &&
        p.customerGroupId === input.customerGroupId && p.effectiveTo === null && p.effectiveFrom < input.effectiveFrom,
    );
    if (!open) fail(422, "PRICE_OVERLAP", "This price overlaps an existing price for the same scope.", [{ field: "effectiveFrom", message: "Overlaps an existing price." }]);
    open!.effectiveTo = input.effectiveFrom;
  }
  const row: ProductPrice = { ...input, id: uid("prc"), createdBy: requireUser(ctx).fullName };
  db.prices.unshift(row);
  const wholesale = db.priceLists.find((l) => l.type === "WHOLESALE")?.id;
  db.priceHistory.unshift({
    id: uid("ph"), productId: product.id, sku: product.sku, productName: product.nameEn, scope: describeScope(ctx, row),
    oldPrice: currentPriceForScope(product, row, wholesale), newPrice: row.price, effectiveFrom: row.effectiveFrom,
    userName: requireUser(ctx).fullName, at: ctx.now.toISOString(), approvedBy: null,
  });
  audit(ctx, "PRICE_CHANGED", "PRC", "price", row.id, { after: { sku: product.sku, price: row.price, scope: describeScope(ctx, row) } });
  return row;
}

POST("/prices", (ctx) => {
  requirePerm(ctx, "pricing.edit");
  return addPrice(ctx, ctx.body as Omit<ProductPrice, "id" | "createdBy">);
});

DELETE("/prices/:id", (ctx) => {
  requirePerm(ctx, "pricing.edit");
  const row = ctx.db.prices.find((p) => p.id === ctx.params.id);
  if (!row) return notFound("Price");
  if (row.effectiveFrom <= ctx.now.toISOString()) return fail(409, "IN_USE", "A price already in effect cannot be deleted. End it with a new price.");
  ctx.db.prices = ctx.db.prices.filter((p) => p.id !== row.id);
  audit(ctx, "PRICE_DELETED", "PRC", "price", row.id);
  return undefined;
});

interface BulkInput {
  categoryId?: string;
  brandId?: string;
  mode: "PERCENT" | "AMOUNT";
  value: number;
  effectiveFrom?: string;
}

function bulkPreview(ctx: Ctx, input: BulkInput): BulkPricePreviewRow[] {
  const showCost = canSeeCost(ctx);
  return ctx.db.products
    .filter((p) => p.type !== "VARIANT_PARENT" && p.status !== "INACTIVE" && (!input.categoryId || p.categoryId === input.categoryId) && (!input.brandId || p.brandId === input.brandId))
    .map((p) => {
      const newPrice = round(input.mode === "PERCENT" ? p.retailPrice * (1 + input.value / 100) : p.retailPrice + input.value, 2);
      const minMargin = ctx.db.categories.find((c) => c.id === p.categoryId)?.minMarginPct ?? 0;
      const margin = newPrice > 0 ? ((newPrice - (p.avgCost ?? 0)) / newPrice) * 100 : 0;
      return {
        productId: p.id, sku: p.sku, productName: p.nameEn, currentPrice: p.retailPrice, newPrice,
        marginPct: showCost ? round(margin, 1) : null,
        belowMin: newPrice < 0 || (p.minSellingPrice !== null && newPrice < p.minSellingPrice) || margin < minMargin,
      };
    });
}

POST("/prices/bulk/preview", (ctx) => {
  requirePerm(ctx, "pricing.edit");
  return list(bulkPreview(ctx, ctx.body as BulkInput));
});

POST("/prices/bulk", (ctx) => {
  requirePerm(ctx, "pricing.edit");
  const input = ctx.body as BulkInput;
  const rows = bulkPreview(ctx, input);
  if (!rows.length) return validation("categoryId", "No products match this filter.");
  if (rows.some((r) => r.newPrice < 0)) return validation("value", "This change would make a price negative.");
  const retail = ctx.db.priceLists.find((l) => l.type === "RETAIL")?.id ?? null;
  const effectiveFrom = input.effectiveFrom ? new Date(input.effectiveFrom).toISOString() : ctx.now.toISOString();
  const scheduled = effectiveFrom > ctx.now.toISOString();
  for (const row of rows) {
    const product = getProduct(ctx.db, row.productId);
    if (scheduled) {
      addPrice(ctx, { productId: product.id, unitId: product.baseUnitId, priceListId: retail, branchId: null, customerGroupId: null, price: row.newPrice, effectiveFrom, effectiveTo: null });
    } else {
      ctx.db.priceHistory.unshift({ id: uid("ph"), productId: product.id, sku: product.sku, productName: product.nameEn, scope: "Standard retail (bulk)", oldPrice: product.retailPrice, newPrice: row.newPrice, effectiveFrom, userName: requireUser(ctx).fullName, at: ctx.now.toISOString(), approvedBy: null });
      product.retailPrice = row.newPrice;
    }
  }
  audit(ctx, "BULK_PRICE_UPDATE", "PRC", "price", "bulk", { after: { count: rows.length, ...input } });
  return { updated: rows.length, scheduled };
});

// Customer groups live with pricing because they drive price resolution.
crud<CustomerGroup>("/customer-groups", "customerGroups", {
  view: ["customers.view", "pos.sell", "pricing.view"],
  manage: ["customers.manage", "pricing.edit"],
  prefix: "grp",
  module: "CUS",
  validate: (ctx, input, existing) => assertUniqueCode(ctx.db.customerGroups, input.code, existing),
  beforeDelete: (ctx, row) => {
    if (ctx.db.customers.some((c) => c.groupId === row.id)) fail(409, "IN_USE", "Customers belong to this group.");
  },
});

// Promotions and coupons
GET("/promotions", (ctx) => {
  requirePerm(ctx, "promotions.view");
  const today = ctx.now.toISOString().slice(0, 10);
  return list(ctx.db.promotions.map((p) => (p.status === "ACTIVE" && p.endDate < today ? { ...p, status: "EXPIRED" as const } : p)));
});

function validatePromotion(ctx: Ctx, input: Partial<Promotion>) {
  if (input.startDate && input.endDate && input.endDate < input.startDate) validation("endDate", "End date must be on or after the start date.");
  if ((input.usageLimit ?? 0) < 0) validation("usageLimit", "Limit must not be negative.");
}

POST("/promotions", (ctx) => {
  requirePerm(ctx, "promotions.manage");
  const input = ctx.body as Partial<Promotion>;
  validatePromotion(ctx, input);
  assertUniqueCode(ctx.db.promotions, input.code, null);
  const row = { ...input, id: uid("pro"), usageCount: 0, status: "PENDING_APPROVAL", createdBy: requireUser(ctx).fullName, approvedBy: null } as Promotion;
  ctx.db.promotions.unshift(row);
  audit(ctx, "PROMOTION_CREATED", "PRM", "promotion", row.id, { after: row });
  return row;
});

PATCH("/promotions/:id", (ctx) => {
  requirePerm(ctx, "promotions.manage");
  const row = ctx.db.promotions.find((p) => p.id === ctx.params.id);
  if (!row) return notFound("Promotion");
  const input = ctx.body as Partial<Promotion>;
  validatePromotion(ctx, input);
  assertUniqueCode(ctx.db.promotions, input.code, row);
  Object.assign(row, input, { status: "PENDING_APPROVAL", approvedBy: null });
  audit(ctx, "PROMOTION_UPDATED", "PRM", "promotion", row.id, { after: row });
  return row;
});

POST("/promotions/:id/approve", (ctx) => {
  requirePerm(ctx, "promotions.manage");
  const user = requireUser(ctx);
  if (!ctx.permissions.has("settings.manage") && !ctx.permissions.has("purchasing.approve")) return fail(403, "FORBIDDEN", "You cannot approve promotions.");
  const row = ctx.db.promotions.find((p) => p.id === ctx.params.id);
  if (!row) return notFound("Promotion");
  if (row.status !== "PENDING_APPROVAL") return fail(409, "INVALID_STATE_TRANSITION", "Only a pending promotion can be approved.");
  if (row.createdBy === user.fullName && !ctx.db.settings.reducedSodMode) return fail(403, "SOD_VIOLATION", "You cannot approve your own promotion.");
  row.status = "ACTIVE";
  row.approvedBy = user.fullName;
  audit(ctx, "PROMOTION_APPROVED", "PRM", "promotion", row.id);
  return row;
});

POST("/promotions/:id/disable", (ctx) => {
  requirePerm(ctx, "promotions.manage");
  const row = ctx.db.promotions.find((p) => p.id === ctx.params.id);
  if (!row) return notFound("Promotion");
  row.status = "DISABLED";
  audit(ctx, "PROMOTION_DISABLED", "PRM", "promotion", row.id);
  return row;
});

DELETE("/promotions/:id", (ctx) => {
  requirePerm(ctx, "promotions.manage");
  const row = ctx.db.promotions.find((p) => p.id === ctx.params.id);
  if (!row) return notFound("Promotion");
  if (row.usageCount > 0) return fail(409, "IN_USE", "A promotion that has been used cannot be deleted. Disable it instead.");
  ctx.db.promotions = ctx.db.promotions.filter((p) => p.id !== row.id);
  return undefined;
});

crud<Coupon>("/coupons", "coupons", {
  view: ["promotions.view", "pos.sell"],
  manage: ["promotions.manage"],
  prefix: "cpn",
  module: "PRM",
  validate: (ctx, input, existing) => assertUniqueCode(ctx.db.coupons, input.code, existing, "Coupon code"),
  beforeDelete: (_ctx, row) => {
    if (row.usageCount > 0) fail(409, "IN_USE", "A redeemed coupon cannot be deleted. Deactivate it instead.");
  },
});

export { assertNotSelfApproval };
