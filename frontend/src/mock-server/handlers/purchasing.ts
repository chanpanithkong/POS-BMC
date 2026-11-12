import type { GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine, PurchaseReturn, Supplier, SupplierInvoice, TimelineEvent } from "@/types";
import {
  assertNotSelfApproval, audit, badState, branchFilter, fail, list, nextDocNo, notFound, notify, requirePerm, requireUser, round, uid, validation, type Ctx,
} from "../core";
import { applyWac, getLocation, getProduct, getWarehouse, locationByType, postMovement, sellableLocation } from "../domain/inventory";
import { assertNotFrozen } from "./inventory";
import { DELETE, GET, PATCH, POST, assertUniqueCode } from "../registry";

const event = (ctx: Ctx, label: string, note?: string): TimelineEvent => ({ at: ctx.now.toISOString(), label, by: requireUser(ctx).fullName, note });

// Suppliers
function supplierView(ctx: Ctx, supplier: Supplier): Supplier {
  const pos = ctx.db.purchaseOrders.filter((p) => p.supplierId === supplier.id);
  const open = pos.filter((p) => ["APPROVED", "SENT", "PARTIALLY_RECEIVED"].includes(p.status));
  const received = pos.filter((p) => p.firstReceivedAt);
  const onTime = received.filter((p) => (p.firstReceivedAt ?? "").slice(0, 10) <= p.expectedDate).length;
  const lines = pos.filter((p) => !["DRAFT", "PENDING_APPROVAL", "CANCELLED"].includes(p.status)).flatMap((p) => p.lines);
  const ordered = lines.reduce((s, l) => s + l.quantityBase, 0);
  const fill = lines.reduce((s, l) => s + Math.min(l.receivedBase, l.quantityBase), 0);
  const outstanding = ctx.db.supplierInvoices.filter((i) => i.supplierId === supplier.id).reduce((s, i) => s + i.amount - i.paidAmount, 0);
  return { ...supplier, openPoCount: open.length, onTimeRate: received.length ? round((onTime / received.length) * 100, 1) : null, fillRate: ordered ? round((fill / ordered) * 100, 1) : null, outstandingBalance: round(outstanding, 2) };
}

function validateSupplier(ctx: Ctx, input: Partial<Supplier>, existing: Supplier | null) {
  assertUniqueCode(ctx.db.suppliers, input.code, existing);
  if (input.nameEn !== undefined && !input.nameEn.trim()) validation("nameEn", "Name is required.");
}

GET("/suppliers", (ctx) => {
  requirePerm(ctx, "suppliers.view", "purchasing.view");
  return list(ctx.db.suppliers.map((s) => supplierView(ctx, s)));
});
GET("/suppliers/:id", (ctx) => {
  requirePerm(ctx, "suppliers.view");
  const supplier = ctx.db.suppliers.find((s) => s.id === ctx.params.id);
  return supplier ? supplierView(ctx, supplier) : notFound("Supplier");
});
POST("/suppliers", (ctx) => {
  requirePerm(ctx, "suppliers.manage");
  const input = ctx.body as Partial<Supplier>;
  validateSupplier(ctx, input, null);
  const supplier = { ...input, id: uid("sup"), contacts: input.contacts ?? [] } as Supplier;
  ctx.db.suppliers.unshift(supplier);
  audit(ctx, "SUPPLIER_CREATED", "PUR", "supplier", supplier.id, { after: supplier });
  return supplierView(ctx, supplier);
});
PATCH("/suppliers/:id", (ctx) => {
  requirePerm(ctx, "suppliers.manage");
  const supplier = ctx.db.suppliers.find((s) => s.id === ctx.params.id);
  if (!supplier) return notFound("Supplier");
  const input = ctx.body as Partial<Supplier>;
  validateSupplier(ctx, input, supplier);
  Object.assign(supplier, input);
  audit(ctx, "SUPPLIER_UPDATED", "PUR", "supplier", supplier.id, { after: supplier });
  return supplierView(ctx, supplier);
});
DELETE("/suppliers/:id", (ctx) => {
  requirePerm(ctx, "suppliers.manage");
  const id = ctx.params.id;
  if (ctx.db.purchaseOrders.some((p) => p.supplierId === id) || ctx.db.products.some((p) => p.suppliers.some((s) => s.supplierId === id))) {
    return fail(409, "IN_USE", "This supplier has purchase history or product links. Deactivate it instead.");
  }
  ctx.db.suppliers = ctx.db.suppliers.filter((s) => s.id !== id);
  audit(ctx, "SUPPLIER_DELETED", "PUR", "supplier", id);
  return undefined;
});

// Purchase orders
const getPo = (ctx: Ctx, id: string): PurchaseOrder => ctx.db.purchaseOrders.find((p) => p.id === id) ?? (notFound("Purchase order") as never);

function buildPoLines(ctx: Ctx, lines: { productId: string; unitId: string; quantity: number; unitCost: number; taxRate?: number }[], supplierId: string): PurchaseOrderLine[] {
  if (!lines?.length) validation("lines", "Add at least one line.");
  return lines.map((l) => {
    const product = getProduct(ctx.db, l.productId);
    if (!(l.quantity > 0)) validation("lines", "Quantity must be greater than zero.");
    if (l.unitCost < 0) validation("lines", "Cost must not be negative.");
    const factor = l.unitId === product.baseUnitId ? 1 : (product.conversions.find((c) => c.unitId === l.unitId)?.factor ?? 1);
    const base = round(l.quantity * factor, 4);
    if (!product.allowFraction && !Number.isInteger(base)) fail(422, "INVALID_QUANTITY_FOR_UNIT", `${product.nameEn} must be ordered in whole units.`);
    const taxRate = l.taxRate ?? 0;
    return {
      id: uid("pol"), productId: product.id, sku: product.sku, productName: product.nameEn, supplierSku: product.suppliers.find((s) => s.supplierId === supplierId)?.supplierSku ?? "",
      unitId: l.unitId, unitCode: ctx.db.units.find((u) => u.id === l.unitId)?.code ?? "", factor, quantity: l.quantity, quantityBase: base, unitCost: l.unitCost, taxRate,
      lineTotal: round(l.quantity * l.unitCost, 2), receivedBase: 0, cancelledBase: 0,
    };
  });
}

function setPoTotals(po: PurchaseOrder) {
  po.subtotal = round(po.lines.reduce((s, l) => s + l.lineTotal, 0), 2);
  po.taxTotal = round(po.lines.reduce((s, l) => s + (l.lineTotal * l.taxRate) / 100, 0), 2);
  po.total = round(po.subtotal + po.taxTotal, 2);
}

GET("/purchase-orders", (ctx) => {
  requirePerm(ctx, "purchasing.view");
  const inBranch = branchFilter(ctx);
  return list(ctx.db.purchaseOrders.filter((p) => inBranch(p.branchId) && (!ctx.query.supplierId || p.supplierId === ctx.query.supplierId)));
});

POST("/purchase-orders", (ctx) => {
  requirePerm(ctx, "purchasing.create");
  const user = requireUser(ctx);
  const input = ctx.body as { supplierId: string; warehouseId: string; expectedDate: string; notes?: string; lines: Parameters<typeof buildPoLines>[1] };
  const supplier = ctx.db.suppliers.find((s) => s.id === input.supplierId);
  if (!supplier) return validation("supplierId", "Supplier is required.");
  if (supplier.status !== "ACTIVE") return validation("supplierId", "Supplier is inactive");
  const warehouse = getWarehouse(ctx.db, input.warehouseId);
  const po: PurchaseOrder = {
    id: uid("po"), poNo: nextDocNo(ctx, "PO"), supplierId: supplier.id, supplierName: supplier.nameEn, warehouseId: warehouse.id, warehouseName: warehouse.name, branchId: warehouse.branchId,
    expectedDate: input.expectedDate, status: "DRAFT", notes: input.notes ?? "", lines: buildPoLines(ctx, input.lines, supplier.id), subtotal: 0, taxTotal: 0, total: 0,
    createdBy: user.fullName, createdById: user.id, approvedBy: null, createdAt: ctx.now.toISOString(), sentAt: null, firstReceivedAt: null, timeline: [event(ctx, "Created")],
  };
  setPoTotals(po);
  ctx.db.purchaseOrders.unshift(po);
  audit(ctx, "PO_CREATED", "PUR", "purchase_order", po.id, { branchId: po.branchId, after: { total: po.total } });
  return po;
});

PATCH("/purchase-orders/:id", (ctx) => {
  requirePerm(ctx, "purchasing.create");
  const po = getPo(ctx, ctx.params.id);
  if (!["DRAFT", "PENDING_APPROVAL", "APPROVED"].includes(po.status)) return badState("This purchase order can no longer be edited.");
  const input = ctx.body as { expectedDate?: string; notes?: string; lines?: Parameters<typeof buildPoLines>[1] };
  if (input.lines) po.lines = buildPoLines(ctx, input.lines, po.supplierId);
  if (input.expectedDate) po.expectedDate = input.expectedDate;
  if (input.notes !== undefined) po.notes = input.notes;
  setPoTotals(po);
  if (po.status === "APPROVED") {
    po.status = "PENDING_APPROVAL";
    po.approvedBy = null;
    po.timeline.push(event(ctx, "Edited after approval — returned for approval"));
  }
  audit(ctx, "PO_UPDATED", "PUR", "purchase_order", po.id, { branchId: po.branchId });
  return po;
});

DELETE("/purchase-orders/:id", (ctx) => {
  requirePerm(ctx, "purchasing.create");
  const po = getPo(ctx, ctx.params.id);
  if (po.status !== "DRAFT") return badState("Only a draft purchase order can be deleted.");
  ctx.db.purchaseOrders = ctx.db.purchaseOrders.filter((p) => p.id !== po.id);
  return undefined;
});

POST("/purchase-orders/:id/submit", (ctx) => {
  requirePerm(ctx, "purchasing.create");
  const po = getPo(ctx, ctx.params.id);
  if (po.status !== "DRAFT") return badState("Only a draft purchase order can be submitted.");
  po.status = "PENDING_APPROVAL";
  po.timeline.push(event(ctx, "Submitted for approval"));
  notify(ctx, "PO_APPROVAL", "Purchase order awaiting approval", `${po.poNo}: ${po.total.toFixed(2)} USD to ${po.supplierName}`, { link: "/purchases", permission: "purchasing.approve", branchId: po.branchId });
  return po;
});

POST("/purchase-orders/:id/approve", (ctx) => {
  requirePerm(ctx, "purchasing.approve");
  const po = getPo(ctx, ctx.params.id);
  if (po.status !== "PENDING_APPROVAL") return badState("Only a pending purchase order can be approved.");
  const selfApproved = assertNotSelfApproval(ctx, po.createdById, "purchase order");
  if (po.total > ctx.limits.poApprovalLimit) return fail(403, "LIMIT_EXCEEDED", `This order is above your approval limit of ${ctx.limits.poApprovalLimit} USD.`);
  po.status = "APPROVED";
  po.approvedBy = requireUser(ctx).fullName;
  po.timeline.push(event(ctx, "Approved"));
  audit(ctx, "PO_APPROVED", "PUR", "purchase_order", po.id, { branchId: po.branchId, flagged: selfApproved });
  return po;
});

POST("/purchase-orders/:id/reject", (ctx) => {
  requirePerm(ctx, "purchasing.approve");
  const po = getPo(ctx, ctx.params.id);
  if (po.status !== "PENDING_APPROVAL") return badState("Only a pending purchase order can be rejected.");
  const { reason } = ctx.body as { reason: string };
  if (!reason?.trim()) return validation("reason", "A rejection reason is required.");
  po.status = "DRAFT";
  po.timeline.push(event(ctx, "Rejected", reason));
  return po;
});

POST("/purchase-orders/:id/send", (ctx) => {
  requirePerm(ctx, "purchasing.create", "purchasing.approve");
  const po = getPo(ctx, ctx.params.id);
  if (po.status !== "APPROVED") return badState("Only an approved purchase order can be sent.");
  po.status = "SENT";
  po.sentAt = ctx.now.toISOString();
  po.timeline.push(event(ctx, "Marked as sent to supplier"));
  return po;
});

POST("/purchase-orders/:id/cancel", (ctx) => {
  requirePerm(ctx, "purchasing.create", "purchasing.approve");
  const po = getPo(ctx, ctx.params.id);
  if (["RECEIVED", "CANCELLED", "SHORT_CLOSED"].includes(po.status)) return badState("This purchase order is already closed.");
  const { reason } = ctx.body as { reason: string };
  if (!reason?.trim()) return validation("reason", "A cancellation reason is required.");
  const partly = po.lines.some((l) => l.receivedBase > 0);
  po.lines.forEach((l) => (l.cancelledBase = round(l.quantityBase - l.receivedBase, 4)));
  po.status = partly ? "SHORT_CLOSED" : "CANCELLED";
  po.timeline.push(event(ctx, partly ? "Remaining quantity cancelled" : "Cancelled", reason));
  audit(ctx, "PO_CANCELLED", "PUR", "purchase_order", po.id, { after: { reason }, branchId: po.branchId });
  return po;
});

// Goods receipts
const getGrn = (ctx: Ctx, id: string): GoodsReceipt => ctx.db.goodsReceipts.find((g) => g.id === id) ?? (notFound("Goods receipt") as never);

GET("/goods-receipts", (ctx) => {
  requirePerm(ctx, "purchasing.view", "receiving.create");
  const inBranch = branchFilter(ctx);
  return list(ctx.db.goodsReceipts.filter((g) => inBranch(g.branchId)));
});

interface GrnLineInput {
  poLineId?: string | null;
  productId: string;
  unitId: string;
  quantityReceived: number;
  quantityDamaged?: number;
  quantityRejected?: number;
  unitCost: number;
  batchNo?: string;
  expiryDate?: string;
}

function buildGrnLines(ctx: Ctx, po: PurchaseOrder | undefined, lines: GrnLineInput[]): GoodsReceiptLine[] {
  if (!lines?.length) validation("lines", "Add at least one line.");
  const today = ctx.now.toISOString().slice(0, 10);
  return lines.map((l) => {
    const product = getProduct(ctx.db, l.productId);
    const factor = l.unitId === product.baseUnitId ? 1 : (product.conversions.find((c) => c.unitId === l.unitId)?.factor ?? 1);
    if ((l.quantityReceived ?? 0) < 0 || (l.quantityDamaged ?? 0) < 0 || (l.quantityRejected ?? 0) < 0) validation("lines", "Quantities must not be negative.");
    if (l.unitCost < 0) validation("lines", "Cost must not be negative.");
    if (product.trackExpiry && l.quantityReceived > 0) {
      if (!l.batchNo?.trim()) validation("lines", `Batch number required for ${product.nameEn}.`);
      if (!l.expiryDate) validation("lines", "Expiry date required");
      if (l.expiryDate && l.expiryDate < today) validation("lines", `Expiry date for ${product.nameEn} is before today.`);
    }
    const poLine = po?.lines.find((x) => x.id === l.poLineId);
    return {
      id: uid("grl"), poLineId: l.poLineId ?? null, productId: product.id, sku: product.sku, productName: product.nameEn, unitId: l.unitId, unitCode: ctx.db.units.find((u) => u.id === l.unitId)?.code ?? "", factor,
      orderedOpen: poLine ? round((poLine.quantityBase - poLine.receivedBase - poLine.cancelledBase) / factor, 4) : 0,
      quantityReceived: l.quantityReceived, quantityDamaged: l.quantityDamaged ?? 0, quantityRejected: l.quantityRejected ?? 0, unitCost: l.unitCost, batchNo: l.batchNo ?? "", expiryDate: l.expiryDate ?? "", trackExpiry: product.trackExpiry,
    };
  });
}

function discrepanciesOf(ctx: Ctx, receipt: GoodsReceipt) {
  const out: string[] = [];
  let needsApproval = false;
  const tolerance = ctx.db.settings.overDeliveryTolerancePct;
  for (const line of receipt.lines) {
    if (receipt.poId) {
      const total = line.quantityReceived + line.quantityDamaged;
      if (line.orderedOpen > 0 && total > line.orderedOpen) {
        const pct = round(((total - line.orderedOpen) / line.orderedOpen) * 100, 1);
        out.push(`${line.productName}: received quantity exceeds open PO quantity by ${pct}% (tolerance ${tolerance}%)`);
        if (pct > tolerance) needsApproval = true;
      } else if (total < line.orderedOpen) {
        out.push(`${line.productName}: under-delivered by ${round(line.orderedOpen - total, 4)} ${line.unitCode}`);
      }
      if (!line.poLineId) {
        out.push(`${line.productName}: item not on the purchase order`);
        needsApproval = true;
      }
    }
    if (line.quantityDamaged > 0) out.push(`${line.productName}: ${line.quantityDamaged} ${line.unitCode} damaged`);
    if (line.quantityRejected > 0) out.push(`${line.productName}: ${line.quantityRejected} ${line.unitCode} rejected`);
    if (line.unitCost === 0 && line.quantityReceived > 0) {
      out.push(`${line.productName}: received at zero cost`);
      needsApproval = true;
    }
  }
  if (!receipt.poId) needsApproval = true;
  return { out, needsApproval };
}

function blindView(receipt: GoodsReceipt) {
  return receipt.blind && receipt.status !== "POSTED" ? { ...receipt, lines: receipt.lines.map((l) => ({ ...l, orderedOpen: 0 })) } : receipt;
}

POST("/goods-receipts", (ctx) => {
  requirePerm(ctx, "receiving.create");
  const user = requireUser(ctx);
  const input = ctx.body as { poId?: string | null; supplierId?: string; warehouseId?: string; deliveryNote: string; invoiceRef?: string; blind?: boolean; exceptionReason?: string; lines: GrnLineInput[] };
  const po = input.poId ? getPo(ctx, input.poId) : undefined;
  if (po && !["APPROVED", "SENT", "PARTIALLY_RECEIVED"].includes(po.status)) return validation("poId", "Goods can only be received against an approved purchase order.");
  if (!po) {
    requirePerm(ctx, "receiving.exception");
    if (!input.exceptionReason?.trim()) return validation("exceptionReason", "A reason is required to receive without a purchase order.");
  }
  if (!input.deliveryNote?.trim()) return validation("deliveryNote", "Delivery note number is required.");
  const warehouse = getWarehouse(ctx.db, po?.warehouseId ?? (input.warehouseId as string));
  const supplier = ctx.db.suppliers.find((s) => s.id === (po?.supplierId ?? input.supplierId));
  if (!supplier) return validation("supplierId", "Supplier is required.");
  const receipt: GoodsReceipt = {
    id: uid("grn"), receiptNo: nextDocNo(ctx, "GRN"), poId: po?.id ?? null, poNo: po?.poNo ?? null, supplierId: supplier.id, supplierName: supplier.nameEn, warehouseId: warehouse.id, warehouseName: warehouse.name, branchId: warehouse.branchId,
    status: "DRAFT", blind: Boolean(input.blind), exceptionReason: input.exceptionReason ?? null, deliveryNote: input.deliveryNote.trim(), invoiceRef: input.invoiceRef ?? "", lines: buildGrnLines(ctx, po, input.lines), discrepancies: [],
    createdBy: user.fullName, createdById: user.id, approvedBy: null, postedBy: null, postedAt: null, createdAt: ctx.now.toISOString(), flaggedForReview: !po,
  };
  receipt.totalCost = round(receipt.lines.reduce((s, l) => s + (l.quantityReceived + l.quantityDamaged) * l.unitCost, 0), 2);
  receipt.discrepancies = discrepanciesOf(ctx, receipt).out;
  ctx.db.goodsReceipts.unshift(receipt);
  return blindView(receipt);
});

function postReceipt(ctx: Ctx, receipt: GoodsReceipt) {
  const user = requireUser(ctx);
  const po = receipt.poId ? getPo(ctx, receipt.poId) : undefined;
  assertNotFrozen(ctx, receipt.warehouseId);
  const sellable = sellableLocation(ctx.db, receipt.warehouseId);
  const damaged = locationByType(ctx.db, receipt.warehouseId, "DAMAGED");
  for (const line of receipt.lines) {
    const product = getProduct(ctx.db, line.productId);
    const baseGood = round(line.quantityReceived * line.factor, 4);
    const baseDamaged = round(line.quantityDamaged * line.factor, 4);
    const unitCostBase = line.unitCost / line.factor;
    if (baseGood + baseDamaged > 0) applyWac(ctx.db, product, baseGood + baseDamaged, unitCostBase);
    if (line.unitCost > 0) product.lastPurchaseCost = round(unitCostBase, 4);
    const common = { type: "PURCHASE_RECEIPT" as const, productId: line.productId, unitCode: line.unitCode, unitCost: unitCostBase, sourceType: "GRN", sourceId: receipt.id, sourceNo: receipt.receiptNo, approvedBy: receipt.approvedBy };
    if (baseGood > 0) {
      postMovement(ctx, { ...common, toLocationId: sellable.id, quantityBase: baseGood, quantityEntered: line.quantityReceived, batchNo: line.batchNo || null });
      if (product.trackExpiry && line.batchNo) ctx.db.batches.push({ id: uid("bat"), productId: product.id, locationId: sellable.id, batchNo: line.batchNo, expiryDate: line.expiryDate, quantity: baseGood, receiptId: receipt.id });
    }
    if (baseDamaged > 0) postMovement(ctx, { ...common, toLocationId: (damaged ?? sellable).id, quantityBase: baseDamaged, quantityEntered: line.quantityDamaged, reasonCode: "Damaged on receipt" });
    const poLine = po?.lines.find((x) => x.id === line.poLineId);
    if (poLine) poLine.receivedBase = round(poLine.receivedBase + baseGood + baseDamaged, 4);
  }
  if (po) {
    const complete = po.lines.every((l) => l.receivedBase + l.cancelledBase >= l.quantityBase);
    po.status = complete ? "RECEIVED" : "PARTIALLY_RECEIVED";
    po.firstReceivedAt ??= ctx.now.toISOString();
    po.timeline.push(event(ctx, `${complete ? "Fully" : "Partially"} received`, receipt.receiptNo));
  }
  receipt.status = "POSTED";
  receipt.postedBy = user.fullName;
  receipt.postedAt = ctx.now.toISOString();
  audit(ctx, "GRN_POSTED", "GRN", "goods_receipt", receipt.id, { after: { receiptNo: receipt.receiptNo, value: receipt.totalCost }, branchId: receipt.branchId, flagged: !receipt.poId });
  if (receipt.discrepancies.length) {
    notify(ctx, "RECEIPT_DISCREPANCY", "Receiving discrepancy", `${receipt.receiptNo}: ${receipt.discrepancies[0]}`, { link: "/purchases/receiving", permission: "inventory.adjust.approve", branchId: receipt.branchId });
  }
  return receipt;
}

POST("/goods-receipts/:id/post", (ctx) => {
  requirePerm(ctx, "receiving.post");
  const receipt = getGrn(ctx, ctx.params.id);
  if (receipt.status === "POSTED") return fail(409, "ALREADY_POSTED", "This receipt has already been posted");
  if (receipt.status === "PENDING_APPROVAL") return badState("This receipt is waiting for approval.");
  const check = discrepanciesOf(ctx, receipt);
  receipt.discrepancies = check.out;
  if (check.needsApproval) {
    receipt.status = "PENDING_APPROVAL";
    notify(ctx, "RECEIPT_DISCREPANCY", "Receipt needs approval", `${receipt.receiptNo}: ${check.out[0] ?? "received without a purchase order"}`, { link: "/purchases/receiving", permission: "inventory.adjust.approve", branchId: receipt.branchId });
    return blindView(receipt);
  }
  return postReceipt(ctx, receipt);
});

POST("/goods-receipts/:id/approve", (ctx) => {
  requirePerm(ctx, "inventory.adjust.approve");
  const receipt = getGrn(ctx, ctx.params.id);
  if (receipt.status !== "PENDING_APPROVAL") return badState("This receipt is not waiting for approval.");
  assertNotSelfApproval(ctx, receipt.createdById, "goods receipt");
  receipt.approvedBy = requireUser(ctx).fullName;
  return postReceipt(ctx, receipt);
});

POST("/goods-receipts/:id/reject", (ctx) => {
  requirePerm(ctx, "inventory.adjust.approve");
  const receipt = getGrn(ctx, ctx.params.id);
  if (receipt.status !== "PENDING_APPROVAL") return badState("This receipt is not waiting for approval.");
  receipt.status = "DRAFT";
  return receipt;
});

DELETE("/goods-receipts/:id", (ctx) => {
  requirePerm(ctx, "receiving.create");
  const receipt = getGrn(ctx, ctx.params.id);
  if (receipt.status === "POSTED") return badState("A posted receipt cannot be deleted.");
  ctx.db.goodsReceipts = ctx.db.goodsReceipts.filter((g) => g.id !== receipt.id);
  return undefined;
});

// Supplier invoices
GET("/supplier-invoices", (ctx) => {
  requirePerm(ctx, "purchasing.view");
  return list(ctx.db.supplierInvoices);
});

POST("/supplier-invoices", (ctx) => {
  requirePerm(ctx, "purchasing.create", "expenses.approve");
  const user = requireUser(ctx);
  const input = ctx.body as { invoiceNo: string; supplierId: string; poId?: string | null; invoiceDate: string; dueDate: string; amount: number };
  const supplier = ctx.db.suppliers.find((s) => s.id === input.supplierId);
  if (!supplier) return validation("supplierId", "Supplier is required.");
  const normal = (v: string) => v.replace(/[^a-z0-9]/gi, "").toLowerCase();
  if (ctx.db.supplierInvoices.some((i) => i.supplierId === supplier.id && normal(i.invoiceNo) === normal(input.invoiceNo ?? ""))) {
    return fail(409, "DUPLICATE_INVOICE", "This supplier invoice has already been recorded.", [{ field: "invoiceNo", message: "Duplicate invoice number for this supplier." }]);
  }
  const po = input.poId ? getPo(ctx, input.poId) : undefined;
  let status: SupplierInvoice["status"] = "RECORDED";
  let matchNotes = "";
  if (po) {
    const receivedValue = round(po.lines.reduce((s, l) => s + (l.receivedBase / l.factor) * l.unitCost * (1 + l.taxRate / 100), 0), 2);
    const difference = round(input.amount - receivedValue, 2);
    status = Math.abs(difference) <= receivedValue * 0.01 ? "MATCHED" : "MISMATCH";
    matchNotes = status === "MATCHED" ? `Matches received value ${receivedValue.toFixed(2)} USD` : `Differs from received value ${receivedValue.toFixed(2)} USD by ${difference.toFixed(2)} USD`;
  }
  const invoice: SupplierInvoice = {
    id: uid("inv"), invoiceNo: input.invoiceNo.trim(), supplierId: supplier.id, supplierName: supplier.nameEn, poId: po?.id ?? null, poNo: po?.poNo ?? null, invoiceDate: input.invoiceDate, dueDate: input.dueDate,
    amount: input.amount, paidAmount: 0, status, matchNotes, payments: [], createdBy: user.fullName, createdAt: ctx.now.toISOString(),
  };
  ctx.db.supplierInvoices.unshift(invoice);
  audit(ctx, "SUPPLIER_INVOICE_RECORDED", "PUR", "supplier_invoice", invoice.id, { after: { invoiceNo: invoice.invoiceNo, status } });
  return invoice;
});

POST("/supplier-invoices/:id/payments", (ctx) => {
  requirePerm(ctx, "purchasing.create", "expenses.approve");
  const user = requireUser(ctx);
  const invoice = ctx.db.supplierInvoices.find((i) => i.id === ctx.params.id);
  if (!invoice) return notFound("Invoice");
  const { amount, reference } = ctx.body as { amount: number; reference: string };
  if (!(amount > 0)) return validation("amount", "Amount must be greater than zero.");
  if (!reference?.trim()) return validation("reference", "A payment reference is required.");
  if (amount > round(invoice.amount - invoice.paidAmount, 2) + 0.005) return validation("amount", "Payment exceeds the outstanding balance.");
  invoice.payments.push({ id: uid("sp"), amount, reference: reference.trim(), paidAt: ctx.now.toISOString(), by: user.fullName });
  invoice.paidAmount = round(invoice.paidAmount + amount, 2);
  invoice.status = invoice.paidAmount >= invoice.amount - 0.005 ? "PAID" : "PARTIALLY_PAID";
  audit(ctx, "SUPPLIER_PAYMENT", "PUR", "supplier_invoice", invoice.id, { after: { amount, reference } });
  return invoice;
});

// Purchase returns
GET("/purchase-returns", (ctx) => {
  requirePerm(ctx, "purchasing.view");
  return list(ctx.db.purchaseReturns);
});

POST("/purchase-returns", (ctx) => {
  requirePerm(ctx, "purchasing.create");
  const user = requireUser(ctx);
  const input = ctx.body as { goodsReceiptId: string; reason: string; lines: { productId: string; locationId: string; quantityBase: number }[] };
  const receipt = getGrn(ctx, input.goodsReceiptId);
  if (receipt.status !== "POSTED") return validation("goodsReceiptId", "Select a posted goods receipt.");
  if (!input.reason?.trim()) return validation("reason", "A reason is required.");
  if (!input.lines?.length) return validation("lines", "Add at least one line.");
  const lines = input.lines.map((l) => {
    const received = receipt.lines.find((x) => x.productId === l.productId);
    if (!received) return validation("lines", "This product is not on the selected receipt.") as never;
    if (!(l.quantityBase > 0)) return validation("lines", "Quantity must be greater than zero.") as never;
    const unitCost = round(received.unitCost / received.factor, 4);
    return { id: uid("prl"), productId: l.productId, sku: received.sku, productName: received.productName, locationId: l.locationId, locationName: getLocation(ctx.db, l.locationId).name, quantityBase: l.quantityBase, unitCost, total: round(l.quantityBase * unitCost, 2) };
  });
  const record: PurchaseReturn = {
    id: uid("prt"), returnNo: nextDocNo(ctx, "SUPPLIER_RETURN"), supplierId: receipt.supplierId, supplierName: receipt.supplierName, goodsReceiptId: receipt.id, goodsReceiptNo: receipt.receiptNo, warehouseId: receipt.warehouseId, status: "DRAFT",
    reason: input.reason.trim(), lines, total: round(lines.reduce((s, l) => s + l.total, 0), 2), creditNoteRef: null, createdBy: user.fullName, createdById: user.id, approvedBy: null, createdAt: ctx.now.toISOString(),
  };
  ctx.db.purchaseReturns.unshift(record);
  return record;
});

const getPrt = (ctx: Ctx, id: string): PurchaseReturn => ctx.db.purchaseReturns.find((p) => p.id === id) ?? (notFound("Purchase return") as never);

POST("/purchase-returns/:id/approve", (ctx) => {
  requirePerm(ctx, "purchasing.approve");
  const record = getPrt(ctx, ctx.params.id);
  if (record.status !== "DRAFT") return badState("Only a draft return can be approved.");
  assertNotSelfApproval(ctx, record.createdById, "purchase return");
  record.status = "APPROVED";
  record.approvedBy = requireUser(ctx).fullName;
  return record;
});

POST("/purchase-returns/:id/dispatch", (ctx) => {
  requirePerm(ctx, "purchasing.create", "receiving.post");
  const record = getPrt(ctx, ctx.params.id);
  if (record.status !== "APPROVED") return badState("Only an approved return can be dispatched.");
  for (const line of record.lines) {
    postMovement(ctx, { type: "PURCHASE_RETURN", productId: line.productId, fromLocationId: line.locationId, quantityBase: line.quantityBase, unitCost: line.unitCost, sourceType: "SUPPLIER_RETURN", sourceId: record.id, sourceNo: record.returnNo, reasonCode: record.reason, approvedBy: record.approvedBy });
  }
  record.status = "DISPATCHED";
  audit(ctx, "PURCHASE_RETURN_DISPATCHED", "PUR", "purchase_return", record.id);
  return record;
});

POST("/purchase-returns/:id/credit", (ctx) => {
  requirePerm(ctx, "purchasing.create", "expenses.approve");
  const record = getPrt(ctx, ctx.params.id);
  if (record.status !== "DISPATCHED") return badState("Dispatch the return before recording a credit note.");
  const { creditNoteRef } = ctx.body as { creditNoteRef: string };
  if (!creditNoteRef?.trim()) return validation("creditNoteRef", "Credit note reference is required.");
  record.creditNoteRef = creditNoteRef.trim();
  record.status = "CREDITED";
  audit(ctx, "SUPPLIER_CREDIT_NOTE", "PUR", "purchase_return", record.id, { after: { creditNoteRef } });
  return record;
});
