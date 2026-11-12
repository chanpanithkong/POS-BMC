import type {
  AdjustmentLine, AdjustmentReason, ExpiringBatchRow, MovementType, Product, ReorderSuggestion, StockAdjustment, StockCount, StockCountLine, StockMovement, StockOverviewRow,
  StockTransfer, TimelineEvent,
} from "@/types";
import {
  assertNotSelfApproval, audit, badState, branchFilter, can, canSeeCost, fail, list, nextDocNo, notFound, notify, requirePerm, requireUser, round, uid, validation, type Ctx,
} from "../core";
import {
  availableAt, evaluateStockAlerts, getLocation, getProduct, getWarehouse, inTransitLocation, locationByType, onHandInWarehouse, onOrderBase, postMovement, reconcileBalances,
  availableInWarehouse, sellableLocation, settingsFor,
} from "../domain/inventory";
import { GET, PATCH, POST } from "../registry";

const unitCode = (ctx: Ctx, product: Product) => ctx.db.units.find((u) => u.id === product.baseUnitId)?.code ?? "";
const event = (ctx: Ctx, label: string, note?: string): TimelineEvent => ({ at: ctx.now.toISOString(), label, by: requireUser(ctx).fullName, note });

/** Blocks posting into a warehouse with a frozen stocktake (FR-ADJ-005). */
export function assertNotFrozen(ctx: Ctx, warehouseId: string) {
  if (ctx.db.counts.some((c) => c.warehouseId === warehouseId && c.freeze && ["OPEN", "COUNTING", "REVIEW", "APPROVED"].includes(c.status))) {
    fail(409, "LOCATION_FROZEN", "This warehouse is frozen for a stocktake.");
  }
}

GET("/inventory/balances", (ctx) => {
  requirePerm(ctx, "inventory.view");
  const { db, query } = ctx;
  const inBranch = branchFilter(ctx);
  const warehouses = db.warehouses.filter((w) => inBranch(w.branchId) && (!query.warehouseId || w.id === query.warehouseId));
  const showValue = canSeeCost(ctx);
  const warehouseIds = new Set(warehouses.map((w) => w.id));
  const locations = db.locations.filter((l) => warehouseIds.has(l.warehouseId) && (!query.locationType || l.type === query.locationType) && l.type !== "IN_TRANSIT");
  const transit = inTransitLocation(db);
  const rows: StockOverviewRow[] = db.products
    .filter((p) => p.type !== "SERVICE" && p.type !== "VARIANT_PARENT")
    .map((product) => {
      const byLocation = locations.flatMap((location) => {
        const b = db.balances.find((x) => x.locationId === location.id && x.productId === product.id);
        if (!b || (b.onHand === 0 && b.reserved === 0)) return [];
        const warehouse = getWarehouse(db, location.warehouseId);
        return [{ locationId: location.id, locationName: location.name, locationType: location.type, warehouseId: warehouse.id, warehouseName: warehouse.name, branchId: warehouse.branchId, onHand: b.onHand, reserved: b.reserved }];
      });
      const onHand = round(byLocation.reduce((s, l) => s + l.onHand, 0), 4);
      const reserved = round(byLocation.reduce((s, l) => s + l.reserved, 0), 4);
      const available = round(byLocation.filter((l) => db.locations.find((x) => x.id === l.locationId)?.availableToSell).reduce((s, l) => s + l.onHand - l.reserved, 0), 4);
      const single = warehouses.length === 1 ? settingsFor(product, warehouses[0].id) : product.stockSettings;
      const reorderLevel = warehouses.length === 1 ? single.reorderLevel : product.stockSettings.reorderLevel * warehouses.filter((w) => w.branchId).length;
      const maxLevel = warehouses.length === 1 ? single.maxLevel : product.stockSettings.maxLevel * warehouses.filter((w) => w.branchId).length;
      const status: StockOverviewRow["status"] = onHand < 0 ? "NEGATIVE" : available <= 0 ? "OUT" : available <= reorderLevel ? "LOW" : maxLevel > 0 && onHand > maxLevel ? "OVER" : "IN_STOCK";
      const row: StockOverviewRow = {
        productId: product.id, sku: product.sku, productName: product.nameEn, categoryId: product.categoryId,
        categoryName: db.categories.find((c) => c.id === product.categoryId)?.nameEn ?? "", unitCode: unitCode(ctx, product),
        onHand, reserved, available, onOrder: onOrderBase(db, product.id, typeof query.warehouseId === "string" ? query.warehouseId : undefined),
        inTransit: db.balances.find((b) => b.locationId === transit.id && b.productId === product.id)?.onHand ?? 0,
        reorderLevel, maxLevel, status, byLocation,
      };
      if (showValue) {
        row.avgCost = product.avgCost;
        row.value = round(onHand * (product.avgCost ?? 0), 2);
      }
      return row;
    });
  return list(rows);
});

GET("/inventory/availability", (ctx) => {
  requirePerm(ctx, "inventory.view", "pos.sell");
  const { locationId, productId } = ctx.query as { locationId: string; productId: string };
  return { productId, locationId, available: availableAt(ctx.db, locationId, productId) };
});

function movementEffect(m: StockMovement) {
  if (m.fromLocationId && m.toLocationId) return 0;
  return m.toLocationId ? m.quantityBase : -m.quantityBase;
}

GET("/inventory/movements", (ctx) => {
  requirePerm(ctx, "inventory.view");
  const inBranch = branchFilter(ctx);
  const running = new Map<string, number>();
  const rows = ctx.db.movements.map((m) => {
    const next = round((running.get(m.productId) ?? 0) + movementEffect(m), 4);
    running.set(m.productId, next);
    return { ...m, runningBalance: next };
  });
  return list(rows.filter((m) => inBranch(m.branchId) && (!ctx.query.productId || m.productId === ctx.query.productId)).reverse().slice(0, 5000));
});

POST("/inventory/movements/:id/reverse", (ctx) => {
  requirePerm(ctx, "inventory.reverse");
  const user = requireUser(ctx);
  const id = Number(ctx.params.id);
  const original = ctx.db.movements.find((m) => m.id === id);
  if (!original) return notFound("Movement");
  const { reason } = ctx.body as { reason: string };
  if (!reason?.trim()) return validation("reason", "Reversal requires a reason");
  if (original.reversedByMovementId) return badState("This movement has already been reversed.");
  if (original.type === "REVERSAL") return badState("A reversal cannot itself be reversed.");
  if (original.userId === user.id && !ctx.db.settings.reducedSodMode && original.type.startsWith("ADJUSTMENT")) return fail(403, "SOD_VIOLATION", "You cannot reverse your own adjustment.");
  const reversal = postMovement(ctx, {
    type: "REVERSAL", productId: original.productId, fromLocationId: original.toLocationId, toLocationId: original.fromLocationId,
    quantityBase: original.quantityBase, unitCost: original.unitCost ?? 0, sourceType: "REVERSAL", sourceId: String(original.id), sourceNo: `REV-${original.id}`,
    reasonCode: reason, reversesMovementId: original.id, approvedBy: user.fullName,
  });
  original.reversedByMovementId = reversal?.id ?? null;
  audit(ctx, "MOVEMENT_REVERSED", "INV", "movement", String(original.id), { after: { reason, reversalId: reversal?.id } });
  return reversal;
});

POST("/inventory/relocations", (ctx) => {
  requirePerm(ctx, "inventory.transfer");
  const { productId, fromLocationId, toLocationId, quantity, reason } = ctx.body as { productId: string; fromLocationId: string; toLocationId: string; quantity: number; reason?: string };
  if (getLocation(ctx.db, fromLocationId).warehouseId !== getLocation(ctx.db, toLocationId).warehouseId) return validation("toLocationId", "Relocation must stay within one warehouse. Use a transfer instead.");
  if (fromLocationId === toLocationId) return validation("toLocationId", "Choose a different location.");
  const product = getProduct(ctx.db, productId);
  assertNotFrozen(ctx, getLocation(ctx.db, fromLocationId).warehouseId);
  return postMovement(ctx, { type: "RELOCATION", productId, fromLocationId, toLocationId, quantityBase: quantity, unitCost: product.avgCost ?? 0, sourceType: "RELOCATION", sourceId: uid("rel"), sourceNo: "RELOCATION", reasonCode: reason ?? null });
});

POST("/inventory/reconciliation", (ctx) => {
  requirePerm(ctx, "inventory.view");
  const result = reconcileBalances(ctx.db);
  audit(ctx, "RECONCILIATION_RUN", "INV", "balances", "all", { after: { checked: result.balancesChecked, differences: result.differences.length }, flagged: result.differences.length > 0 });
  return { checkedAt: ctx.now.toISOString(), ...result };
});

GET("/inventory/batches", (ctx) => {
  requirePerm(ctx, "inventory.view");
  const { db } = ctx;
  const inBranch = branchFilter(ctx);
  const today = new Date(ctx.now.toISOString().slice(0, 10)).getTime();
  const rows: ExpiringBatchRow[] = db.batches.filter((b) => b.quantity > 0).flatMap((b) => {
    const location = getLocation(db, b.locationId);
    const warehouse = getWarehouse(db, location.warehouseId);
    if (!inBranch(warehouse.branchId)) return [];
    const product = getProduct(db, b.productId);
    return [{ ...b, sku: product.sku, productName: product.nameEn, locationName: location.name, warehouseName: warehouse.name, daysToExpiry: Math.round((new Date(b.expiryDate).getTime() - today) / 86_400_000), ...(canSeeCost(ctx) ? { value: round(b.quantity * (product.avgCost ?? 0), 2) } : {}) }];
  });
  return list(rows.sort((a, b) => a.daysToExpiry - b.daysToExpiry));
});

GET("/inventory/reorder-suggestions", (ctx) => {
  requirePerm(ctx, "purchasing.view", "alerts.view", "inventory.view");
  const { db } = ctx;
  const inBranch = branchFilter(ctx);
  const rows: ReorderSuggestion[] = [];
  for (const warehouse of db.warehouses.filter((w) => w.branchId && w.status === "ACTIVE" && inBranch(w.branchId))) {
    for (const product of db.products.filter((p) => p.status === "ACTIVE" && p.type !== "SERVICE" && p.type !== "VARIANT_PARENT")) {
      const settings = settingsFor(product, warehouse.id);
      const available = availableInWarehouse(db, warehouse.id, product.id);
      if (available > settings.reorderLevel) continue;
      const onOrder = onOrderBase(db, product.id, warehouse.id);
      const needed = Math.max(settings.maxLevel - available - onOrder, onOrder > 0 ? 0 : settings.reorderQty);
      if (needed <= 0) continue;
      const link = product.suppliers.find((s) => s.preferred) ?? product.suppliers[0];
      const purchaseUnit = product.conversions.find((c) => c.isPurchaseDefault);
      const factor = purchaseUnit?.factor ?? 1;
      const qty = Math.ceil(needed / factor);
      rows.push({
        productId: product.id, sku: product.sku, productName: product.nameEn, warehouseId: warehouse.id, warehouseName: warehouse.name, available, onOrder, maxLevel: settings.maxLevel,
        suggestedBase: qty * factor, purchaseUnitId: purchaseUnit?.unitId ?? product.baseUnitId, purchaseUnitCode: db.units.find((u) => u.id === (purchaseUnit?.unitId ?? product.baseUnitId))?.code ?? "",
        purchaseFactor: factor, suggestedQty: qty, supplierId: link?.supplierId ?? null, supplierName: db.suppliers.find((s) => s.id === link?.supplierId)?.nameEn ?? "No supplier linked",
        ...(canSeeCost(ctx) ? { cost: link?.cost ?? product.lastPurchaseCost } : {}), leadTimeDays: link?.leadTimeDays ?? 0,
      });
    }
  }
  return list(rows);
});

// Adjustments (Draft -> Submitted -> Approved -> Posted, BR-INV-004)
const getAdj = (ctx: Ctx, id: string): StockAdjustment => ctx.db.adjustments.find((a) => a.id === id) ?? (notFound("Adjustment") as never);

function buildAdjLines(ctx: Ctx, input: { productId: string; locationId: string; quantity: number; reason: AdjustmentReason; notes?: string }[]): AdjustmentLine[] {
  if (!input?.length) validation("lines", "Add at least one line.");
  return input.map((l) => {
    if (!l.reason) validation("lines", "Reason required");
    if (!l.quantity) validation("lines", "Quantity must not be zero.");
    const product = getProduct(ctx.db, l.productId);
    if (!product.allowFraction && !Number.isInteger(l.quantity)) fail(422, "INVALID_QUANTITY_FOR_UNIT", `${product.nameEn} must be adjusted in whole units.`);
    return {
      id: uid("adl"), productId: product.id, sku: product.sku, productName: product.nameEn, locationId: l.locationId, locationName: getLocation(ctx.db, l.locationId).name,
      quantity: l.quantity, unitCode: unitCode(ctx, product), reason: l.reason, notes: l.notes ?? "", unitCost: product.avgCost, valueImpact: round(l.quantity * (product.avgCost ?? 0), 2),
    };
  });
}

GET("/inventory/adjustments", (ctx) => {
  requirePerm(ctx, "inventory.view");
  const inBranch = branchFilter(ctx);
  return list(ctx.db.adjustments.filter((a) => inBranch(a.branchId)));
});

POST("/inventory/adjustments", (ctx) => {
  requirePerm(ctx, "inventory.adjust");
  const user = requireUser(ctx);
  const input = ctx.body as { warehouseId: string; notes?: string; attachment?: string; lines: Parameters<typeof buildAdjLines>[1] };
  const warehouse = getWarehouse(ctx.db, input.warehouseId);
  const lines = buildAdjLines(ctx, input.lines);
  const adjustment: StockAdjustment = {
    id: uid("adj"), adjustmentNo: nextDocNo(ctx, "ADJUSTMENT"), warehouseId: warehouse.id, warehouseName: warehouse.name, branchId: warehouse.branchId, status: "DRAFT", lines,
    notes: input.notes ?? "", attachment: input.attachment ?? null, totalValue: round(lines.reduce((s, l) => s + Math.abs(l.valueImpact ?? 0), 0), 2), requiresApproval: false,
    createdBy: user.fullName, createdById: user.id, approvedBy: null, createdAt: ctx.now.toISOString(), postedAt: null, timeline: [event(ctx, "Created")],
  };
  ctx.db.adjustments.unshift(adjustment);
  return adjustment;
});

PATCH("/inventory/adjustments/:id", (ctx) => {
  requirePerm(ctx, "inventory.adjust");
  const adjustment = getAdj(ctx, ctx.params.id);
  if (adjustment.status !== "DRAFT" && adjustment.status !== "REJECTED") return badState("Only a draft adjustment can be edited.");
  const input = ctx.body as { notes?: string; lines: Parameters<typeof buildAdjLines>[1] };
  adjustment.lines = buildAdjLines(ctx, input.lines);
  adjustment.notes = input.notes ?? adjustment.notes;
  adjustment.status = "DRAFT";
  adjustment.totalValue = round(adjustment.lines.reduce((s, l) => s + Math.abs(l.valueImpact ?? 0), 0), 2);
  return adjustment;
});

POST("/inventory/adjustments/:id/submit", (ctx) => {
  requirePerm(ctx, "inventory.adjust");
  const adjustment = getAdj(ctx, ctx.params.id);
  if (adjustment.status !== "DRAFT") return badState("Only a draft adjustment can be submitted.");
  adjustment.status = "SUBMITTED";
  adjustment.requiresApproval = (adjustment.totalValue ?? 0) > ctx.limits.adjustmentValue || !can(ctx, "inventory.adjust.approve");
  adjustment.timeline.push(event(ctx, "Submitted"));
  if (!adjustment.requiresApproval) {
    adjustment.status = "APPROVED";
    adjustment.approvedBy = "Auto-approved within limit";
    adjustment.timeline.push(event(ctx, "Auto-approved within limit"));
  } else {
    notify(ctx, "APPROVAL", "Adjustment awaiting approval", `${adjustment.adjustmentNo} value ${adjustment.totalValue?.toFixed(2)} USD`, { link: "/inventory/adjustments", permission: "inventory.adjust.approve", branchId: adjustment.branchId });
  }
  return adjustment;
});

POST("/inventory/adjustments/:id/approve", (ctx) => {
  requirePerm(ctx, "inventory.adjust.approve");
  const adjustment = getAdj(ctx, ctx.params.id);
  if (adjustment.status !== "SUBMITTED") return badState("Only a submitted adjustment can be approved.");
  const selfApproved = assertNotSelfApproval(ctx, adjustment.createdById, "adjustment");
  if ((adjustment.totalValue ?? 0) > ctx.limits.adjustmentValue) return fail(403, "LIMIT_EXCEEDED", "This adjustment is above your approval limit.");
  adjustment.status = "APPROVED";
  adjustment.approvedBy = requireUser(ctx).fullName;
  adjustment.timeline.push(event(ctx, "Approved"));
  audit(ctx, "ADJUSTMENT_APPROVED", "ADJ", "adjustment", adjustment.id, { branchId: adjustment.branchId, flagged: selfApproved });
  return adjustment;
});

POST("/inventory/adjustments/:id/reject", (ctx) => {
  requirePerm(ctx, "inventory.adjust.approve");
  const adjustment = getAdj(ctx, ctx.params.id);
  if (adjustment.status !== "SUBMITTED") return badState("Only a submitted adjustment can be rejected.");
  const { reason } = ctx.body as { reason: string };
  if (!reason?.trim()) return validation("reason", "A rejection reason is required.");
  adjustment.status = "REJECTED";
  adjustment.timeline.push(event(ctx, "Rejected", reason));
  return adjustment;
});

const OUT_TYPE: Partial<Record<AdjustmentReason, MovementType>> = { DAMAGED: "DAMAGE", EXPIRED: "EXPIRY", LOST: "LOSS", WRITE_OFF: "WRITE_OFF" };

POST("/inventory/adjustments/:id/post", (ctx) => {
  requirePerm(ctx, "inventory.adjust.approve", "inventory.adjust");
  const adjustment = getAdj(ctx, ctx.params.id);
  if (adjustment.status === "POSTED") return fail(409, "ALREADY_POSTED", "This adjustment has already been posted.");
  if (adjustment.status !== "APPROVED") return badState("Only an approved adjustment can be posted.");
  assertNotFrozen(ctx, adjustment.warehouseId);
  for (const line of adjustment.lines) {
    const product = getProduct(ctx.db, line.productId);
    const cost = product.avgCost ?? 0;
    const common = { productId: line.productId, quantityBase: Math.abs(line.quantity), unitCost: cost, sourceType: "ADJUSTMENT", sourceId: adjustment.id, sourceNo: adjustment.adjustmentNo, reasonCode: line.reason, approvedBy: adjustment.approvedBy };
    if (line.quantity > 0) {
      postMovement(ctx, { ...common, type: "ADJUSTMENT_IN", toLocationId: line.locationId });
    } else {
      const type = OUT_TYPE[line.reason] ?? "ADJUSTMENT_OUT";
      const destination = type === "DAMAGE" ? locationByType(ctx.db, adjustment.warehouseId, "DAMAGED") : type === "EXPIRY" ? locationByType(ctx.db, adjustment.warehouseId, "EXPIRED") : undefined;
      postMovement(ctx, { ...common, type, fromLocationId: line.locationId, toLocationId: destination && destination.id !== line.locationId ? destination.id : null });
    }
  }
  adjustment.status = "POSTED";
  adjustment.postedAt = ctx.now.toISOString();
  adjustment.timeline.push(event(ctx, "Posted"));
  audit(ctx, "ADJUSTMENT_POSTED", "ADJ", "adjustment", adjustment.id, { after: { value: adjustment.totalValue }, branchId: adjustment.branchId });
  if ((adjustment.totalValue ?? 0) >= ctx.db.settings.adjustmentAlertValue) {
    const line = adjustment.lines[0];
    ctx.db.alerts.unshift({ id: uid("alr"), type: "UNUSUAL_ADJUSTMENT", productId: line.productId, sku: line.sku, productName: line.productName, warehouseId: adjustment.warehouseId, warehouseName: adjustment.warehouseName, branchId: adjustment.branchId, message: `${adjustment.adjustmentNo} posted with value ${adjustment.totalValue?.toFixed(2)} USD, above the alert threshold.`, status: "OPEN", assignedTo: null, snoozedUntil: null, note: null, createdAt: ctx.now.toISOString(), updatedAt: ctx.now.toISOString() });
  }
  return adjustment;
});

// Transfers (BR-TRF-001, BR-TRF-002)
const getTrf = (ctx: Ctx, id: string): StockTransfer => ctx.db.transfers.find((t) => t.id === id) ?? (notFound("Transfer") as never);

GET("/inventory/transfers", (ctx) => {
  requirePerm(ctx, "inventory.view");
  const inBranch = branchFilter(ctx);
  const visible = (id: string) => inBranch(getWarehouse(ctx.db, id).branchId);
  return list(ctx.db.transfers.filter((t) => visible(t.sourceWarehouseId) || visible(t.destinationWarehouseId)).map((t) => (canSeeCost(ctx) ? t : { ...t, value: undefined })));
});

POST("/inventory/transfers", (ctx) => {
  requirePerm(ctx, "inventory.transfer");
  const user = requireUser(ctx);
  const input = ctx.body as { sourceWarehouseId: string; destinationWarehouseId: string; reason: string; lines: { productId: string; quantity: number }[] };
  if (input.sourceWarehouseId === input.destinationWarehouseId) return validation("destinationWarehouseId", "Source and destination must be different.");
  if (!input.lines?.length) return validation("lines", "Add at least one line.");
  if (!input.reason?.trim()) return validation("reason", "A reason is required.");
  const source = getWarehouse(ctx.db, input.sourceWarehouseId);
  const destination = getWarehouse(ctx.db, input.destinationWarehouseId);
  const lines = input.lines.map((l) => {
    const product = getProduct(ctx.db, l.productId);
    if (!(l.quantity > 0)) validation("lines", "Quantity must be greater than zero.");
    return { id: uid("trl"), productId: product.id, sku: product.sku, productName: product.nameEn, unitCode: unitCode(ctx, product), quantityRequested: l.quantity, quantityDispatched: 0, quantityReceived: 0, quantityShort: 0, quantityDamaged: 0, quantityExcess: 0 };
  });
  const transfer: StockTransfer = {
    id: uid("trf"), transferNo: nextDocNo(ctx, "TRANSFER"), sourceWarehouseId: source.id, sourceWarehouseName: source.name, destinationWarehouseId: destination.id, destinationWarehouseName: destination.name,
    status: "REQUESTED", reason: input.reason.trim(), lines, value: round(lines.reduce((s, l) => s + l.quantityRequested * (getProduct(ctx.db, l.productId).avgCost ?? 0), 0), 2),
    createdBy: user.fullName, createdById: user.id, approvedBy: null, createdAt: ctx.now.toISOString(), dispatchedAt: null, receivedAt: null, timeline: [event(ctx, "Requested")],
  };
  ctx.db.transfers.unshift(transfer);
  audit(ctx, "TRANSFER_REQUESTED", "TRF", "transfer", transfer.id);
  notify(ctx, "TRANSFER", "Transfer requested", `${transfer.transferNo}: ${source.name} to ${destination.name}`, { link: "/inventory/transfers", permission: "inventory.transfer.approve" });
  return transfer;
});

POST("/inventory/transfers/:id/approve", (ctx) => {
  requirePerm(ctx, "inventory.transfer.approve");
  const transfer = getTrf(ctx, ctx.params.id);
  if (transfer.status !== "REQUESTED") return badState("Only a requested transfer can be approved.");
  if ((transfer.value ?? 0) > ctx.db.settings.transferApprovalValue) assertNotSelfApproval(ctx, transfer.createdById, "transfer");
  transfer.status = "APPROVED";
  transfer.approvedBy = requireUser(ctx).fullName;
  transfer.timeline.push(event(ctx, "Approved"));
  audit(ctx, "TRANSFER_APPROVED", "TRF", "transfer", transfer.id);
  return transfer;
});

POST("/inventory/transfers/:id/dispatch", (ctx) => {
  requirePerm(ctx, "inventory.transfer");
  const transfer = getTrf(ctx, ctx.params.id);
  if (transfer.status === "DISPATCHED") return fail(409, "ALREADY_POSTED", "This transfer has already been dispatched.");
  if (transfer.status !== "APPROVED") return badState("Only an approved transfer can be dispatched.");
  assertNotFrozen(ctx, transfer.sourceWarehouseId);
  const { lines } = ctx.body as { lines: { lineId: string; quantity: number }[] };
  const source = sellableLocation(ctx.db, transfer.sourceWarehouseId);
  const transit = inTransitLocation(ctx.db);
  for (const entry of lines) {
    const line = transfer.lines.find((l) => l.id === entry.lineId);
    if (!line) return notFound("Transfer line");
    if (entry.quantity < 0) return validation("lines", "Quantity must not be negative.");
    if (entry.quantity > availableAt(ctx.db, source.id, line.productId)) return fail(422, "INSUFFICIENT_STOCK", `Dispatch quantity exceeds available stock for ${line.productName}.`);
    line.quantityDispatched = entry.quantity;
    if (entry.quantity > 0) {
      const product = getProduct(ctx.db, line.productId);
      postMovement(ctx, { type: "TRANSFER_OUT", productId: line.productId, fromLocationId: source.id, toLocationId: transit.id, quantityBase: entry.quantity, unitCost: product.avgCost ?? 0, sourceType: "TRANSFER", sourceId: transfer.id, sourceNo: transfer.transferNo });
    }
  }
  if (!transfer.lines.some((l) => l.quantityDispatched > 0)) return validation("lines", "Dispatch at least one item.");
  transfer.status = "DISPATCHED";
  transfer.dispatchedAt = ctx.now.toISOString();
  transfer.timeline.push(event(ctx, "Dispatched"));
  audit(ctx, "TRANSFER_DISPATCHED", "TRF", "transfer", transfer.id);
  notify(ctx, "TRANSFER", "Transfer in transit", `${transfer.transferNo} is on its way to ${transfer.destinationWarehouseName}.`, { link: "/inventory/transfers", permission: "inventory.transfer" });
  return transfer;
});

POST("/inventory/transfers/:id/receive", (ctx) => {
  requirePerm(ctx, "inventory.transfer");
  const transfer = getTrf(ctx, ctx.params.id);
  if (transfer.status !== "DISPATCHED" && transfer.status !== "PARTIALLY_RECEIVED") return badState("This transfer is not in transit.");
  const { lines } = ctx.body as { lines: { lineId: string; received: number; short: number; damaged: number; excess: number }[] };
  const transit = inTransitLocation(ctx.db);
  const destination = sellableLocation(ctx.db, transfer.destinationWarehouseId);
  const damaged = locationByType(ctx.db, transfer.destinationWarehouseId, "DAMAGED") ?? destination;
  assertNotFrozen(ctx, transfer.destinationWarehouseId);
  for (const entry of lines) {
    const line = transfer.lines.find((l) => l.id === entry.lineId);
    if (!line) return notFound("Transfer line");
    const outstanding = round(line.quantityDispatched - line.quantityReceived - line.quantityShort - line.quantityDamaged, 4);
    if (entry.received + entry.short + entry.damaged > outstanding + 1e-9) return validation("lines", "Received quantity exceeds dispatched — record as excess");
    const product = getProduct(ctx.db, line.productId);
    const cost = product.avgCost ?? 0;
    const common = { productId: line.productId, unitCost: cost, sourceType: "TRANSFER", sourceId: transfer.id, sourceNo: transfer.transferNo };
    if (entry.received > 0) postMovement(ctx, { ...common, type: "TRANSFER_RECEIVE", fromLocationId: transit.id, toLocationId: destination.id, quantityBase: entry.received });
    if (entry.damaged > 0) postMovement(ctx, { ...common, type: "TRANSFER_RECEIVE", fromLocationId: transit.id, toLocationId: damaged.id, quantityBase: entry.damaged, reasonCode: "Damaged in transit" });
    line.quantityReceived = round(line.quantityReceived + entry.received, 4);
    line.quantityShort = round(line.quantityShort + entry.short, 4);
    line.quantityDamaged = round(line.quantityDamaged + entry.damaged, 4);
    line.quantityExcess = round(line.quantityExcess + entry.excess, 4);
  }
  const complete = transfer.lines.every((l) => round(l.quantityReceived + l.quantityShort + l.quantityDamaged, 4) >= l.quantityDispatched);
  transfer.status = complete ? "RECEIVED" : "PARTIALLY_RECEIVED";
  if (complete) transfer.receivedAt = ctx.now.toISOString();
  transfer.timeline.push(event(ctx, complete ? "Received in full" : "Partially received"));
  audit(ctx, "TRANSFER_RECEIVED", "TRF", "transfer", transfer.id);
  if (transfer.lines.some((l) => l.quantityShort || l.quantityDamaged || l.quantityExcess)) {
    notify(ctx, "TRANSFER", "Transfer discrepancy", `${transfer.transferNo} has short, damaged or excess quantities.`, { link: "/inventory/transfers", permission: "inventory.transfer.approve" });
  }
  return transfer;
});

POST("/inventory/transfers/:id/close", (ctx) => {
  requirePerm(ctx, "inventory.transfer.approve");
  const transfer = getTrf(ctx, ctx.params.id);
  if (transfer.status !== "RECEIVED") return badState("Only a fully received transfer can be closed.");
  const transit = inTransitLocation(ctx.db);
  const destination = sellableLocation(ctx.db, transfer.destinationWarehouseId);
  for (const line of transfer.lines) {
    const product = getProduct(ctx.db, line.productId);
    const common = { type: "TRANSFER_VARIANCE" as const, productId: line.productId, unitCost: product.avgCost ?? 0, sourceType: "TRANSFER", sourceId: transfer.id, sourceNo: transfer.transferNo, approvedBy: requireUser(ctx).fullName };
    if (line.quantityShort > 0) postMovement(ctx, { ...common, fromLocationId: transit.id, quantityBase: line.quantityShort, reasonCode: "Short on receipt" });
    if (line.quantityExcess > 0) postMovement(ctx, { ...common, toLocationId: destination.id, quantityBase: line.quantityExcess, reasonCode: "Excess on receipt" });
  }
  transfer.status = "CLOSED";
  transfer.timeline.push(event(ctx, "Closed and reconciled"));
  audit(ctx, "TRANSFER_CLOSED", "TRF", "transfer", transfer.id);
  return transfer;
});

POST("/inventory/transfers/:id/cancel", (ctx) => {
  requirePerm(ctx, "inventory.transfer");
  const transfer = getTrf(ctx, ctx.params.id);
  if (transfer.status !== "REQUESTED" && transfer.status !== "APPROVED") return badState("After dispatch, stock must be returned to source through a receipt at source.");
  transfer.status = "CANCELLED";
  transfer.timeline.push(event(ctx, "Cancelled", (ctx.body as { reason?: string }).reason));
  audit(ctx, "TRANSFER_CANCELLED", "TRF", "transfer", transfer.id);
  return transfer;
});

// Stock counts (BR-INV-008)
const getCount = (ctx: Ctx, id: string): StockCount => ctx.db.counts.find((c) => c.id === id) ?? (notFound("Count") as never);

function countView(ctx: Ctx, count: StockCount): StockCount {
  const hideSystem = count.blind && (count.status === "OPEN" || count.status === "COUNTING");
  if (!hideSystem && canSeeCost(ctx)) return count;
  return {
    ...count,
    lines: count.lines.map((l) => ({ ...l, snapshotQty: hideSystem ? null : l.snapshotQty, variance: hideSystem ? null : l.variance, valueVariance: hideSystem || !canSeeCost(ctx) ? null : l.valueVariance })),
  };
}

GET("/inventory/counts", (ctx) => {
  requirePerm(ctx, "inventory.view");
  const inBranch = branchFilter(ctx);
  return list(ctx.db.counts.filter((c) => inBranch(getWarehouse(ctx.db, c.warehouseId).branchId)).map((c) => countView(ctx, c)));
});

POST("/inventory/counts", (ctx) => {
  requirePerm(ctx, "inventory.count");
  const user = requireUser(ctx);
  const { db } = ctx;
  const input = ctx.body as { warehouseId: string; scope: StockCount["scope"]; categoryId?: string; locationId?: string; sampleSize?: number; freeze?: boolean; blind?: boolean };
  const warehouse = getWarehouse(db, input.warehouseId);
  let locations = db.locations.filter((l) => l.warehouseId === warehouse.id && l.type !== "IN_TRANSIT" && l.status === "ACTIVE");
  if (input.scope === "CYCLE_LOCATION") locations = locations.filter((l) => l.id === input.locationId);
  else locations = locations.filter((l) => l.type === "SELLABLE" || l.type === "STORAGE");
  let products = db.products.filter((p) => p.type !== "SERVICE" && p.type !== "VARIANT_PARENT" && p.status !== "INACTIVE");
  if (input.scope === "CYCLE_CATEGORY") products = products.filter((p) => p.categoryId === input.categoryId);
  if (input.scope === "CYCLE_RANDOM") products = [...products].sort(() => Math.random() - 0.5).slice(0, input.sampleSize ?? 10);
  const lines: StockCountLine[] = locations.flatMap((location) =>
    products
      .filter((p) => input.scope !== "FULL" || db.balances.some((b) => b.locationId === location.id && b.productId === p.id && b.onHand !== 0))
      .map((p) => ({ id: uid("cl"), locationId: location.id, locationName: location.name, productId: p.id, sku: p.sku, productName: p.nameEn, unitCode: unitCode(ctx, p), snapshotQty: null, countedQty: null, countedAt: null, countedBy: null, variance: null, valueVariance: null, reason: "", recountRequired: false })),
  );
  if (!lines.length) return validation("scope", "No items match this count scope.");
  const label = input.scope === "FULL" ? "Full stocktake" : input.scope === "CYCLE_CATEGORY" ? `Category: ${db.categories.find((c) => c.id === input.categoryId)?.nameEn}` : input.scope === "CYCLE_LOCATION" ? `Location: ${locations[0]?.name}` : `Random sample of ${products.length}`;
  const count: StockCount = {
    id: uid("cnt"), countNo: nextDocNo(ctx, "COUNT"), warehouseId: warehouse.id, warehouseName: warehouse.name, scope: input.scope, scopeLabel: label, freeze: Boolean(input.freeze), blind: Boolean(input.blind), status: "OPEN", lines,
    createdBy: user.fullName, createdById: user.id, approvedBy: null, createdAt: ctx.now.toISOString(), postedAt: null, timeline: [event(ctx, "Created", input.freeze ? "Warehouse frozen" : undefined)],
  };
  db.counts.unshift(count);
  audit(ctx, "COUNT_CREATED", "ADJ", "count", count.id, { after: { scope: label, freeze: count.freeze } });
  return countView(ctx, count);
});

PATCH("/inventory/counts/:id/lines", (ctx) => {
  requirePerm(ctx, "inventory.count");
  const user = requireUser(ctx);
  const count = getCount(ctx, ctx.params.id);
  if (count.status !== "OPEN" && count.status !== "COUNTING" && count.status !== "REVIEW") return badState("This count can no longer be edited.");
  const { lines } = ctx.body as { lines: { lineId: string; countedQty?: number | null; reason?: string }[] };
  for (const entry of lines) {
    const line = count.lines.find((l) => l.id === entry.lineId);
    if (!line) return notFound("Count line");
    if (entry.countedQty !== undefined && entry.countedQty !== null) {
      if (entry.countedQty < 0) return validation("countedQty", "Counted quantity must not be negative.");
      const product = getProduct(ctx.db, line.productId);
      line.snapshotQty = ctx.db.balances.find((b) => b.locationId === line.locationId && b.productId === line.productId)?.onHand ?? 0;
      line.countedQty = entry.countedQty;
      line.countedAt = ctx.now.toISOString();
      line.countedBy = user.fullName;
      line.variance = round(entry.countedQty - line.snapshotQty, 4);
      line.valueVariance = round(line.variance * (product.avgCost ?? 0), 2);
      line.recountRequired = false;
    }
    if (entry.reason !== undefined) line.reason = entry.reason;
  }
  if (count.status === "OPEN") count.status = "COUNTING";
  return countView(ctx, count);
});

POST("/inventory/counts/:id/submit", (ctx) => {
  requirePerm(ctx, "inventory.count");
  const count = getCount(ctx, ctx.params.id);
  if (count.status !== "COUNTING") return badState("Enter counts before submitting.");
  if (count.lines.some((l) => l.countedQty === null)) return validation("lines", "Counted quantity required for every line.");
  count.lines.forEach((l) => (l.recountRequired = Math.abs(l.variance ?? 0) >= ctx.db.settings.countVarianceRecountQty && !l.reason));
  count.status = "REVIEW";
  count.timeline.push(event(ctx, "Submitted for review"));
  return countView(ctx, count);
});

POST("/inventory/counts/:id/recount", (ctx) => {
  requirePerm(ctx, "inventory.count");
  const count = getCount(ctx, ctx.params.id);
  if (count.status !== "REVIEW") return badState("Only a count under review can be recounted.");
  const { lineIds } = ctx.body as { lineIds: string[] };
  count.lines.filter((l) => lineIds.includes(l.id)).forEach((l) => {
    Object.assign(l, { countedQty: null, snapshotQty: null, countedAt: null, countedBy: null, variance: null, valueVariance: null, recountRequired: false });
  });
  count.status = "COUNTING";
  count.timeline.push(event(ctx, `Recount requested for ${lineIds.length} line(s)`));
  return countView(ctx, count);
});

POST("/inventory/counts/:id/approve", (ctx) => {
  requirePerm(ctx, "inventory.count.approve");
  const count = getCount(ctx, ctx.params.id);
  if (count.status !== "REVIEW") return badState("Only a count under review can be approved.");
  if (count.lines.some((l) => Math.abs(l.variance ?? 0) >= ctx.db.settings.countVarianceRecountQty && !l.reason.trim())) return validation("lines", "Variance above threshold — recount or reason required");
  assertNotSelfApproval(ctx, count.createdById, "stock count");
  count.status = "APPROVED";
  count.approvedBy = requireUser(ctx).fullName;
  count.timeline.push(event(ctx, "Approved"));
  return countView(ctx, count);
});

POST("/inventory/counts/:id/post", (ctx) => {
  requirePerm(ctx, "inventory.count.approve");
  const count = getCount(ctx, ctx.params.id);
  if (count.status === "POSTED") return fail(409, "ALREADY_POSTED", "This count has already been posted.");
  if (count.status !== "APPROVED") return badState("Only an approved count can be posted.");
  for (const line of count.lines) {
    if (!line.variance) continue;
    const product = getProduct(ctx.db, line.productId);
    postMovement(ctx, {
      type: "COUNT_VARIANCE", productId: line.productId, fromLocationId: line.variance < 0 ? line.locationId : null, toLocationId: line.variance > 0 ? line.locationId : null,
      quantityBase: Math.abs(line.variance), unitCost: product.avgCost ?? 0, sourceType: "COUNT", sourceId: count.id, sourceNo: count.countNo, reasonCode: line.reason || "Count variance", approvedBy: count.approvedBy, skipNegativeCheck: true,
    });
  }
  count.status = "POSTED";
  count.postedAt = ctx.now.toISOString();
  count.timeline.push(event(ctx, "Posted"));
  audit(ctx, "COUNT_POSTED", "ADJ", "count", count.id);
  return countView(ctx, count);
});

POST("/inventory/counts/:id/cancel", (ctx) => {
  requirePerm(ctx, "inventory.count");
  const count = getCount(ctx, ctx.params.id);
  if (count.status === "POSTED" || count.status === "CANCELLED") return badState("This count cannot be cancelled.");
  count.status = "CANCELLED";
  count.timeline.push(event(ctx, "Cancelled"));
  return countView(ctx, count);
});

// Alerts
GET("/alerts", (ctx) => {
  requirePerm(ctx, "alerts.view", "inventory.view");
  const inBranch = branchFilter(ctx);
  const nowIso = ctx.now.toISOString();
  return list(ctx.db.alerts.filter((a) => inBranch(a.branchId)).map((a) => (a.status === "SNOOZED" && a.snoozedUntil && a.snoozedUntil <= nowIso ? { ...a, status: "OPEN" as const } : a)));
});

POST("/alerts/:id/action", (ctx) => {
  requirePerm(ctx, "alerts.manage");
  const alert = ctx.db.alerts.find((a) => a.id === ctx.params.id);
  if (!alert) return notFound("Alert");
  const { action, note, assignedTo, days } = ctx.body as { action: "ACKNOWLEDGE" | "RESOLVE" | "SNOOZE" | "ASSIGN"; note?: string; assignedTo?: string; days?: number };
  if (action === "ACKNOWLEDGE") alert.status = "ACKNOWLEDGED";
  if (action === "RESOLVE") {
    if (!note?.trim()) return validation("note", "A note is required to resolve an alert manually.");
    alert.status = "RESOLVED";
    alert.note = note;
  }
  if (action === "SNOOZE") {
    alert.status = "SNOOZED";
    alert.snoozedUntil = new Date(ctx.now.getTime() + (days ?? 1) * 86_400_000).toISOString();
    alert.note = note ?? null;
  }
  if (action === "ASSIGN") alert.assignedTo = assignedTo ?? null;
  alert.updatedAt = ctx.now.toISOString();
  audit(ctx, `ALERT_${action}`, "ALR", "alert", alert.id);
  return alert;
});

function raiseCheckAlert(ctx: Ctx, type: "EXPIRING" | "EXPIRED" | "SLOW_MOVING", product: Product, warehouseId: string | null, message: string) {
  if (ctx.db.alerts.some((a) => a.type === type && a.productId === product.id && a.warehouseId === warehouseId && a.status !== "RESOLVED")) return false;
  const warehouse = warehouseId ? getWarehouse(ctx.db, warehouseId) : null;
  ctx.db.alerts.unshift({ id: uid("alr"), type, productId: product.id, sku: product.sku, productName: product.nameEn, warehouseId, warehouseName: warehouse?.name ?? "All", branchId: warehouse?.branchId ?? null, message, status: "OPEN", assignedTo: null, snoozedUntil: null, note: null, createdAt: ctx.now.toISOString(), updatedAt: ctx.now.toISOString() });
  return true;
}

export function runScheduledAlertChecks(ctx: Ctx) {
  const { db } = ctx;
  evaluateStockAlerts(ctx, db.products.map((p) => p.id));
  const todayIso = ctx.now.toISOString().slice(0, 10);
  const today = new Date(todayIso).getTime();
  let raised = 0;
  for (const batch of db.batches.filter((b) => b.quantity > 0)) {
    const days = Math.round((new Date(batch.expiryDate).getTime() - today) / 86_400_000);
    const product = getProduct(db, batch.productId);
    const warehouseId = getLocation(db, batch.locationId).warehouseId;
    if (days < 0 && raiseCheckAlert(ctx, "EXPIRED", product, warehouseId, `Batch ${batch.batchNo} of ${product.nameEn} expired on ${batch.expiryDate}.`)) raised++;
    else if (days >= 0 && days <= db.settings.expiryWarningDays && raiseCheckAlert(ctx, "EXPIRING", product, warehouseId, `Batch ${batch.batchNo} of ${product.nameEn} expires in ${days} days.`)) raised++;
  }
  const cutoff = new Date(ctx.now.getTime() - db.settings.slowMovingDays * 86_400_000).toISOString();
  const sold = new Set(db.sales.filter((s) => s.status === "FINALIZED" && (s.finalizedAt ?? "") >= cutoff).flatMap((s) => s.lines.map((l) => l.productId)));
  for (const product of db.products.filter((p) => p.status === "ACTIVE" && p.type !== "SERVICE" && p.type !== "VARIANT_PARENT")) {
    const onHand = db.balances.filter((b) => b.productId === product.id).reduce((s, b) => s + b.onHand, 0);
    if (onHand > 0 && !sold.has(product.id) && raiseCheckAlert(ctx, "SLOW_MOVING", product, null, `${product.nameEn} has no sales in the last ${db.settings.slowMovingDays} days with ${onHand} on hand.`)) raised++;
  }
  return raised;
}

POST("/alerts/evaluate", (ctx) => {
  requirePerm(ctx, "alerts.view");
  return { raised: runScheduledAlertChecks(ctx) };
});

export { onHandInWarehouse };
