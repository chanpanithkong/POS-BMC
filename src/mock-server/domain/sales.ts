import type {
  AddPaymentInput, AppliedDiscount, CashSession, CreateReturnInput, Product, ReturnQuote, Sale, SaleLine, SaleOp, SalePayment,
  SalesReturn, SalesReturnLine, Terminal,
} from "@/types";
import {
  audit, badState, businessDate, can, consumeApproval, currentRate, fail, getBranch, nextDocNo, notFound, notify, requireApproval,
  requireUser, round, uid, validation, type Ctx,
} from "../core";
import {
  applyWac, availableAt, consumeBatchesFefo, getLocation, getProduct, locationByType, negativeAllowed, postMovement,
} from "./inventory";
import { bestPromotion, calculateTotals, derivePaymentStatus, resolvePrice, roundKhr } from "./pricing";
import type { MockDb } from "../db";

export function getTerminal(db: MockDb, id: string | null | undefined): Terminal {
  const terminal = db.terminals.find((t) => t.id === id && t.status === "ACTIVE");
  if (!terminal) return fail(401, "TERMINAL_NOT_REGISTERED", "This device is not registered as a POS terminal.");
  return terminal;
}

export const getSale = (db: MockDb, id: string): Sale => db.sales.find((s) => s.id === id) ?? (notFound("Sale") as never);

export function openSessionFor(db: MockDb, terminalId: string): CashSession | undefined {
  return db.cashSessions.find((s) => s.terminalId === terminalId && s.status === "OPEN");
}

export function createDraftSale(ctx: Ctx, terminal: Terminal, customerId: string | null = null): Sale {
  const user = requireUser(ctx);
  const { db } = ctx;
  const session = openSessionFor(db, terminal.id);
  const customer = customerId ? db.customers.find((c) => c.id === customerId) : undefined;
  const sale: Sale = {
    id: crypto.randomUUID(),
    receiptNo: null,
    branchId: terminal.branchId,
    branchName: getBranch(db, terminal.branchId).nameEn,
    terminalId: terminal.id,
    terminalName: terminal.name,
    sessionId: session?.id ?? null,
    cashierId: user.id,
    cashierName: user.fullName,
    salespersonId: null,
    customerId: customer?.id ?? null,
    customerName: customer?.name ?? null,
    status: "DRAFT",
    paymentStatus: "UNPAID",
    fulfilmentStatus: "NOT_REQUIRED",
    currency: "USD",
    subtotal: 0,
    discountTotal: 0,
    taxTotal: 0,
    rounding: 0,
    grandTotal: 0,
    paidTotal: 0,
    refundedTotal: 0,
    balance: 0,
    exchangeRate: currentRate(db),
    grandTotalKhr: 0,
    orderDiscount: null,
    couponCode: null,
    lines: [],
    payments: [],
    returnIds: [],
    holdLabel: null,
    businessDate: null,
    createdAt: ctx.now.toISOString(),
    finalizedAt: null,
    reprintCount: 0,
    cancelReason: null,
    voidReason: null,
    voidedBy: null,
    invoiceNo: null,
    loyaltyEarned: 0,
    version: 1,
    notices: [],
  };
  db.sales.unshift(sale);
  return sale;
}

function assertQuantity(product: Product, quantity: number, factor: number) {
  if (!(quantity > 0)) fail(422, "INVALID_QUANTITY_FOR_UNIT", "Quantity must be greater than zero.");
  const base = round(quantity * factor, 6);
  if (!product.allowFraction && !Number.isInteger(base)) {
    fail(422, "INVALID_QUANTITY_FOR_UNIT", `${product.nameEn} can only be sold in whole units.`);
  }
  return base;
}

function unitOf(db: MockDb, id: string) {
  return db.units.find((u) => u.id === id) ?? (notFound("Unit") as never);
}

function assertSellable(ctx: Ctx, sale: Sale, product: Product) {
  if (product.status !== "ACTIVE" && product.status !== "DISCONTINUED") {
    fail(422, "VALIDATION_ERROR", `${product.nameEn} is not available for sale.`);
  }
  if (product.type === "VARIANT_PARENT") fail(422, "VALIDATION_ERROR", `Select a specific variant of ${product.nameEn}.`);
  if (product.branchActivation[sale.branchId] === false) fail(422, "VALIDATION_ERROR", `${product.nameEn} is not sold at this branch.`);
}

function buildLine(ctx: Ctx, sale: Sale, product: Product, unitId: string, quantity: number, terminal: Terminal): SaleLine {
  const { db } = ctx;
  const factor = unitId === product.baseUnitId ? 1 : (product.conversions.find((c) => c.unitId === unitId)?.factor ?? 1);
  const base = assertQuantity(product, quantity, factor);
  const customer = sale.customerId ? db.customers.find((c) => c.id === sale.customerId) ?? null : null;
  const resolved = resolvePrice(db, product, unitId, sale.branchId, customer, ctx.now);
  const tax = db.taxCodes.find((t) => t.id === product.taxCodeId);
  return {
    id: uid("ln"),
    productId: product.id,
    sku: product.sku,
    nameEn: product.nameEn,
    nameKm: product.nameKm,
    unitId,
    unitCode: unitOf(db, unitId).code,
    factor,
    quantity,
    quantityBase: base,
    allowFraction: product.allowFraction,
    precision: product.precision,
    unitPrice: resolved.price,
    priceSource: resolved.source,
    priceExplanation: resolved.explanation,
    listPrice: resolved.price,
    overrideApprovedBy: null,
    overrideReason: null,
    lineDiscount: null,
    promotionName: resolved.promotionName,
    grossAmount: 0,
    discountAmount: 0,
    orderDiscountShare: 0,
    taxCodeId: tax?.id ?? null,
    taxCode: tax?.code ?? "EXEMPT",
    taxRate: tax?.rate ?? 0,
    taxAmount: 0,
    lineTotal: 0,
    returnedQuantity: 0,
    available: product.type === "SERVICE" ? 999999 : availableAt(db, terminal.defaultLocationId, product.id),
    isService: product.type === "SERVICE",
    priceChanged: false,
  };
}

function refreshAvailability(ctx: Ctx, sale: Sale, terminal: Terminal) {
  for (const line of sale.lines) {
    line.available = line.isService ? 999999 : availableAt(ctx.db, terminal.defaultLocationId, line.productId);
  }
}

/** Applies BOGO promotions and customer-group discounts as line-level discounts. */
function applyAutomaticDiscounts(ctx: Ctx, sale: Sale) {
  const { db } = ctx;
  const customer = sale.customerId ? db.customers.find((c) => c.id === sale.customerId) ?? null : null;
  const group = customer?.groupId ? db.customerGroups.find((g) => g.id === customer.groupId) : undefined;
  for (const line of sale.lines) {
    if (line.lineDiscount && line.lineDiscount.source === "MANUAL") continue;
    line.lineDiscount = null;
    const product = getProduct(db, line.productId);
    const promo = bestPromotion(db, product, sale.branchId, customer, ctx.now, line.unitPrice);
    if (promo?.type === "BOGO" && line.quantity >= 2) {
      const free = Math.floor(line.quantity / 2);
      line.lineDiscount = { type: "AMOUNT", value: round(free * line.unitPrice, 2), reason: promo.name, source: "PROMOTION", approvedBy: null };
      line.promotionName = promo.name;
    } else if (group && group.discountPct > 0 && line.priceSource !== "PROMOTION") {
      line.lineDiscount = { type: "PERCENT", value: group.discountPct, reason: `${group.name} discount`, source: "CUSTOMER", approvedBy: null };
    }
  }
  if (!sale.orderDiscount || sale.orderDiscount.source !== "MANUAL") {
    sale.orderDiscount = null;
    const coupon = sale.couponCode ? db.coupons.find((c) => c.code === sale.couponCode) : undefined;
    if (coupon) {
      sale.orderDiscount = coupon.discountPct
        ? { type: "PERCENT", value: coupon.discountPct, reason: `Coupon ${coupon.code}`, source: "COUPON", approvedBy: null }
        : { type: "AMOUNT", value: coupon.discountAmount, reason: `Coupon ${coupon.code}`, source: "COUPON", approvedBy: null };
    } else {
      const today = ctx.now.toISOString().slice(0, 10);
      const orderPromo = db.promotions
        .filter((p) => p.type === "ORDER" && p.status === "ACTIVE" && today >= p.startDate && today <= p.endDate && (!p.branchIds.length || p.branchIds.includes(sale.branchId)))
        .sort((a, b) => b.priority - a.priority)[0];
      if (orderPromo && sale.lines.length) {
        sale.orderDiscount = orderPromo.discountPct
          ? { type: "PERCENT", value: orderPromo.discountPct, reason: orderPromo.name, source: "PROMOTION", approvedBy: null }
          : { type: "AMOUNT", value: orderPromo.discountAmount, reason: orderPromo.name, source: "PROMOTION", approvedBy: null };
      }
    }
  }
}

function effectiveDiscountPct(base: number, type: AppliedDiscount["type"], value: number) {
  if (type === "PERCENT") return value;
  return base > 0 ? (value / base) * 100 : 100;
}

function repriceLines(ctx: Ctx, sale: Sale, flagChanges: boolean) {
  const { db } = ctx;
  const customer = sale.customerId ? db.customers.find((c) => c.id === sale.customerId) ?? null : null;
  sale.notices = [];
  for (const line of sale.lines) {
    if (line.overrideApprovedBy || line.priceSource === "OVERRIDE") continue;
    const product = getProduct(db, line.productId);
    const resolved = resolvePrice(db, product, line.unitId, sale.branchId, customer, ctx.now);
    if (flagChanges && resolved.price !== line.unitPrice) {
      sale.notices.push(`Price changed: ${line.nameEn} ${line.unitPrice.toFixed(2)} to ${resolved.price.toFixed(2)}`);
      line.priceChanged = true;
    }
    line.unitPrice = resolved.price;
    line.listPrice = resolved.price;
    line.priceSource = resolved.source;
    line.priceExplanation = resolved.explanation;
    line.promotionName = resolved.promotionName;
  }
}

export function applySaleOps(ctx: Ctx, sale: Sale, ops: SaleOp[], terminal: Terminal) {
  const { db } = ctx;
  const user = requireUser(ctx);
  if (sale.status !== "DRAFT" && sale.status !== "HELD" && sale.status !== "PENDING_PAYMENT") {
    badState("Only an open sale can be changed.");
  }
  const lineById = (id: string) => sale.lines.find((l) => l.id === id) ?? (notFound("Sale line") as never);
  for (const op of ops) {
    if (op.type !== "resume" && sale.status === "HELD") badState("Resume this sale before changing it.");
    switch (op.type) {
      case "add_barcode":
      case "add_product": {
        let product: Product;
        let unitId: string;
        let quantity = 1;
        if (op.type === "add_barcode") {
          const hit = db.products.flatMap((p) => p.barcodes.filter((b) => b.active && b.barcode === op.barcode).map((b) => ({ p, b })))[0];
          if (!hit) return fail(404, "BARCODE_NOT_FOUND", "Barcode not found — search by name.");
          product = hit.p;
          unitId = hit.b.unitId;
        } else {
          product = getProduct(db, op.productId);
          unitId = op.unitId ?? product.conversions.find((c) => c.isSalesDefault)?.unitId ?? product.baseUnitId;
          quantity = op.quantity ?? 1;
        }
        assertSellable(ctx, sale, product);
        const existing = sale.lines.find((l) => l.productId === product.id && l.unitId === unitId && l.priceSource !== "OVERRIDE");
        if (existing) {
          existing.quantity = round(existing.quantity + quantity, product.precision);
          existing.quantityBase = assertQuantity(product, existing.quantity, existing.factor);
          sale.lines.splice(sale.lines.indexOf(existing), 1);
          sale.lines.push(existing);
        } else {
          sale.lines.push(buildLine(ctx, sale, product, unitId, quantity, terminal));
        }
        break;
      }
      case "set_quantity": {
        const line = lineById(op.lineId);
        const product = getProduct(db, line.productId);
        line.quantityBase = assertQuantity(product, op.quantity, line.factor);
        line.quantity = op.quantity;
        break;
      }
      case "set_unit": {
        const line = lineById(op.lineId);
        const product = getProduct(db, line.productId);
        const replacement = buildLine(ctx, sale, product, op.unitId, line.quantity, terminal);
        sale.lines[sale.lines.indexOf(line)] = replacement;
        break;
      }
      case "remove_line":
        sale.lines = sale.lines.filter((l) => l.id !== op.lineId);
        break;
      case "line_discount": {
        const line = lineById(op.lineId);
        if (op.value <= 0) {
          line.lineDiscount = null;
          break;
        }
        if (!op.reason?.trim()) validation("reason", "A reason is required for discounts.");
        const base = line.unitPrice * line.quantity;
        const pct = effectiveDiscountPct(base, op.discountType, op.value);
        if (pct > 100) validation("value", "Discount cannot exceed the line amount.");
        let approvedBy: string | null = null;
        if (pct > ctx.limits.discountPct || !can(ctx, "pos.discount")) {
          const approval = consumeApproval(ctx, op.approvalToken, "DISCOUNT", user.id);
          if (!approval) return requireApproval("DISCOUNT", "Discount above your limit — manager approval required.");
          if (approval.amount + 1e-9 < pct) return requireApproval("DISCOUNT", "The approval does not cover this discount.");
          approvedBy = approval.approverName;
          audit(ctx, "DISCOUNT_ABOVE_LIMIT", "POS", "sale", sale.id, { after: { line: line.sku, pct: round(pct), approvedBy }, branchId: sale.branchId });
        }
        line.lineDiscount = { type: op.discountType, value: op.value, reason: op.reason, source: "MANUAL", approvedBy };
        break;
      }
      case "order_discount": {
        if (op.value <= 0) {
          sale.orderDiscount = null;
          break;
        }
        if (!op.reason?.trim()) validation("reason", "A reason is required for discounts.");
        const base = sale.lines.reduce((s, l) => s + l.unitPrice * l.quantity, 0);
        const pct = effectiveDiscountPct(base, op.discountType, op.value);
        if (pct > 100) validation("value", "Discount cannot exceed the sale amount.");
        let approvedBy: string | null = null;
        if (pct > ctx.limits.discountPct || !can(ctx, "pos.discount")) {
          const approval = consumeApproval(ctx, op.approvalToken, "DISCOUNT", user.id);
          if (!approval) return requireApproval("DISCOUNT", "Discount above your limit — manager approval required.");
          if (approval.amount + 1e-9 < pct) return requireApproval("DISCOUNT", "The approval does not cover this discount.");
          approvedBy = approval.approverName;
          audit(ctx, "DISCOUNT_ABOVE_LIMIT", "POS", "sale", sale.id, { after: { order: true, pct: round(pct), approvedBy }, branchId: sale.branchId });
        }
        sale.orderDiscount = { type: op.discountType, value: op.value, reason: op.reason, source: "MANUAL", approvedBy };
        break;
      }
      case "override_price": {
        const line = lineById(op.lineId);
        const product = getProduct(db, line.productId);
        if (op.price < 0) validation("price", "Price must not be negative.");
        if (!op.reason?.trim()) validation("reason", "A reason is required for price overrides.");
        const belowMin = product.minSellingPrice !== null && op.price < product.minSellingPrice * line.factor;
        const reduction = line.listPrice - op.price;
        let approvedBy: string | null = null;
        if (!can(ctx, "pos.override") || reduction > ctx.limits.overrideAmount || belowMin) {
          const approval = consumeApproval(ctx, op.approvalToken, "PRICE_OVERRIDE", user.id);
          if (!approval) return requireApproval("PRICE_OVERRIDE", belowMin ? "Below minimum selling price — manager approval required." : "Price override requires manager approval.");
          approvedBy = approval.approverName;
        }
        audit(ctx, "PRICE_OVERRIDE", "POS", "sale", sale.id, { before: { price: line.unitPrice }, after: { price: op.price, reason: op.reason, approvedBy }, branchId: sale.branchId });
        line.unitPrice = op.price;
        line.priceSource = "OVERRIDE";
        line.priceExplanation = `Manual override${approvedBy ? ` approved by ${approvedBy}` : ""}`;
        line.overrideApprovedBy = approvedBy ?? user.fullName;
        line.overrideReason = op.reason;
        break;
      }
      case "set_customer": {
        const customer = op.customerId ? db.customers.find((c) => c.id === op.customerId) ?? (notFound("Customer") as never) : null;
        sale.customerId = customer?.id ?? null;
        sale.customerName = customer?.name ?? null;
        repriceLines(ctx, sale, false);
        break;
      }
      case "apply_coupon": {
        if (!op.code) {
          sale.couponCode = null;
          break;
        }
        const coupon = db.coupons.find((c) => c.code.toUpperCase() === op.code?.toUpperCase() && c.status === "ACTIVE");
        const today = ctx.now.toISOString().slice(0, 10);
        if (!coupon || today < coupon.startDate || today > coupon.endDate) return validation("code", "This coupon is not valid.");
        if (coupon.usageCount >= coupon.usageLimit) return fail(422, "PROMO_LIMIT_REACHED", "This coupon has reached its usage limit.");
        const subtotal = sale.lines.reduce((s, l) => s + l.unitPrice * l.quantity, 0);
        if (subtotal < coupon.minSpend) return validation("code", `This coupon needs a minimum spend of ${coupon.minSpend.toFixed(2)} USD.`);
        sale.couponCode = coupon.code;
        break;
      }
      case "hold": {
        if (!sale.lines.length) validation("lines", "Add items before holding a sale.");
        if (sale.payments.some((p) => p.status === "PENDING" || p.status === "COMPLETED")) badState("A sale with payments cannot be held.");
        if (!can(ctx, "pos.hold")) fail(403, "FORBIDDEN", "You cannot hold sales.");
        sale.status = "HELD";
        sale.holdLabel = op.label.trim() || `Held ${ctx.now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
        break;
      }
      case "resume": {
        if (sale.status !== "HELD") badState("Only a held sale can be resumed.");
        sale.status = "DRAFT";
        sale.holdLabel = null;
        sale.terminalId = terminal.id;
        sale.terminalName = terminal.name;
        sale.sessionId = openSessionFor(db, terminal.id)?.id ?? null;
        repriceLines(ctx, sale, true);
        break;
      }
    }
  }
  applyAutomaticDiscounts(ctx, sale);
  refreshAvailability(ctx, sale, terminal);
  calculateTotals(db, sale);
  sale.version += 1;
  return sale;
}

export function addPayment(ctx: Ctx, sale: Sale, input: AddPaymentInput) {
  const { db } = ctx;
  if (sale.status !== "DRAFT" && sale.status !== "PENDING_PAYMENT") badState("Payments can only be added to an open sale.");
  if (!sale.lines.length) validation("lines", "Add items before taking payment.");
  const config = db.paymentMethods.find((m) => m.code === input.method && m.status === "ACTIVE");
  if (!config) return validation("method", "This payment method is not enabled.");
  if (!(input.amountTendered > 0)) validation("amountTendered", "Amount must be greater than zero.");
  calculateTotals(db, sale);
  if (sale.balance <= 0) badState("This sale is already fully paid.");
  const rate = currentRate(db);
  const session = openSessionFor(db, sale.terminalId);
  if (input.method === "CASH" && !session) return fail(422, "VALIDATION_ERROR", "Cash payment requires an open cashier session.");
  if (input.method === "CASH" && session && session.cashierId !== sale.cashierId) {
    return fail(422, "VALIDATION_ERROR", `This drawer is in ${session.cashierName}'s open session. Use your own terminal session.`);
  }
  if (config.requiresReference && !input.reference?.trim()) return validation("reference", `A reference is required for ${config.name}.`);
  if (input.reference) {
    const duplicate = db.sales.flatMap((s) => s.payments).find(
      (p) => p.provider === config.provider && p.reference === input.reference && p.status !== "FAILED" && p.status !== "CANCELLED",
    );
    if (duplicate) return fail(409, "DUPLICATE_PAYMENT_REFERENCE", "This payment reference has already been used.");
  }
  const tenderedBase = input.currency === "KHR" ? input.amountTendered / rate : input.amountTendered;
  let applied = round(Math.min(tenderedBase, sale.balance), 2);
  let changeAmount = 0;
  let roundingAmount = 0;
  const changeCurrency = input.changeCurrency ?? input.currency;

  if (input.method === "CASH") {
    if (input.currency === "KHR") {
      const dueKhr = roundKhr(db, sale.balance * rate);
      if (input.amountTendered >= dueKhr) {
        applied = sale.balance;
        roundingAmount = round(dueKhr - sale.balance * rate, 2);
      }
    }
    const changeBase = input.currency === "KHR"
      ? Math.max(0, input.amountTendered - roundKhr(db, sale.balance * rate)) / rate
      : Math.max(0, tenderedBase - sale.balance);
    if (changeBase > 0.0001) {
      changeAmount = changeCurrency === "KHR" ? roundKhr(db, changeBase * rate) : round(changeBase, 2);
    }
  } else if (tenderedBase > sale.balance + 0.005) {
    return validation("amountTendered", "A non-cash payment cannot exceed the balance due.");
  }
  if (input.method === "STORE_CREDIT") {
    const customer = db.customers.find((c) => c.id === sale.customerId);
    if (!customer) return validation("method", "Select a customer to use store credit.");
    if (customer.storeCredit < applied) return validation("amountTendered", `Store credit balance is ${customer.storeCredit.toFixed(2)} USD.`);
    customer.storeCredit = round(customer.storeCredit - applied, 2);
  }
  const pending = input.method === "QR";
  const payment: SalePayment = {
    id: uid("pay"),
    saleId: sale.id,
    sessionId: session?.id ?? null,
    terminalId: sale.terminalId,
    method: input.method,
    currency: input.currency,
    amountTendered: input.amountTendered,
    exchangeRate: input.currency === "KHR" ? rate : 1,
    amountApplied: applied,
    changeAmount,
    changeCurrency,
    roundingAmount,
    status: pending ? "PENDING" : "COMPLETED",
    provider: config.provider || null,
    reference: input.reference?.trim() || null,
    approvalCode: input.approvalCode?.trim() || null,
    cardLast4: input.cardLast4?.trim() || null,
    failureReason: null,
    refundedAmount: 0,
    createdAt: ctx.now.toISOString(),
    completedAt: pending ? null : ctx.now.toISOString(),
    reconciled: false,
  };
  sale.payments.push(payment);
  if (pending) sale.status = "PENDING_PAYMENT";
  calculateTotals(db, sale);
  sale.paymentStatus = derivePaymentStatus(sale);
  sale.version += 1;
  return sale;
}

export function resolvePendingPayment(ctx: Ctx, sale: Sale, paymentId: string, outcome: "COMPLETED" | "FAILED" | "CANCELLED", reference?: string, reason?: string) {
  const payment = sale.payments.find((p) => p.id === paymentId) ?? (notFound("Payment") as never);
  if (payment.status !== "PENDING") badState("Only a pending payment can be updated.");
  if (outcome === "COMPLETED") {
    if (!reference?.trim()) validation("reference", "Enter the verified provider reference.");
    const duplicate = ctx.db.sales.flatMap((s) => s.payments).find((p) => p.id !== payment.id && p.provider === payment.provider && p.reference === reference && p.status === "COMPLETED");
    if (duplicate) fail(409, "DUPLICATE_PAYMENT_REFERENCE", "This payment reference has already been used.");
    payment.reference = reference!.trim();
    payment.completedAt = ctx.now.toISOString();
  }
  payment.status = outcome;
  payment.failureReason = outcome === "COMPLETED" ? null : reason ?? (outcome === "FAILED" ? "Declined" : "Cancelled before confirmation");
  if (!sale.payments.some((p) => p.status === "PENDING") && sale.status === "PENDING_PAYMENT") sale.status = "DRAFT";
  calculateTotals(ctx.db, sale);
  sale.paymentStatus = derivePaymentStatus(sale);
  sale.version += 1;
  return sale;
}

/** Atomic finalization (SRS 11.9): re-validate, deduct stock, snapshot cost, assign the receipt number. */
export function finalizeSale(ctx: Ctx, sale: Sale, terminal: Terminal) {
  const { db } = ctx;
  if (sale.status === "FINALIZED") fail(409, "ALREADY_FINALIZED", "This sale has already been finalized.");
  if (sale.status !== "DRAFT" && sale.status !== "PENDING_PAYMENT") badState("This sale cannot be finalized.");
  if (!sale.lines.length || sale.lines.some((l) => !(l.quantity > 0))) validation("lines", "A sale needs at least one line with a positive quantity.");
  calculateTotals(db, sale);
  if (sale.payments.some((p) => p.status === "PENDING")) fail(422, "PAYMENT_INCOMPLETE", "Payment still pending — waiting for confirmation.");
  if (sale.balance > 0.005) fail(422, "PAYMENT_INCOMPLETE", `Balance of ${sale.balance.toFixed(2)} USD is still due.`);

  const sellingFrom = getLocation(db, terminal.defaultLocationId);
  if (db.counts.some((c) => c.warehouseId === sellingFrom.warehouseId && c.freeze && ["OPEN", "COUNTING", "REVIEW", "APPROVED"].includes(c.status))) {
    fail(409, "LOCATION_FROZEN", "Sales are blocked while this warehouse is frozen for a stocktake.");
  }
  const needed = new Map<string, number>();
  for (const line of sale.lines) {
    const product = getProduct(db, line.productId);
    assertSellable(ctx, sale, product);
    if (product.minSellingPrice !== null && line.unitPrice < product.minSellingPrice * line.factor && !line.overrideApprovedBy) {
      fail(422, "PRICE_BELOW_MINIMUM", `${product.nameEn} is below its minimum selling price.`);
    }
    if (!line.isService) needed.set(line.productId, (needed.get(line.productId) ?? 0) + line.quantityBase);
  }
  for (const [productId, qty] of needed) {
    const product = getProduct(db, productId);
    const available = availableAt(db, terminal.defaultLocationId, productId);
    if (qty > available + 1e-9 && !negativeAllowed(db, product)) {
      fail(422, "INSUFFICIENT_STOCK", `Only ${available} of ${product.nameEn} available at this counter.`, [
        { message: "insufficient", productId, requested: qty, available },
      ]);
    }
  }
  const receiptNo = nextDocNo(ctx, "RECEIPT", getBranch(db, sale.branchId).code);
  for (const line of sale.lines) {
    const product = getProduct(db, line.productId);
    const unitCost = product.avgCost ?? 0;
    line.unitCost = round(unitCost, 4);
    line.costTotal = line.isService ? 0 : round(unitCost * line.quantityBase, 4);
    if (line.isService) continue;
    consumeBatchesFefo(ctx, product, terminal.defaultLocationId, line.quantityBase);
    postMovement(ctx, {
      type: "SALE",
      productId: line.productId,
      fromLocationId: terminal.defaultLocationId,
      quantityBase: line.quantityBase,
      unitCode: line.unitCode,
      quantityEntered: line.quantity,
      unitCost,
      sourceType: "SALE",
      sourceId: sale.id,
      sourceNo: receiptNo,
    });
  }
  sale.receiptNo = receiptNo;
  sale.status = "FINALIZED";
  sale.finalizedAt = ctx.now.toISOString();
  sale.businessDate = businessDate(db, sale.branchId, ctx.now);
  sale.sessionId = openSessionFor(db, terminal.id)?.id ?? sale.sessionId;
  sale.paymentStatus = derivePaymentStatus(sale);

  if (sale.couponCode) {
    const coupon = db.coupons.find((c) => c.code === sale.couponCode);
    if (coupon) coupon.usageCount += 1;
  }
  const promoNames = new Set(sale.lines.map((l) => l.promotionName).filter(Boolean));
  db.promotions.filter((p) => promoNames.has(p.name)).forEach((p) => (p.usageCount += 1));

  const customer = sale.customerId ? db.customers.find((c) => c.id === sale.customerId) : undefined;
  if (customer) {
    customer.lastPurchaseAt = sale.finalizedAt;
    customer.totalSpent = round(customer.totalSpent + sale.grandTotal, 2);
    if (db.settings.loyaltyEnabled) {
      sale.loyaltyEarned = Math.floor(sale.grandTotal * db.settings.loyaltyPointsPerUsd);
      customer.loyaltyPoints += sale.loyaltyEarned;
      customer.tier = customer.loyaltyPoints >= 2000 ? "Gold" : customer.loyaltyPoints >= 500 ? "Silver" : "Member";
    }
  }
  sale.version += 1;
  return sale;
}

export function cancelSale(ctx: Ctx, sale: Sale, reason: string, approvalToken?: string) {
  const user = requireUser(ctx);
  if (!["DRAFT", "HELD", "PENDING_PAYMENT"].includes(sale.status)) badState("Only a sale that has not been finalized can be cancelled.");
  if (sale.payments.some((p) => p.status === "COMPLETED" && p.method !== "CASH")) badState("Refund completed electronic payments before cancelling.");
  if (sale.lines.length) {
    if (!can(ctx, "pos.cancel")) {
      const approval = consumeApproval(ctx, approvalToken, "CANCEL_SALE", user.id);
      if (!approval) return requireApproval("CANCEL_SALE", "Cancelling a sale with items requires manager approval.");
      audit(ctx, "SALE_CANCELLED", "POS", "sale", sale.id, { after: { reason, approvedBy: approval.approverName, value: sale.grandTotal }, branchId: sale.branchId });
    } else {
      audit(ctx, "SALE_CANCELLED", "POS", "sale", sale.id, { after: { reason, value: sale.grandTotal }, branchId: sale.branchId });
    }
  }
  sale.status = "CANCELLED";
  sale.cancelReason = reason || "Cancelled";
  sale.payments.filter((p) => p.status === "PENDING").forEach((p) => {
    p.status = "CANCELLED";
    p.failureReason = "Sale cancelled";
  });
  return sale;
}

export function voidSale(ctx: Ctx, sale: Sale, reason: string, approvalToken?: string) {
  const { db } = ctx;
  const user = requireUser(ctx);
  if (sale.status !== "FINALIZED") return badState("Only a finalized sale can be voided.");
  const session = db.cashSessions.find((s) => s.id === sale.sessionId);
  if (!session || session.status !== "OPEN") return badState("A sale can only be voided within the same open session. Use a return instead.");
  if (sale.returnIds.length) return badState("This sale has returns and cannot be voided.");
  if (!reason?.trim()) validation("reason", "A reason is required to void a sale.");
  const approval = consumeApproval(ctx, approvalToken, "VOID_SALE", user.id);
  if (!approval) return requireApproval("VOID_SALE", "Voiding a finalized sale requires approval by a different user.");
  const terminal = getTerminal(db, sale.terminalId);
  for (const line of sale.lines) {
    if (line.isService) continue;
    postMovement(ctx, {
      type: "SALE_VOID",
      productId: line.productId,
      toLocationId: terminal.defaultLocationId,
      quantityBase: line.quantityBase,
      unitCode: line.unitCode,
      quantityEntered: line.quantity,
      unitCost: line.unitCost ?? 0,
      sourceType: "SALE",
      sourceId: sale.id,
      sourceNo: sale.receiptNo ?? sale.id,
      reasonCode: reason,
      approvedBy: approval.approverName,
    });
  }
  sale.payments.forEach((p) => {
    if (p.status === "COMPLETED") {
      p.status = "REFUNDED";
      p.refundedAmount = p.amountApplied;
    }
  });
  sale.status = "VOIDED";
  sale.voidReason = reason;
  sale.voidedBy = approval.approverName;
  sale.refundedTotal = sale.grandTotal;
  sale.paymentStatus = "REFUNDED";
  audit(ctx, "SALE_VOIDED", "SALES", "sale", sale.id, { after: { reason, approvedBy: approval.approverName, receiptNo: sale.receiptNo }, branchId: sale.branchId });
  return sale;
}

export function quoteReturn(ctx: Ctx, sale: Sale, input: Pick<CreateReturnInput, "lines" | "refundMethod" | "replacementLines">): ReturnQuote {
  const { db } = ctx;
  if (sale.status !== "FINALIZED") badState("Only a finalized sale can be returned.");
  const windowDays = db.settings.returnWindowDays;
  const days = (ctx.now.getTime() - new Date(sale.finalizedAt ?? sale.createdAt).getTime()) / 86_400_000;
  const reasons: string[] = [];
  let windowExpired = false;
  const quoted = input.lines.filter((l) => l.quantity > 0).map((entry) => {
    const line = sale.lines.find((l) => l.id === entry.saleLineId) ?? (notFound("Sale line") as never);
    const remaining = round(line.quantity - line.returnedQuantity, 4);
    if (entry.quantity > remaining) {
      fail(422, "RETURN_QUANTITY_EXCEEDED", `Only ${remaining} unit${remaining === 1 ? "" : "s"} remains returnable on ${line.nameEn}.`);
    }
    if (!line.allowFraction && !Number.isInteger(entry.quantity * line.factor)) fail(422, "INVALID_QUANTITY_FOR_UNIT", "Quantity is not valid for this unit.");
    const product = getProduct(db, line.productId);
    const category = db.categories.find((c) => c.id === product.categoryId);
    const lineWindow = category?.returnWindowDays ?? windowDays;
    if (days > lineWindow) windowExpired = true;
    if (category && !category.returnable) reasons.push(`${category.nameEn} items are not returnable`);
    if (entry.condition === "NON_RETURNABLE") reasons.push(`${line.nameEn} marked non-returnable`);
    const ratio = entry.quantity / line.quantity;
    const net = (line.grossAmount - line.discountAmount - line.orderDiscountShare) * ratio;
    const tax = line.taxAmount * ratio;
    return { saleLineId: line.id, quantity: entry.quantity, netAmount: round(net, 2), taxAmount: round(tax, 2), refundAmount: round(line.lineTotal * ratio, 2) };
  });
  if (!quoted.length) validation("lines", "Select at least one item to return.");
  const refundTotal = round(quoted.reduce((s, l) => s + l.refundAmount, 0), 2);
  if (windowExpired) reasons.push("Return window expired");
  if (refundTotal > ctx.limits.refundAmount) reasons.push("Refund above your limit");
  if (input.refundMethod === "CASH" && refundTotal > db.settings.refundCashApprovalThreshold) reasons.push("Cash refund above threshold");
  let replacementTotal = 0;
  if (input.replacementLines?.length) {
    const taxInclusive = db.settings.taxInclusive;
    for (const r of input.replacementLines) {
      const product = getProduct(db, r.productId);
      const unitId = r.unitId ?? product.baseUnitId;
      const price = resolvePrice(db, product, unitId, sale.branchId, null, ctx.now).price;
      const rate = db.taxCodes.find((t) => t.id === product.taxCodeId)?.rate ?? 0;
      replacementTotal += taxInclusive ? price * r.quantity : price * r.quantity * (1 + rate / 100);
    }
    replacementTotal = round(replacementTotal, 2);
  }
  return {
    refundTotal,
    netTotal: round(quoted.reduce((s, l) => s + l.netAmount, 0), 2),
    taxTotal: round(quoted.reduce((s, l) => s + l.taxAmount, 0), 2),
    lines: quoted,
    windowExpired,
    approvalReasons: [...new Set(reasons)],
    replacementTotal,
    difference: round(replacementTotal - refundTotal, 2),
  };
}

export function createReturn(ctx: Ctx, sale: Sale, input: CreateReturnInput): SalesReturn {
  const { db } = ctx;
  const user = requireUser(ctx);
  if (input.lines.some((l) => l.quantity > 0 && (!l.reason?.trim() || !l.condition))) validation("lines", "Reason and condition are required per line.");
  const quote = quoteReturn(ctx, sale, input);
  let approvedBy: string | null = null;
  const canSelfApprove = can(ctx, "returns.approve") && quote.refundTotal <= ctx.limits.refundAmount && !quote.windowExpired;
  if (quote.approvalReasons.length && !canSelfApprove) {
    const approval = consumeApproval(ctx, input.approvalToken, "REFUND", user.id);
    if (!approval) {
      notify(ctx, "REFUND_APPROVAL", "Refund approval requested", `${user.fullName} requested approval on ${sale.receiptNo}: ${quote.approvalReasons.join("; ")}`, { link: "/sales/returns", permission: "returns.approve", branchId: sale.branchId });
      return requireApproval("REFUND", `${quote.approvalReasons[0]} — approval required.`);
    }
    approvedBy = approval.approverName;
  }
  const terminal = getTerminal(db, ctx.terminalId ?? sale.terminalId);
  const session = openSessionFor(db, terminal.id);
  const isExchange = Boolean(input.replacementLines?.length);
  if (input.refundMethod === "CASH" && !session && !isExchange) fail(422, "VALIDATION_ERROR", "Cash refund requires an open cashier session.");

  const location = getLocation(db, terminal.defaultLocationId);
  const returnNo = nextDocNo(ctx, "RETURN", getBranch(db, sale.branchId).code);
  const returnId = uid("ret");
  const lines: SalesReturnLine[] = quote.lines.map((q) => {
    const entry = input.lines.find((l) => l.saleLineId === q.saleLineId)!;
    const line = sale.lines.find((l) => l.id === q.saleLineId)!;
    const destinationType = entry.condition === "RESALABLE" ? "SELLABLE" : entry.condition === "EXPIRED" ? "EXPIRED" : entry.condition === "DAMAGED" ? "DAMAGED" : "RETURNS";
    const destination = entry.condition === "RESALABLE" ? location : locationByType(db, location.warehouseId, destinationType) ?? location;
    const baseQty = round(q.quantity * line.factor, 4);
    if (!line.isService) {
      const product = getProduct(db, line.productId);
      if (entry.condition === "RESALABLE") applyWac(db, product, baseQty, line.unitCost ?? 0);
      postMovement(ctx, {
        type: "SALE_RETURN",
        productId: line.productId,
        toLocationId: destination.id,
        quantityBase: baseQty,
        unitCode: line.unitCode,
        quantityEntered: q.quantity,
        unitCost: line.unitCost ?? 0,
        sourceType: "RETURN",
        sourceId: returnId,
        sourceNo: returnNo,
        reasonCode: entry.reason,
        approvedBy,
      });
    }
    line.returnedQuantity = round(line.returnedQuantity + q.quantity, 4);
    return {
      saleLineId: line.id,
      productId: line.productId,
      sku: line.sku,
      name: line.nameEn,
      quantity: q.quantity,
      condition: entry.condition,
      reason: entry.reason,
      netAmount: q.netAmount,
      taxAmount: q.taxAmount,
      refundAmount: q.refundAmount,
      unitCost: line.unitCost,
      destinationLocationId: destination.id,
    };
  });

  let exchangeSaleId: string | null = null;
  let differencePaid = 0;
  let cashOutToCustomer = quote.refundTotal;
  let appliedToExchange = 0;
  if (isExchange) {
    const newSale = createDraftSale(ctx, terminal, sale.customerId);
    applySaleOps(ctx, newSale, (input.replacementLines ?? []).map((r) => ({ type: "add_product" as const, productId: r.productId, unitId: r.unitId, quantity: r.quantity })), terminal);
    appliedToExchange = Math.min(quote.refundTotal, newSale.grandTotal);
    if (appliedToExchange > 0) {
      newSale.payments.push({
        id: uid("pay"), saleId: newSale.id, sessionId: session?.id ?? null, terminalId: terminal.id, method: "STORE_CREDIT", currency: "USD",
        amountTendered: appliedToExchange, exchangeRate: 1, amountApplied: appliedToExchange, changeAmount: 0, changeCurrency: "USD", roundingAmount: 0,
        status: "COMPLETED", provider: null, reference: returnNo, approvalCode: null, cardLast4: null, failureReason: null, refundedAmount: 0,
        createdAt: ctx.now.toISOString(), completedAt: ctx.now.toISOString(), reconciled: true,
      });
      calculateTotals(db, newSale);
    }
    const difference = round(newSale.balance, 2);
    if (difference > 0) {
      const settlement = input.settlementMethod ?? "CASH";
      addPayment(ctx, newSale, { method: settlement, currency: "USD", amountTendered: difference, reference: input.settlementReference });
      differencePaid = difference;
    }
    finalizeSale(ctx, newSale, terminal);
    exchangeSaleId = newSale.id;
    cashOutToCustomer = round(quote.refundTotal - appliedToExchange, 2);
  }

  const refundIsElectronic = input.refundMethod !== "CASH" && input.refundMethod !== "STORE_CREDIT";
  const pending = refundIsElectronic && cashOutToCustomer > 0 && !input.reference?.trim();
  const original = sale.payments.find((p) => p.method === input.refundMethod && p.status !== "REFUNDED");
  const bd = businessDate(db, sale.branchId, ctx.now);
  const pushRefund = (method: SalesReturn["refundMethod"], amount: number, status: "PENDING" | "COMPLETED", reference: string | null) => {
    if (amount <= 0) return;
    db.refunds.unshift({ id: uid("rfd"), returnId, salePaymentId: original?.id ?? null, method, amount, currency: "USD", status, reference, sessionId: session?.id ?? null, createdAt: ctx.now.toISOString(), businessDate: bd });
  };
  if (appliedToExchange > 0) pushRefund("STORE_CREDIT", appliedToExchange, "COMPLETED", returnNo);
  pushRefund(input.refundMethod, cashOutToCustomer, pending ? "PENDING" : "COMPLETED", input.reference?.trim() || null);
  if (input.refundMethod === "STORE_CREDIT" && !isExchange) {
    const customer = db.customers.find((c) => c.id === sale.customerId);
    if (!customer) validation("refundMethod", "Store credit needs a customer on the original sale.");
    customer!.storeCredit = round(customer!.storeCredit + cashOutToCustomer, 2);
  }
  if (original) {
    original.refundedAmount = round(original.refundedAmount + quote.refundTotal, 2);
    original.status = original.refundedAmount >= original.amountApplied - 0.005 ? "REFUNDED" : "PARTIALLY_REFUNDED";
  }
  sale.refundedTotal = round(sale.refundedTotal + quote.refundTotal, 2);
  sale.paymentStatus = derivePaymentStatus(sale);
  sale.returnIds.push(returnId);
  const customer = sale.customerId ? db.customers.find((c) => c.id === sale.customerId) : undefined;
  if (customer && sale.loyaltyEarned > 0 && sale.grandTotal > 0) {
    const pts = Math.floor(sale.loyaltyEarned * (quote.refundTotal / sale.grandTotal));
    customer.loyaltyPoints = Math.max(0, customer.loyaltyPoints - pts);
  }
  const record: SalesReturn = {
    id: returnId,
    returnNo,
    originalSaleId: sale.id,
    originalReceiptNo: sale.receiptNo ?? "",
    branchId: sale.branchId,
    branchName: sale.branchName,
    terminalId: terminal.id,
    sessionId: session?.id ?? null,
    customerName: sale.customerName,
    type: isExchange ? "EXCHANGE" : "RETURN",
    lines,
    refundMethod: input.refundMethod,
    refundTotal: quote.refundTotal,
    netTotal: quote.netTotal,
    taxTotal: quote.taxTotal,
    refundStatus: pending ? "PENDING" : "COMPLETED",
    reference: input.reference?.trim() || null,
    exchangeSaleId,
    differencePaid,
    createdBy: user.fullName,
    approvedBy,
    overrideWindow: quote.windowExpired,
    createdAt: ctx.now.toISOString(),
    businessDate: bd,
  };
  db.returns.unshift(record);
  audit(ctx, isExchange ? "EXCHANGE_COMPLETED" : "REFUND_COMPLETED", "RETURNS", "return", returnId, { after: { returnNo, receiptNo: sale.receiptNo, amount: quote.refundTotal, method: input.refundMethod, approvedBy }, branchId: sale.branchId });
  return record;
}
