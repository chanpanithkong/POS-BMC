import type { Branch, Company, DocumentSequence, ExchangeRate, PaymentMethodConfig, ReceiptTemplate, StockLocation, SystemSettings, TaxCode, Terminal, Warehouse } from "@/types";
import { audit, fail, list, notFound, positive, requirePerm, requireUser, uid, validation, type Ctx } from "../core";
import { onHandInWarehouse } from "../domain/inventory";
import { GET, PATCH, POST, assertUniqueCode, crud } from "../registry";

const VIEW = ["settings.view", "settings.manage", "dashboard.view"] as const;

GET("/companies/current", (ctx) => {
  requireUser(ctx);
  return ctx.db.company;
});
PATCH("/companies/current", (ctx) => {
  requirePerm(ctx, "settings.manage");
  const before = { ...ctx.db.company };
  Object.assign(ctx.db.company, ctx.body as Partial<Company>);
  audit(ctx, "SETTINGS_CHANGED", "ORG", "company", ctx.db.company.id, { before, after: ctx.db.company });
  return ctx.db.company;
});

GET("/settings", (ctx) => {
  requireUser(ctx);
  return ctx.db.settings;
});
PATCH("/settings", (ctx) => {
  requirePerm(ctx, "settings.manage");
  const before = { ...ctx.db.settings };
  const input = ctx.body as Partial<SystemSettings>;
  if (input.costingMethod && input.costingMethod !== before.costingMethod && ctx.db.movements.length) {
    return fail(409, "METHOD_LOCKED", "Costing method is locked after the first posting.");
  }
  Object.assign(ctx.db.settings, input);
  audit(ctx, "SETTINGS_CHANGED", "ORG", "settings", "system", { before, after: ctx.db.settings });
  return ctx.db.settings;
});

crud<Branch>("/branches", "branches", {
  view: [...VIEW, "pos.sell", "pos.hold", "inventory.view", "sales.view"],
  manage: ["settings.manage"],
  prefix: "br",
  module: "ORG",
  validate: (ctx, input, existing) => assertUniqueCode(ctx.db.branches, input.code, existing),
  beforeDelete: (ctx, row) => {
    if (ctx.db.warehouses.some((w) => w.branchId === row.id) || ctx.db.sales.some((s) => s.branchId === row.id)) {
      fail(409, "IN_USE", "This branch has warehouses or sales. Deactivate it instead.");
    }
  },
});

function hasStock(ctx: Ctx, warehouseId: string) {
  return ctx.db.products.some((p) => onHandInWarehouse(ctx.db, warehouseId, p.id) !== 0);
}

crud<Warehouse>("/warehouses", "warehouses", {
  view: [...VIEW, "inventory.view", "purchasing.view"],
  manage: ["settings.manage"],
  prefix: "wh",
  module: "ORG",
  validate: (ctx, input, existing) => {
    assertUniqueCode(ctx.db.warehouses, input.code, existing);
    if (existing && input.status === "INACTIVE" && hasStock(ctx, existing.id)) {
      fail(409, "WAREHOUSE_HAS_STOCK", "Transfer or write off all stock before deactivating this warehouse.");
    }
  },
  beforeDelete: (ctx, row) => {
    if (hasStock(ctx, row.id) || ctx.db.movements.some((m) => m.warehouseId === row.id)) fail(409, "IN_USE", "This warehouse has stock history. Deactivate it instead.");
    ctx.db.locations = ctx.db.locations.filter((l) => l.warehouseId !== row.id);
  },
});

crud<StockLocation>("/locations", "locations", {
  view: [...VIEW, "inventory.view", "purchasing.view", "pos.sell"],
  manage: ["settings.manage"],
  prefix: "loc",
  module: "ORG",
  validate: (ctx, input, existing) => {
    if (input.code !== undefined && ctx.db.locations.some((l) => l.code === input.code && l.warehouseId === (input.warehouseId ?? existing?.warehouseId) && l.id !== existing?.id)) {
      validation("code", "Location code already exists in this warehouse.");
    }
  },
  beforeDelete: (ctx, row) => {
    if (ctx.db.balances.some((b) => b.locationId === row.id && b.onHand !== 0)) fail(409, "IN_USE", "This location holds stock.");
    if (ctx.db.terminals.some((t) => t.defaultLocationId === row.id)) fail(409, "IN_USE", "A terminal sells from this location.");
  },
});

crud<Terminal>("/terminals", "terminals", {
  view: [...VIEW, "pos.sell", "pos.hold", "sales.view"],
  manage: ["settings.manage"],
  prefix: "term",
  module: "ORG",
  validate: (ctx, input, existing) => {
    assertUniqueCode(ctx.db.terminals, input.code, existing);
    const locationId = input.defaultLocationId ?? existing?.defaultLocationId;
    const branchId = input.branchId ?? existing?.branchId;
    const location = ctx.db.locations.find((l) => l.id === locationId);
    const warehouse = ctx.db.warehouses.find((w) => w.id === location?.warehouseId);
    if (!location || location.type !== "SELLABLE" || warehouse?.branchId !== branchId) {
      validation("defaultLocationId", "Select a sellable location in this terminal's branch.");
    }
  },
  beforeDelete: (ctx, row) => {
    if (ctx.db.sales.some((s) => s.terminalId === row.id)) fail(409, "IN_USE", "This terminal has sales history. Deactivate it instead.");
  },
});

crud<TaxCode>("/tax-codes", "taxCodes", {
  view: [...VIEW, "products.view"],
  manage: ["settings.manage"],
  prefix: "tax",
  module: "ORG",
  validate: (ctx, input, existing) => {
    assertUniqueCode(ctx.db.taxCodes, input.code, existing);
    if (input.rate !== undefined && (input.rate < 0 || input.rate > 100)) validation("rate", "Rate must be between 0 and 100.");
  },
  beforeDelete: (ctx, row) => {
    if (ctx.db.products.some((p) => p.taxCodeId === row.id)) fail(409, "IN_USE", "Products use this tax code.");
  },
});

crud<PaymentMethodConfig>("/payment-methods", "paymentMethods", {
  view: [...VIEW, "pos.sell", "sales.view"],
  manage: ["settings.manage"],
  prefix: "pm",
  module: "ORG",
  beforeDelete: () => fail(409, "IN_USE", "Payment methods cannot be deleted. Deactivate them instead."),
});

GET("/currencies/rates", (ctx) => {
  requireUser(ctx);
  return list([...ctx.db.exchangeRates].sort((a, b) => b.effectiveAt.localeCompare(a.effectiveAt)));
});
POST("/currencies/rates", (ctx) => {
  requirePerm(ctx, "settings.manage");
  const user = requireUser(ctx);
  const { rate } = ctx.body as { rate: number };
  const row: ExchangeRate = { id: uid("fx"), from: "USD", to: "KHR", rate: positive(rate, "rate", "Rate"), effectiveAt: ctx.now.toISOString(), createdBy: user.fullName };
  ctx.db.exchangeRates.unshift(row);
  audit(ctx, "EXCHANGE_RATE_SET", "ORG", "exchange_rate", row.id, { after: row });
  return row;
});

GET("/document-sequences", (ctx) => {
  requirePerm(ctx, ...VIEW);
  return list(ctx.db.sequences);
});
PATCH("/document-sequences/:id", (ctx) => {
  requirePerm(ctx, "settings.manage");
  const row = ctx.db.sequences.find((s) => s.id === ctx.params.id);
  if (!row) return notFound("Sequence");
  const input = ctx.body as Partial<DocumentSequence>;
  if (input.nextValue !== undefined && input.nextValue < row.nextValue) return validation("nextValue", "Document numbers are never reused, so the next value cannot go backwards.");
  Object.assign(row, input);
  audit(ctx, "NUMBERING_CHANGED", "ORG", "sequence", row.id, { after: row });
  return row;
});

crud<ReceiptTemplate>("/receipt-templates", "receiptTemplates", {
  view: [...VIEW, "pos.sell", "sales.view"],
  manage: ["settings.manage"],
  prefix: "tpl",
  module: "DOC",
  beforeDelete: (ctx) => {
    if (ctx.db.receiptTemplates.length <= 1) fail(409, "IN_USE", "At least one receipt template is required.");
  },
});
