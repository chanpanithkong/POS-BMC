import type {
  AddPaymentInput, CashMovement, CashMovementKind, CashSession, CreateReturnInput, Currency, CurrencyAmounts, Sale, SaleOp, SessionSummary,
} from "@/types";
import {
  allowedBranchIds, assertBranch, audit, badState, branchFilter, can, consumeApproval, fail, list, nextDocNo, notFound, notify, positive, requireApproval,
  requirePerm, requireUser, round, uid, validation, type Ctx,
} from "../core";
import {
  addPayment, applySaleOps, cancelSale, createDraftSale, createReturn, finalizeSale, getSale, getTerminal, openSessionFor, quoteReturn, resolvePendingPayment, voidSale,
} from "../domain/sales";
import { GET, PATCH, POST } from "../registry";
import type { MockDb } from "../db";

const terminalOf = (ctx: Ctx, sale?: Sale) => getTerminal(ctx.db, ctx.terminalId ?? sale?.terminalId);

function scopedSale(ctx: Ctx, id: string) {
  const sale = getSale(ctx.db, id);
  assertBranch(ctx, sale.branchId);
  if (!can(ctx, "sales.view_all") && sale.cashierId !== ctx.user?.id && sale.status === "FINALIZED") notFound("Sale");
  return sale;
}

POST("/sales", (ctx) => {
  requirePerm(ctx, "pos.sell", "pos.hold");
  const { customerId } = (ctx.body ?? {}) as { customerId?: string };
  const terminal = terminalOf(ctx);
  assertBranch(ctx, terminal.branchId);
  return createDraftSale(ctx, terminal, customerId ?? null);
});

GET("/sales", (ctx) => {
  requirePerm(ctx, "sales.view");
  const inBranch = branchFilter(ctx);
  const all = can(ctx, "sales.view_all");
  const statuses = ctx.query.status ? String(ctx.query.status).split(",") : ["FINALIZED", "VOIDED", "CANCELLED"];
  return list(
    ctx.db.sales.filter(
      (s) => statuses.includes(s.status) && inBranch(s.branchId) && (all || s.cashierId === ctx.user?.id) && (!ctx.query.customerId || s.customerId === ctx.query.customerId) && (!ctx.query.terminalId || s.terminalId === ctx.query.terminalId),
    ),
  );
});

/** Restores the open draft after a refresh or crash (NFR-REL-003). */
GET("/sales/current", (ctx) => {
  requirePerm(ctx, "pos.sell", "pos.hold");
  const terminal = terminalOf(ctx);
  return ctx.db.sales.find((s) => s.terminalId === terminal.id && s.cashierId === ctx.user?.id && (s.status === "DRAFT" || s.status === "PENDING_PAYMENT")) ?? null;
});

GET("/sales/held", (ctx) => {
  requirePerm(ctx, "pos.sell", "pos.hold", "sales.view");
  const inBranch = branchFilter(ctx);
  return list(ctx.db.sales.filter((s) => s.status === "HELD" && inBranch(s.branchId)));
});

GET("/sales/:id", (ctx) => {
  requirePerm(ctx, "sales.view", "pos.sell", "pos.hold");
  return scopedSale(ctx, ctx.params.id);
});

PATCH("/sales/:id", (ctx) => {
  requirePerm(ctx, "pos.sell", "pos.hold");
  const sale = getSale(ctx.db, ctx.params.id);
  assertBranch(ctx, sale.branchId);
  const { ops, version } = ctx.body as { ops: SaleOp[]; version?: number };
  if (version !== undefined && version !== sale.version) fail(409, "VERSION_CONFLICT", "This sale changed on another screen. Reloading it.");
  return applySaleOps(ctx, sale, ops, terminalOf(ctx, sale));
});

POST("/sales/:id/finalize", (ctx) => {
  requirePerm(ctx, "pos.sell");
  const sale = getSale(ctx.db, ctx.params.id);
  assertBranch(ctx, sale.branchId);
  const terminal = terminalOf(ctx, sale);
  const { cashPayment } = (ctx.body ?? {}) as { cashPayment?: AddPaymentInput };
  if (cashPayment) addPayment(ctx, sale, { ...cashPayment, method: "CASH" });
  finalizeSale(ctx, sale, terminal);
  audit(ctx, "SALE_FINALIZED", "POS", "sale", sale.id, { after: { receiptNo: sale.receiptNo, total: sale.grandTotal }, branchId: sale.branchId });
  return sale;
});

POST("/sales/:id/cancel", (ctx) => {
  requirePerm(ctx, "pos.sell", "pos.hold");
  const { reason, approvalToken } = ctx.body as { reason: string; approvalToken?: string };
  return cancelSale(ctx, getSale(ctx.db, ctx.params.id), reason, approvalToken);
});

POST("/sales/:id/void", (ctx) => {
  requirePerm(ctx, "pos.sell", "sales.void");
  const { reason, approvalToken } = ctx.body as { reason: string; approvalToken?: string };
  return voidSale(ctx, scopedSale(ctx, ctx.params.id), reason, approvalToken);
});

GET("/sales/:id/payments", (ctx) => {
  requirePerm(ctx, "sales.view", "pos.sell");
  return list(scopedSale(ctx, ctx.params.id).payments);
});

POST("/sales/:id/payments", (ctx) => {
  requirePerm(ctx, "pos.sell");
  return addPayment(ctx, getSale(ctx.db, ctx.params.id), ctx.body as AddPaymentInput);
});

POST("/sales/:id/payments/:paymentId/resolve", (ctx) => {
  requirePerm(ctx, "pos.sell");
  const { outcome, reference, reason } = ctx.body as { outcome: "COMPLETED" | "FAILED" | "CANCELLED"; reference?: string; reason?: string };
  return resolvePendingPayment(ctx, getSale(ctx.db, ctx.params.id), ctx.params.paymentId, outcome, reference, reason);
});

POST("/sales/:id/returns/quote", (ctx) => {
  requirePerm(ctx, "returns.create");
  return quoteReturn(ctx, scopedSale(ctx, ctx.params.id), ctx.body as CreateReturnInput);
});

POST("/sales/:id/returns", (ctx) => {
  requirePerm(ctx, "returns.create");
  return createReturn(ctx, scopedSale(ctx, ctx.params.id), ctx.body as CreateReturnInput);
});

POST("/sales/:id/reprint", (ctx) => {
  requirePerm(ctx, "sales.view", "pos.sell");
  const sale = scopedSale(ctx, ctx.params.id);
  if (sale.status !== "FINALIZED" && sale.status !== "VOIDED") return badState("Only a finalized sale has a receipt.");
  sale.reprintCount += 1;
  audit(ctx, "RECEIPT_REPRINT", "DOC", "sale", sale.id, { after: { receiptNo: sale.receiptNo, reprint: sale.reprintCount }, branchId: sale.branchId, flagged: sale.reprintCount > 1 });
  return sale;
});

POST("/sales/:id/invoice", (ctx) => {
  requirePerm(ctx, "sales.view", "pos.sell");
  const sale = scopedSale(ctx, ctx.params.id);
  if (sale.status !== "FINALIZED") return badState("Invoices can only be issued for finalized sales.");
  if (!sale.invoiceNo) sale.invoiceNo = nextDocNo(ctx, "INVOICE", ctx.db.branches.find((b) => b.id === sale.branchId)?.code);
  audit(ctx, "INVOICE_ISSUED", "DOC", "sale", sale.id, { after: { invoiceNo: sale.invoiceNo }, branchId: sale.branchId });
  return sale;
});

POST("/sales/:id/fulfilment", (ctx) => {
  requirePerm(ctx, "pos.sell");
  const sale = scopedSale(ctx, ctx.params.id);
  sale.fulfilmentStatus = (ctx.body as { status: Sale["fulfilmentStatus"] }).status;
  return sale;
});

GET("/returns", (ctx) => {
  requirePerm(ctx, "sales.view", "returns.create");
  const inBranch = branchFilter(ctx);
  return list(ctx.db.returns.filter((r) => inBranch(r.branchId)));
});

GET("/refunds", (ctx) => {
  requirePerm(ctx, "sales.view");
  return list(ctx.db.refunds);
});

POST("/returns/:id/confirm-refund", (ctx) => {
  requirePerm(ctx, "returns.create", "returns.approve");
  const record = ctx.db.returns.find((r) => r.id === ctx.params.id);
  if (!record) return notFound("Return");
  const { reference } = ctx.body as { reference: string };
  if (!reference?.trim()) return validation("reference", "Enter the provider or bank reference.");
  if (record.refundStatus !== "PENDING") return badState("This refund is not pending.");
  record.refundStatus = "COMPLETED";
  record.reference = reference.trim();
  ctx.db.refunds.filter((r) => r.returnId === record.id && r.status === "PENDING").forEach((r) => {
    r.status = "COMPLETED";
    r.reference = reference.trim();
  });
  audit(ctx, "REFUND_CONFIRMED", "RETURNS", "return", record.id, { after: { reference }, branchId: record.branchId });
  return record;
});

GET("/payments", (ctx) => {
  requirePerm(ctx, "reports.cash", "cash.session.view_all");
  const inBranch = branchFilter(ctx);
  return list(ctx.db.sales.filter((s) => s.status === "FINALIZED" && inBranch(s.branchId)).flatMap((s) => s.payments.map((p) => ({ ...p, receiptNo: s.receiptNo, branchName: s.branchName, businessDate: s.businessDate }))));
});

POST("/payments/:id/reconcile", (ctx) => {
  requirePerm(ctx, "cash.session.approve", "reports.cash");
  const payment = ctx.db.sales.flatMap((s) => s.payments).find((p) => p.id === ctx.params.id);
  if (!payment) return notFound("Payment");
  payment.reconciled = (ctx.body as { reconciled: boolean }).reconciled;
  audit(ctx, "PAYMENT_RECONCILED", "PAY", "payment", payment.id, { after: { reconciled: payment.reconciled } });
  return payment;
});

// Cashier sessions
const zero = (): CurrencyAmounts => ({ USD: 0, KHR: 0 });

export function sessionFigures(db: MockDb, session: CashSession) {
  const cashSales = zero();
  const nonCash: Record<string, number> = {};
  let salesCount = 0;
  let salesTotal = 0;
  let pending = 0;
  for (const sale of db.sales) {
    if (sale.sessionId !== session.id) continue;
    if (sale.status === "PENDING_PAYMENT") pending += sale.payments.filter((p) => p.status === "PENDING").length;
    if (sale.status !== "FINALIZED") continue;
    salesCount += 1;
    salesTotal += sale.grandTotal;
    for (const p of sale.payments) {
      if (p.status === "FAILED" || p.status === "CANCELLED" || p.status === "PENDING") continue;
      if (p.method === "CASH") {
        cashSales[p.currency] = round(cashSales[p.currency] + p.amountTendered, 2);
        cashSales[p.changeCurrency] = round(cashSales[p.changeCurrency] - p.changeAmount, 2);
      } else {
        nonCash[p.method] = round((nonCash[p.method] ?? 0) + p.amountApplied, 2);
      }
    }
  }
  const cashRefunds = zero();
  db.refunds.filter((r) => r.sessionId === session.id && r.status === "COMPLETED").forEach((r) => {
    if (r.method === "CASH") cashRefunds[r.currency] = round(cashRefunds[r.currency] + r.amount, 2);
    else nonCash[`${r.method}_REFUND`] = round((nonCash[`${r.method}_REFUND`] ?? 0) + r.amount, 2);
  });
  const movements = db.cashMovements.filter((m) => m.sessionId === session.id);
  const totals: Record<CashMovementKind, CurrencyAmounts> = { CASH_IN: zero(), CASH_OUT: zero(), PAID_OUT: zero(), DROP: zero() };
  movements.forEach((m) => (totals[m.kind][m.currency] = round(totals[m.kind][m.currency] + m.amount, 2)));
  const expected = zero();
  (["USD", "KHR"] as Currency[]).forEach((c) => {
    expected[c] = round(session.opening[c] + cashSales[c] + totals.CASH_IN[c] - cashRefunds[c] - totals.CASH_OUT[c] - totals.PAID_OUT[c] - totals.DROP[c], 2);
  });
  return { cashSales, cashRefunds, totals, expected, nonCash, movements, salesCount, salesTotal: round(salesTotal, 2), pending };
}

function getSession(ctx: Ctx, id: string) {
  const session = ctx.db.cashSessions.find((s) => s.id === id);
  if (!session) return notFound("Session") as never;
  assertBranch(ctx, session.branchId);
  return session;
}

function canViewExpected(ctx: Ctx, session: CashSession) {
  return can(ctx, "cash.session.view_all") || session.counted !== null;
}

function sessionView(ctx: Ctx, session: CashSession): CashSession {
  return canViewExpected(ctx, session) ? session : { ...session, expected: null, variance: null };
}

GET("/cashier-sessions", (ctx) => {
  requirePerm(ctx, "cash.session.view", "cash.session.view_all");
  const inBranch = branchFilter(ctx);
  const all = can(ctx, "cash.session.view_all");
  return list(ctx.db.cashSessions.filter((s) => inBranch(s.branchId) && (all || s.cashierId === ctx.user?.id)).map((s) => sessionView(ctx, s)));
});

GET("/cashier-sessions/current", (ctx) => {
  requirePerm(ctx, "cash.session.view", "pos.sell");
  const terminal = terminalOf(ctx);
  const session = openSessionFor(ctx.db, terminal.id);
  return session ? sessionView(ctx, session) : null;
});

POST("/cashier-sessions/open", (ctx) => {
  requirePerm(ctx, "cash.session.open");
  const user = requireUser(ctx);
  const terminal = terminalOf(ctx);
  assertBranch(ctx, terminal.branchId);
  const { opening, witness } = ctx.body as { opening: CurrencyAmounts; witness?: string };
  if (opening.USD < 0 || opening.KHR < 0) return validation("opening", "Amounts must not be negative.");
  if (terminal.assignedCashierIds.length && !terminal.assignedCashierIds.includes(user.id) && !can(ctx, "cash.session.approve")) {
    return fail(403, "FORBIDDEN", "You are not assigned to this terminal.");
  }
  if (openSessionFor(ctx.db, terminal.id)) return fail(409, "SESSION_ALREADY_OPEN", "This terminal already has an open session.");
  if (ctx.db.cashSessions.some((s) => s.cashierId === user.id && s.status === "OPEN")) return fail(409, "SESSION_ALREADY_OPEN", "You already have an open session on another terminal.");
  const session: CashSession = {
    id: uid("cs"),
    sessionNo: `S-${String(ctx.db.cashSessions.length + 1).padStart(4, "0")}`,
    terminalId: terminal.id,
    terminalName: terminal.name,
    branchId: terminal.branchId,
    cashierId: user.id,
    cashierName: user.fullName,
    status: "OPEN",
    openedAt: ctx.now.toISOString(),
    closedAt: null,
    opening,
    witness: witness || null,
    counted: null,
    denominations: null,
    expected: null,
    variance: null,
    varianceReason: null,
    reviewedBy: null,
    needsApproval: false,
  };
  ctx.db.cashSessions.unshift(session);
  ctx.db.sales.filter((s) => s.terminalId === terminal.id && s.status === "DRAFT").forEach((s) => (s.sessionId = session.id));
  audit(ctx, "SESSION_OPENED", "CSH", "session", session.id, { after: { opening }, branchId: terminal.branchId });
  return session;
});

GET("/cashier-sessions/:id/summary", (ctx): SessionSummary => {
  requirePerm(ctx, "cash.session.view", "cash.session.view_all");
  const session = getSession(ctx, ctx.params.id);
  if (!can(ctx, "cash.session.view_all") && session.cashierId !== ctx.user?.id) return notFound("Session") as never;
  const f = sessionFigures(ctx.db, session);
  const visible = canViewExpected(ctx, session);
  return {
    session: sessionView(ctx, session),
    movements: f.movements,
    cashSales: visible ? f.cashSales : null,
    cashRefunds: visible ? f.cashRefunds : null,
    movementTotals: visible ? f.totals : null,
    nonCashTotals: f.nonCash,
    salesCount: f.salesCount,
    salesTotal: f.salesTotal,
    pendingPayments: f.pending,
  };
});

POST("/cashier-sessions/:id/movements", (ctx) => {
  requirePerm(ctx, "cash.session.open", "cash.session.approve");
  const user = requireUser(ctx);
  const session = getSession(ctx, ctx.params.id);
  if (session.status !== "OPEN") return badState("Cash movements need an open session.");
  const input = ctx.body as { kind: CashMovementKind; currency: Currency; amount: number; reason: string; witness?: string; approvalToken?: string; expenseCategoryId?: string };
  positive(input.amount, "amount", "Amount");
  if (!input.reason?.trim()) return validation("reason", "A reason is required.");
  const base = input.currency === "KHR" ? input.amount / (ctx.db.exchangeRates[0]?.rate ?? 4100) : input.amount;
  let approvedBy: string | null = null;
  if (base > ctx.db.settings.cashMovementApprovalThreshold && input.kind !== "DROP" && !can(ctx, "cash.session.approve")) {
    const approval = consumeApproval(ctx, input.approvalToken, "CASH_MOVEMENT", user.id);
    if (!approval) return requireApproval("CASH_MOVEMENT", "This amount is above the threshold — manager approval required.");
    approvedBy = approval.approverName;
  }
  const movement: CashMovement = {
    id: uid("cm"), sessionId: session.id, kind: input.kind, currency: input.currency, amount: input.amount, reason: input.reason.trim(),
    witness: input.witness || null, approvedBy, expenseId: null, at: ctx.now.toISOString(), by: user.fullName,
  };
  if (input.kind === "PAID_OUT" && input.expenseCategoryId) {
    const category = ctx.db.expenseCategories.find((c) => c.id === input.expenseCategoryId);
    const branch = ctx.db.branches.find((b) => b.id === session.branchId);
    const expenseId = uid("exp");
    ctx.db.expenses.unshift({
      id: expenseId, expenseNo: nextDocNo(ctx, "EXPENSE", branch?.code), date: ctx.now.toISOString().slice(0, 10), categoryId: category?.id ?? "", categoryName: category?.name ?? "",
      description: input.reason, amount: input.amount, currency: input.currency, amountBase: round(base, 2), paymentMethod: "Cash drawer", branchId: session.branchId, branchName: branch?.nameEn ?? "",
      attachment: null, status: "APPROVED", rejectReason: null, sessionId: session.id, createdBy: user.fullName, createdById: user.id, approvedBy, createdAt: ctx.now.toISOString(),
    });
    movement.expenseId = expenseId;
  }
  ctx.db.cashMovements.unshift(movement);
  audit(ctx, `CASH_${input.kind}`, "CSH", "session", session.id, { after: movement, branchId: session.branchId });
  return movement;
});

POST("/cashier-sessions/:id/close", (ctx) => {
  requirePerm(ctx, "cash.session.close", "cash.session.approve");
  const user = requireUser(ctx);
  const session = getSession(ctx, ctx.params.id);
  if (session.status !== "OPEN") return badState("This session is not open.");
  if (session.cashierId !== user.id && !can(ctx, "cash.session.approve")) return fail(403, "FORBIDDEN", "Only the session owner can submit the count.");
  const { counted, denominations } = ctx.body as { counted: CurrencyAmounts; denominations?: Record<string, number> };
  if (counted.USD < 0 || counted.KHR < 0) return validation("counted", "Amounts must not be negative.");
  const f = sessionFigures(ctx.db, session);
  if (f.pending > 0) return fail(409, "PENDING_PAYMENTS", `${f.pending} payment${f.pending > 1 ? "s are" : " is"} still pending — resolve before closing.`);
  session.counted = counted;
  session.denominations = denominations ?? null;
  session.expected = f.expected;
  session.variance = { USD: round(counted.USD - f.expected.USD, 2), KHR: round(counted.KHR - f.expected.KHR, 2) };
  const { sessionVarianceToleranceUsd: usd, sessionVarianceToleranceKhr: khr } = ctx.db.settings;
  session.needsApproval = Math.abs(session.variance.USD) > usd || Math.abs(session.variance.KHR) > khr;
  if (session.needsApproval) {
    session.status = "CLOSING";
    notify(ctx, "APPROVAL", "Session variance needs review", `${session.sessionNo}: variance ${session.variance.USD} USD / ${session.variance.KHR} KHR.`, { link: "/cashier-sessions", permission: "cash.session.approve", branchId: session.branchId });
  } else {
    session.status = "CLOSED";
    session.closedAt = ctx.now.toISOString();
  }
  audit(ctx, "SESSION_COUNT_SUBMITTED", "CSH", "session", session.id, { after: { counted, expected: f.expected, variance: session.variance }, branchId: session.branchId });
  return session;
});

POST("/cashier-sessions/:id/approve", (ctx) => {
  requirePerm(ctx, "cash.session.approve");
  const user = requireUser(ctx);
  const session = getSession(ctx, ctx.params.id);
  if (session.status !== "CLOSING") return badState("This session is not awaiting review.");
  if (session.cashierId === user.id && !ctx.db.settings.reducedSodMode) return fail(403, "SOD_VIOLATION", "You cannot approve your own variance.");
  const { reason } = ctx.body as { reason: string };
  if (!reason?.trim()) return validation("reason", "A reason is required for variances beyond tolerance.");
  session.varianceReason = reason.trim();
  session.reviewedBy = user.fullName;
  session.status = "CLOSED";
  session.closedAt = ctx.now.toISOString();
  session.needsApproval = false;
  audit(ctx, "SESSION_VARIANCE_APPROVED", "CSH", "session", session.id, { after: { reason, variance: session.variance }, branchId: session.branchId });
  return session;
});

POST("/cashier-sessions/:id/force-close", (ctx) => {
  requirePerm(ctx, "cash.session.approve");
  const user = requireUser(ctx);
  const session = getSession(ctx, ctx.params.id);
  if (session.status !== "OPEN" && session.status !== "CLOSING") return badState("This session is already closed.");
  const { reason } = ctx.body as { reason: string };
  if (!reason?.trim()) return validation("reason", "A reason is required to force close a session.");
  const f = sessionFigures(ctx.db, session);
  session.expected = f.expected;
  session.status = "FORCE_CLOSED";
  session.closedAt = ctx.now.toISOString();
  session.reviewedBy = user.fullName;
  session.varianceReason = reason.trim();
  audit(ctx, "SESSION_FORCE_CLOSED", "CSH", "session", session.id, { after: { reason }, branchId: session.branchId, flagged: true });
  return session;
});

export { allowedBranchIds };
