import type {
  AlertType, InventoryAlert, MovementType, Product, StockBalance, StockLocation, StockSettings, Warehouse,
} from "@/types";
import { businessDate, fail, notFound, notify, requireUser, round, uid, type Ctx } from "../core";
import type { MockDb } from "../db";

export function getProduct(db: MockDb, id: string): Product {
  return db.products.find((p) => p.id === id) ?? (notFound("Product") as never);
}

export function getLocation(db: MockDb, id: string): StockLocation {
  return db.locations.find((l) => l.id === id) ?? (notFound("Location") as never);
}

export function getWarehouse(db: MockDb, id: string): Warehouse {
  return db.warehouses.find((w) => w.id === id) ?? (notFound("Warehouse") as never);
}

export function balanceOf(db: MockDb, locationId: string, productId: string): StockBalance {
  let balance = db.balances.find((b) => b.locationId === locationId && b.productId === productId);
  if (!balance) {
    balance = { locationId, productId, onHand: 0, reserved: 0 };
    db.balances.push(balance);
  }
  return balance;
}

export function locationByType(db: MockDb, warehouseId: string, type: StockLocation["type"]) {
  return db.locations.find((l) => l.warehouseId === warehouseId && l.type === type && l.status === "ACTIVE");
}

export function sellableLocation(db: MockDb, warehouseId: string): StockLocation {
  return (
    locationByType(db, warehouseId, "SELLABLE") ??
    locationByType(db, warehouseId, "STORAGE") ??
    (fail(422, "VALIDATION_ERROR", "This warehouse has no sellable location.") as never)
  );
}

export const inTransitLocation = (db: MockDb) =>
  db.locations.find((l) => l.type === "IN_TRANSIT") ?? (fail(500, "CONFIG_ERROR", "In-transit location missing.") as never);

export function availableAt(db: MockDb, locationId: string, productId: string) {
  const b = db.balances.find((x) => x.locationId === locationId && x.productId === productId);
  return b ? round(b.onHand - b.reserved, 4) : 0;
}

export function availableInWarehouse(db: MockDb, warehouseId: string, productId: string) {
  const sellable = new Set(db.locations.filter((l) => l.warehouseId === warehouseId && l.availableToSell).map((l) => l.id));
  return round(
    db.balances.filter((b) => b.productId === productId && sellable.has(b.locationId)).reduce((s, b) => s + b.onHand - b.reserved, 0),
    4,
  );
}

export function onHandInWarehouse(db: MockDb, warehouseId: string, productId: string) {
  const locations = new Set(db.locations.filter((l) => l.warehouseId === warehouseId).map((l) => l.id));
  return round(db.balances.filter((b) => b.productId === productId && locations.has(b.locationId)).reduce((s, b) => s + b.onHand, 0), 4);
}

export const companyOnHand = (db: MockDb, productId: string) =>
  round(db.balances.filter((b) => b.productId === productId).reduce((s, b) => s + b.onHand, 0), 4);

export function onOrderBase(db: MockDb, productId: string, warehouseId?: string) {
  const open = new Set(["APPROVED", "SENT", "PARTIALLY_RECEIVED"]);
  return round(
    db.purchaseOrders
      .filter((po) => open.has(po.status) && (!warehouseId || po.warehouseId === warehouseId))
      .flatMap((po) => po.lines)
      .filter((l) => l.productId === productId)
      .reduce((s, l) => s + Math.max(0, l.quantityBase - l.receivedBase - l.cancelledBase), 0),
    4,
  );
}

export function negativeAllowed(db: MockDb, product: Product) {
  const category = db.categories.find((c) => c.id === product.categoryId);
  return db.settings.negativeStockAllowed || Boolean(category?.allowNegativeStock);
}

export function settingsFor(product: Product, warehouseId: string): StockSettings {
  return product.warehouseSettings[warehouseId] ?? product.stockSettings;
}

export interface MovementInput {
  type: MovementType;
  productId: string;
  fromLocationId?: string | null;
  toLocationId?: string | null;
  quantityBase: number;
  unitCode?: string;
  quantityEntered?: number;
  unitCost: number;
  sourceType: string;
  sourceId: string;
  sourceNo: string;
  reasonCode?: string | null;
  approvedBy?: string | null;
  reversesMovementId?: number | null;
  batchNo?: string | null;
  /** System reversals may need to pass even at zero stock. */
  skipNegativeCheck?: boolean;
}

/** Single entry point for stock changes. Movements are append-only (BR-INV-001, BR-INV-002). */
export function postMovement(ctx: Ctx, input: MovementInput) {
  const { db } = ctx;
  const user = requireUser(ctx);
  const product = getProduct(db, input.productId);
  if (product.type === "SERVICE") return null;
  if (!(input.quantityBase > 0)) fail(422, "VALIDATION_ERROR", "Movement quantity must be positive.");
  if (!product.allowFraction && !Number.isInteger(round(input.quantityBase, 6))) {
    fail(422, "INVALID_QUANTITY_FOR_UNIT", `${product.nameEn} must be moved in whole units.`);
  }
  const from = input.fromLocationId ? getLocation(db, input.fromLocationId) : null;
  const to = input.toLocationId ? getLocation(db, input.toLocationId) : null;
  if (!from && !to) fail(422, "VALIDATION_ERROR", "A movement needs a source or destination location.");
  if (from) {
    const balance = balanceOf(db, from.id, product.id);
    const next = round(balance.onHand - input.quantityBase, 4);
    if (next < 0 && !input.skipNegativeCheck && !negativeAllowed(db, product)) {
      fail(422, "INSUFFICIENT_STOCK", `Only ${balance.onHand} of ${product.nameEn} available at ${from.name}.`, [
        { message: "insufficient", requested: input.quantityBase, available: balance.onHand },
      ]);
    }
    balance.onHand = next;
  }
  if (to) {
    const balance = balanceOf(db, to.id, product.id);
    balance.onHand = round(balance.onHand + input.quantityBase, 4);
  }
  const anchor = from ?? (to as StockLocation);
  const warehouse = getWarehouse(db, anchor.type === "IN_TRANSIT" && to && from ? to.warehouseId : anchor.warehouseId);
  const movement = {
    id: ++db.movementSeq,
    branchId: warehouse.branchId,
    warehouseId: warehouse.id,
    productId: product.id,
    sku: product.sku,
    productName: product.nameEn,
    fromLocationId: from?.id ?? null,
    toLocationId: to?.id ?? null,
    fromLocationName: from ? `${getWarehouse(db, from.warehouseId).code} / ${from.name}` : null,
    toLocationName: to ? `${getWarehouse(db, to.warehouseId).code} / ${to.name}` : null,
    type: input.type,
    quantityBase: input.quantityBase,
    unitCode: input.unitCode ?? db.units.find((u) => u.id === product.baseUnitId)?.code ?? "",
    quantityEntered: input.quantityEntered ?? input.quantityBase,
    unitCost: round(input.unitCost, 4),
    totalCost: round(input.unitCost * input.quantityBase, 2),
    batchNo: input.batchNo ?? null,
    businessDate: businessDate(db, warehouse.branchId, ctx.now),
    postedAt: ctx.now.toISOString(),
    sourceType: input.sourceType,
    sourceId: input.sourceId,
    sourceNo: input.sourceNo,
    reasonCode: input.reasonCode ?? null,
    reversesMovementId: input.reversesMovementId ?? null,
    reversedByMovementId: null,
    approvedBy: input.approvedBy ?? null,
    userId: user.id,
    userName: user.fullName,
  };
  db.movements.push(movement);
  product.hasMovements = true;
  ctx.touchedProducts.add(product.id);
  return movement;
}

/** Weighted average cost update on receipts and resalable returns, company scope (D-05). */
export function applyWac(db: MockDb, product: Product, quantityBase: number, unitCost: number) {
  const onHand = Math.max(0, companyOnHand(db, product.id));
  const avg = product.avgCost ?? 0;
  const next = onHand + quantityBase > 0 ? (onHand * avg + quantityBase * unitCost) / (onHand + quantityBase) : unitCost;
  product.avgCost = round(next, 4);
}

function raiseAlert(ctx: Ctx, type: AlertType, product: Product, warehouse: Warehouse, message: string) {
  const { db } = ctx;
  const existing = db.alerts.find(
    (a) => a.type === type && a.productId === product.id && a.warehouseId === warehouse.id && a.status !== "RESOLVED",
  );
  if (existing) {
    existing.message = message;
    return;
  }
  const alert: InventoryAlert = {
    id: uid("alr"),
    type,
    productId: product.id,
    sku: product.sku,
    productName: product.nameEn,
    warehouseId: warehouse.id,
    warehouseName: warehouse.name,
    branchId: warehouse.branchId,
    message,
    status: "OPEN",
    assignedTo: null,
    snoozedUntil: null,
    note: null,
    createdAt: ctx.now.toISOString(),
    updatedAt: ctx.now.toISOString(),
  };
  db.alerts.unshift(alert);
  notify(ctx, "STOCK_ALERT", `${type.replaceAll("_", " ")}: ${product.nameEn}`, message, {
    link: "/inventory/alerts",
    permission: "alerts.view",
    branchId: warehouse.branchId,
  });
}

function clearAlert(ctx: Ctx, type: AlertType, productId: string, warehouseId: string) {
  ctx.db.alerts
    .filter((a) => a.type === type && a.productId === productId && a.warehouseId === warehouseId && a.status !== "RESOLVED")
    .forEach((a) => {
      a.status = "RESOLVED";
      a.note = "Resolved automatically: condition cleared";
      a.updatedAt = ctx.now.toISOString();
    });
}

/** Evaluated after commit for each product touched by the request (FR-ALR-001 to 003, 007). */
export function evaluateStockAlerts(ctx: Ctx, productIds: Iterable<string>) {
  const { db } = ctx;
  for (const productId of productIds) {
    const product = db.products.find((p) => p.id === productId);
    if (!product || product.type === "SERVICE" || product.type === "VARIANT_PARENT" || product.status !== "ACTIVE") continue;
    for (const warehouse of db.warehouses.filter((w) => w.status === "ACTIVE" && w.branchId)) {
      const settings = settingsFor(product, warehouse.id);
      const available = availableInWarehouse(db, warehouse.id, product.id);
      const onHand = onHandInWarehouse(db, warehouse.id, product.id);
      const set = (type: AlertType, active: boolean, message: string) =>
        active ? raiseAlert(ctx, type, product, warehouse, message) : clearAlert(ctx, type, product.id, warehouse.id);
      set("OUT_OF_STOCK", available <= 0, `${product.nameEn} is out of stock at ${warehouse.name}.`);
      set(
        "LOW_STOCK",
        available > 0 && available <= settings.reorderLevel,
        `${product.nameEn} has ${available} available at ${warehouse.name} (reorder level ${settings.reorderLevel}).`,
      );
      set("OVERSTOCK", settings.maxLevel > 0 && onHand > settings.maxLevel, `${product.nameEn} has ${onHand} on hand at ${warehouse.name} (maximum ${settings.maxLevel}).`);
      set("NEGATIVE_STOCK", onHand < 0, `${product.nameEn} has a negative balance (${onHand}) at ${warehouse.name}.`);
    }
  }
}

/** FEFO deduction for expiry-tracked products (BR-INV-007, BR-INV-005). */
export function consumeBatchesFefo(ctx: Ctx, product: Product, locationId: string, quantity: number) {
  const { db } = ctx;
  if (!product.trackExpiry) return;
  const today = ctx.now.toISOString().slice(0, 10);
  const batches = db.batches
    .filter((b) => b.productId === product.id && b.locationId === locationId && b.quantity > 0)
    .sort((a, b) => a.expiryDate.localeCompare(b.expiryDate));
  const fresh = batches.filter((b) => b.expiryDate >= today);
  if (batches.length && !fresh.length) {
    fail(422, "BATCH_EXPIRED", `${product.nameEn}: the only available batch has expired and cannot be sold.`);
  }
  let remaining = quantity;
  for (const batch of fresh) {
    if (remaining <= 0) break;
    const take = Math.min(batch.quantity, remaining);
    batch.quantity = round(batch.quantity - take, 4);
    remaining = round(remaining - take, 4);
  }
}

export function reconcileBalances(db: MockDb) {
  const sums = new Map<string, number>();
  const add = (loc: string | null, product: string, delta: number) => {
    if (!loc) return;
    const key = `${loc}|${product}`;
    sums.set(key, round((sums.get(key) ?? 0) + delta, 4));
  };
  for (const m of db.movements) {
    add(m.toLocationId, m.productId, m.quantityBase);
    add(m.fromLocationId, m.productId, -m.quantityBase);
  }
  const differences: { sku: string; location: string; balance: number; movementSum: number }[] = [];
  for (const b of db.balances) {
    const sum = sums.get(`${b.locationId}|${b.productId}`) ?? 0;
    if (round(b.onHand - sum, 4) !== 0) {
      differences.push({
        sku: db.products.find((p) => p.id === b.productId)?.sku ?? b.productId,
        location: db.locations.find((l) => l.id === b.locationId)?.name ?? b.locationId,
        balance: b.onHand,
        movementSum: sum,
      });
    }
  }
  return { balancesChecked: db.balances.length, differences };
}
