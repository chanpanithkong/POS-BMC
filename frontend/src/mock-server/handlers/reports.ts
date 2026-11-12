import type {
  DashboardData, KpiValue, Permission, ReportChartSpec, ReportCheck, ReportColumn, ReportDefinition, ReportFilterKey, ReportResult, ReportRow, RoleCode, Sale,
} from "@/types";
import { branchFilter, can, canSeeCost, fail, list, requirePerm, requireUser, round, type Ctx } from "../core";
import { availableInWarehouse, getLocation, getWarehouse, inTransitLocation, onHandInWarehouse, reconcileBalances, settingsFor } from "../domain/inventory";
import { effective } from "./auth";
import { sessionFigures } from "./sales";
import { GET } from "../registry";
import { openSessionFor } from "../domain/sales";

interface Fact {
  date: string;
  branchId: string;
  branchName: string;
  terminalId: string;
  terminalName: string;
  cashierId: string;
  cashierName: string;
  productId: string;
  sku: string;
  name: string;
  categoryId: string;
  qty: number;
  gross: number;
  discount: number;
  returns: number;
  tax: number;
  cogs: number;
  taxCode: string;
  taxRate: number;
}

const net = (f: Pick<Fact, "gross" | "discount" | "returns">) => f.gross - f.discount - f.returns;

function salesFacts(ctx: Ctx, query = ctx.query) {
  const { db } = ctx;
  const scoped = branchFilter({ ...ctx, query });
  const inRange = (d: string | null) => Boolean(d) && (!query.dateFrom || d! >= String(query.dateFrom)) && (!query.dateTo || d! <= String(query.dateTo));
  const productOf = (id: string) => db.products.find((p) => p.id === id);
  const facts: Fact[] = [];
  const saleMatches = (s: Sale) => scoped(s.branchId) && (!query.terminalId || s.terminalId === query.terminalId) && (!query.cashierId || s.cashierId === query.cashierId);
  const sales = db.sales.filter((s) => s.status === "FINALIZED" && inRange(s.businessDate) && saleMatches(s));
  for (const s of sales) {
    for (const l of s.lines) {
      const product = productOf(l.productId);
      if (query.categoryId && product?.categoryId !== query.categoryId) continue;
      const discount = l.discountAmount + l.orderDiscountShare;
      facts.push({
        date: s.businessDate!, branchId: s.branchId, branchName: s.branchName, terminalId: s.terminalId, terminalName: s.terminalName, cashierId: s.cashierId, cashierName: s.cashierName, productId: l.productId, sku: l.sku, name: l.nameEn,
        categoryId: product?.categoryId ?? "", qty: l.quantity, gross: l.grossAmount, discount, returns: 0, tax: l.lineTotal - (l.grossAmount - discount), cogs: l.costTotal ?? 0, taxCode: l.taxCode, taxRate: l.taxRate,
      });
    }
  }
  const returns = db.returns.filter((r) => inRange(r.businessDate) && scoped(r.branchId));
  for (const r of returns) {
    const sale = db.sales.find((s) => s.id === r.originalSaleId);
    if (!sale || !saleMatches(sale)) continue;
    for (const l of r.lines) {
      const product = productOf(l.productId);
      if (query.categoryId && product?.categoryId !== query.categoryId) continue;
      const line = sale.lines.find((x) => x.id === l.saleLineId);
      facts.push({
        date: r.businessDate, branchId: r.branchId, branchName: r.branchName, terminalId: sale.terminalId, terminalName: sale.terminalName, cashierId: sale.cashierId, cashierName: sale.cashierName, productId: l.productId, sku: l.sku, name: l.name,
        categoryId: product?.categoryId ?? "", qty: -l.quantity, gross: 0, discount: 0, returns: l.netAmount, tax: -(l.refundAmount - l.netAmount), cogs: -((l.unitCost ?? 0) * l.quantity * (line?.factor ?? 1)), taxCode: line?.taxCode ?? "", taxRate: line?.taxRate ?? 0,
      });
    }
  }
  return { facts, sales, returns };
}

function aggregate<S extends ReportRow>(facts: Fact[], key: (f: Fact) => string, seed: (f: Fact) => S) {
  const map = new Map<string, S & { gross: number; discount: number; returns: number; tax: number; cogs: number; qty: number }>();
  for (const f of facts) {
    const k = key(f);
    const row = map.get(k) ?? { ...seed(f), gross: 0, discount: 0, returns: 0, tax: 0, cogs: 0, qty: 0 };
    row.gross += f.gross;
    row.discount += f.discount;
    row.returns += f.returns;
    row.tax += f.tax;
    row.cogs += f.cogs;
    row.qty += f.qty;
    map.set(k, row);
  }
  return [...map.values()].map((r) => {
    const netSales = r.gross - r.discount - r.returns;
    const grossProfit = netSales - r.cogs;
    return { ...r, netSales: round(netSales), gross: round(r.gross), discount: round(r.discount), returns: round(r.returns), tax: round(r.tax), cogs: round(r.cogs), qty: round(r.qty, 3), grossProfit: round(grossProfit), margin: netSales ? round((grossProfit / netSales) * 100, 1) : 0 };
  });
}

const c = (key: string, label: string, type: ReportColumn["type"] = "text"): ReportColumn => ({ key, label, type });
const sum = (rows: ReportRow[], key: string) => round(rows.reduce((s, r) => s + Number(r[key] ?? 0), 0));
const totalsOf = (rows: ReportRow[], keys: string[], labelKey: string): ReportRow => ({ [labelKey]: "Total", ...Object.fromEntries(keys.map((k) => [k, sum(rows, k)])) });
const check = (label: string, expected: number, actual: number, tolerance = 0.02): ReportCheck => ({ label, expected: round(expected), actual: round(actual), passed: Math.abs(expected - actual) <= tolerance });
const bar = (xKey: string, key: string, label: string): ReportChartSpec => ({ type: "bar", xKey, series: [{ key, label }] });
const netTotal = (facts: Fact[]) => round(facts.reduce((s, f) => s + net(f), 0));

interface Output {
  columns: ReportColumn[];
  rows: ReportRow[];
  totals?: ReportRow | null;
  chart?: ReportChartSpec | null;
  checks?: ReportCheck[];
  basis?: string;
}

interface ReportImpl extends ReportDefinition {
  run: (ctx: Ctx) => Output;
}

const SALES_BASIS = "Finalized sales by business date; voids excluded; returns shown separately by return date. Currency: USD.";
const SF: ReportFilterKey[] = ["dateRange", "branch"];
const money = (key: string, label: string) => c(key, label, "money");
const SALES_METRIC_COLS = [c("qty", "Qty", "number"), money("netSales", "Net sales"), money("cogs", "COGS"), money("grossProfit", "Gross profit"), c("margin", "Margin %", "percent")];

function warehousesInScope(ctx: Ctx) {
  const inBranch = branchFilter(ctx);
  return ctx.db.warehouses.filter((w) => inBranch(w.branchId) && (!ctx.query.warehouseId || w.id === ctx.query.warehouseId));
}

function productsInScope(ctx: Ctx) {
  return ctx.db.products.filter((p) => p.type !== "SERVICE" && p.type !== "VARIANT_PARENT" && (!ctx.query.categoryId || p.categoryId === ctx.query.categoryId));
}

const catName = (ctx: Ctx, id: string) => ctx.db.categories.find((x) => x.id === id)?.nameEn ?? "";

function dateOk(ctx: Ctx, d: string | null | undefined) {
  if (!d) return false;
  const day = d.slice(0, 10);
  return (!ctx.query.dateFrom || day >= String(ctx.query.dateFrom)) && (!ctx.query.dateTo || day <= String(ctx.query.dateTo));
}

function movementsInScope(ctx: Ctx) {
  const ids = new Set(warehousesInScope(ctx).map((w) => w.id));
  return ctx.db.movements.filter((m) => ids.has(m.warehouseId) && dateOk(ctx, m.businessDate));
}

function stockLevels(ctx: Ctx) {
  return warehousesInScope(ctx).filter((w) => w.branchId).flatMap((w) =>
    productsInScope(ctx).filter((p) => p.status === "ACTIVE").map((p) => {
      const s = settingsFor(p, w.id);
      return { w, p, s, available: availableInWarehouse(ctx.db, w.id, p.id), onHand: onHandInWarehouse(ctx.db, w.id, p.id) };
    }),
  );
}

function batchRows(ctx: Ctx, expired: boolean) {
  const today = ctx.now.toISOString().slice(0, 10);
  const ids = new Set(warehousesInScope(ctx).map((w) => w.id));
  const horizon = new Date(ctx.now.getTime() + Number(ctx.query.days ?? ctx.db.settings.expiryWarningDays) * 86_400_000).toISOString().slice(0, 10);
  return ctx.db.batches
    .filter((b) => b.quantity > 0 && ids.has(getLocation(ctx.db, b.locationId).warehouseId) && (expired ? b.expiryDate < today : b.expiryDate >= today && b.expiryDate <= horizon))
    .sort((a, b) => a.expiryDate.localeCompare(b.expiryDate))
    .map((b) => {
      const p = ctx.db.products.find((x) => x.id === b.productId)!;
      return { sku: p.sku, product: p.nameEn, batch: b.batchNo, expiry: b.expiryDate, location: getLocation(ctx.db, b.locationId).name, qty: b.quantity, value: round(b.quantity * (p.avgCost ?? 0)) };
    });
}

function grossGroup(ctx: Ctx, key: (f: Fact) => string, seed: (f: Fact) => ReportRow, columns: ReportColumn[], labelKey: string, showMargin = true): Output {
  const { facts } = salesFacts(ctx);
  const showCost = canSeeCost(ctx) && showMargin;
  const rows = aggregate(facts, key, seed).sort((a, b) => b.netSales - a.netSales);
  const cols = [...columns, ...SALES_METRIC_COLS.filter((col) => showCost || ["qty", "netSales"].includes(col.key))];
  const totalKeys = cols.filter((col) => ["money", "number"].includes(col.type)).map((col) => col.key);
  // Rows are rounded for display, so the sum may differ from the unrounded total by half a cent per row.
  return { columns: cols, rows, totals: totalsOf(rows, totalKeys, labelKey), chart: bar(labelKey, "netSales", "Net sales"), checks: [check("Sum equals daily sales net", netTotal(facts), sum(rows, "netSales"), 0.005 * rows.length + 0.01)], basis: SALES_BASIS };
}

function paymentsReceived(ctx: Ctx) {
  const { sales } = salesFacts(ctx);
  const scoped = branchFilter(ctx);
  const inRange = (d: string) => (!ctx.query.dateFrom || d >= String(ctx.query.dateFrom)) && (!ctx.query.dateTo || d <= String(ctx.query.dateTo));
  const received = sales.flatMap((s) => s.payments).filter((p) => !["PENDING", "FAILED", "CANCELLED"].includes(p.status));
  const refunds = ctx.db.refunds.filter((r) => {
    if (!inRange(r.businessDate)) return false;
    const ret = ctx.db.returns.find((x) => x.id === r.returnId);
    return ret ? scoped(ret.branchId) : false;
  });
  return { received, refunds };
}

export const REPORTS: ReportImpl[] = [
  {
    id: "RPT-01", name: "Daily sales", group: "Sales", purpose: "End-of-day performance", permission: "reports.sales", needsCost: false, filters: ["dateRange", "branch", "terminal"],
    run: (ctx) => {
      const { facts, sales } = salesFacts(ctx);
      const rows = aggregate(facts, (f) => `${f.date}|${f.branchId}`, (f) => ({ date: f.date, branch: f.branchName })).map((r) => {
        const transactions = sales.filter((s) => s.businessDate === r.date && s.branchName === r.branch).length;
        return { ...r, transactions, basket: transactions ? round((r.gross - r.discount) / transactions) : 0 };
      }).sort((a, b) => String(b.date).localeCompare(String(a.date)));
      const { received, refunds } = paymentsReceived(ctx);
      const paid = received.reduce((s, p) => s + p.amountApplied, 0) - refunds.reduce((s, r) => s + r.amount, 0);
      return {
        columns: [c("date", "Business date", "date"), c("branch", "Branch"), money("gross", "Gross"), money("discount", "Discounts"), money("returns", "Returns"), money("netSales", "Net sales"), money("tax", "Tax"), c("transactions", "Transactions", "number"), money("basket", "Avg basket")],
        rows, totals: totalsOf(rows, ["gross", "discount", "returns", "netSales", "tax", "transactions"], "date"), basis: SALES_BASIS,
        chart: { type: "line", xKey: "date", series: [{ key: "netSales", label: "Net sales" }] },
        checks: [check("Net sales + tax = payments received − refunds", facts.reduce((s, f) => s + net(f) + f.tax, 0), paid)],
      };
    },
  },
  {
    id: "RPT-02", name: "Monthly sales", group: "Sales", purpose: "Monthly trend", permission: "reports.sales", needsCost: false, filters: SF,
    run: (ctx) => {
      const { facts, sales } = salesFacts(ctx);
      const showCost = canSeeCost(ctx);
      const rows = aggregate(facts, (f) => f.date.slice(0, 7), (f) => ({ month: f.date.slice(0, 7) })).map((r) => ({ ...r, transactions: sales.filter((s) => s.businessDate?.startsWith(String(r.month))).length })).sort((a, b) => String(b.month).localeCompare(String(a.month)));
      return { columns: [c("month", "Month"), money("netSales", "Net sales"), ...(showCost ? [money("grossProfit", "Gross profit")] : []), c("transactions", "Transactions", "number")], rows, totals: totalsOf(rows, ["netSales", "transactions", ...(showCost ? ["grossProfit"] : [])], "month"), chart: bar("month", "netSales", "Net sales"), basis: SALES_BASIS, checks: [check("Month total = sum of daily sales", netTotal(facts), sum(rows, "netSales"))] };
    },
  },
  { id: "RPT-03", name: "Sales by product", group: "Sales", purpose: "Item performance", permission: "reports.sales", needsCost: false, filters: [...SF, "category"], run: (ctx) => grossGroup(ctx, (f) => f.productId, (f) => ({ sku: f.sku, product: f.name }), [c("sku", "SKU"), c("product", "Product")], "product") },
  { id: "RPT-04", name: "Sales by category", group: "Sales", purpose: "Category mix", permission: "reports.sales", needsCost: false, filters: SF, run: (ctx) => grossGroup(ctx, (f) => f.categoryId, (f) => ({ category: catName(ctx, f.categoryId) }), [c("category", "Category")], "category") },
  { id: "RPT-05", name: "Sales by branch", group: "Sales", purpose: "Branch comparison", permission: "reports.sales", needsCost: false, filters: ["dateRange"], run: (ctx) => grossGroup(ctx, (f) => f.branchId, (f) => ({ branch: f.branchName }), [c("branch", "Branch")], "branch") },
  { id: "RPT-06", name: "Sales by cashier", group: "Sales", purpose: "Cashier performance and control", permission: "reports.sales", needsCost: false, filters: [...SF, "cashier"], run: (ctx) => grossGroup(ctx, (f) => f.cashierId, (f) => ({ cashier: f.cashierName }), [c("cashier", "Cashier")], "cashier", false) },
  { id: "RPT-07", name: "Sales by terminal", group: "Sales", purpose: "Terminal activity", permission: "reports.sales", needsCost: false, filters: [...SF, "terminal"], run: (ctx) => grossGroup(ctx, (f) => f.terminalId, (f) => ({ terminal: f.terminalName }), [c("terminal", "Terminal")], "terminal", false) },
  {
    id: "RPT-08", name: "Sales by payment method", group: "Sales", purpose: "Payment mix", permission: "reports.sales", needsCost: false, filters: [...SF, "paymentMethod"],
    run: (ctx) => {
      const { received, refunds } = paymentsReceived(ctx);
      const methods = [...new Set([...received.map((p) => p.method), ...refunds.map((r) => r.method)])].filter((m) => !ctx.query.paymentMethod || m === ctx.query.paymentMethod);
      const rows = methods.map((m) => {
        const collected = round(received.filter((p) => p.method === m).reduce((s, p) => s + p.amountApplied, 0));
        const refunded = round(refunds.filter((r) => r.method === m).reduce((s, r) => s + r.amount, 0));
        return { method: m.replaceAll("_", " "), count: received.filter((p) => p.method === m).length, collected, refunded, net: round(collected - refunded) };
      }).sort((a, b) => b.net - a.net);
      return { columns: [c("method", "Method"), c("count", "Payments", "number"), money("collected", "Collected"), money("refunded", "Refunded"), money("net", "Net received")], rows, totals: totalsOf(rows, ["count", "collected", "refunded", "net"], "method"), chart: { type: "pie", xKey: "method", series: [{ key: "net", label: "Net received" }] }, basis: "Completed payments less refunds. Payments are cash received, not revenue." };
    },
  },
  {
    id: "RPT-09", name: "Discounts", group: "Sales", purpose: "Discount control", permission: "reports.sales", needsCost: false, filters: SF,
    run: (ctx) => {
      const { sales } = salesFacts(ctx);
      const rows = sales.flatMap((s) => [
        ...s.lines.filter((l) => l.lineDiscount).map((l) => ({ date: s.businessDate, receipt: s.receiptNo, level: "Line", detail: l.nameEn, source: l.lineDiscount!.source, reason: l.lineDiscount!.reason, cashier: s.cashierName, approver: l.lineDiscount!.approvedBy ?? "", amount: round(l.discountAmount) })),
        ...(s.orderDiscount ? [{ date: s.businessDate, receipt: s.receiptNo, level: "Order", detail: "Order discount", source: s.orderDiscount.source, reason: s.orderDiscount.reason, cashier: s.cashierName, approver: s.orderDiscount.approvedBy ?? "", amount: round(s.lines.reduce((x, l) => x + l.orderDiscountShare, 0)) }] : []),
      ]).sort((a, b) => b.amount - a.amount) as ReportRow[];
      const expected = round(sales.reduce((s, x) => s + x.discountTotal, 0));
      return { columns: [c("date", "Date", "date"), c("receipt", "Receipt"), c("level", "Level"), c("detail", "Detail"), c("source", "Source"), c("reason", "Reason"), c("cashier", "Cashier"), c("approver", "Approver"), money("amount", "Amount")], rows, totals: totalsOf(rows, ["amount"], "date"), basis: SALES_BASIS, checks: [check("Sum equals daily sales discounts", expected, sum(rows, "amount"), 0.1)] };
    },
  },
  {
    id: "RPT-10", name: "Refunds", group: "Sales", purpose: "Refund control", permission: "reports.sales", needsCost: false, filters: SF,
    run: (ctx) => {
      const { returns } = salesFacts(ctx);
      const rows = returns.map((r) => ({ date: r.businessDate, returnNo: r.returnNo, receipt: r.originalReceiptNo, type: r.type, reason: r.lines[0]?.reason ?? "", method: r.refundMethod, by: r.createdBy, approver: r.approvedBy ?? "", amount: r.refundTotal }));
      return { columns: [c("date", "Date", "date"), c("returnNo", "Return no."), c("receipt", "Original receipt"), c("type", "Type"), c("reason", "Reason"), c("method", "Method"), c("by", "Created by"), c("approver", "Approver"), money("amount", "Refund")], rows, totals: totalsOf(rows, ["amount"], "date"), basis: "Returns by return business date." };
    },
  },
  {
    id: "RPT-11", name: "Voided and cancelled transactions", group: "Sales", purpose: "Void control", permission: "reports.sales", needsCost: false, filters: SF,
    run: (ctx) => {
      const scoped = branchFilter(ctx);
      const rows = ctx.db.sales.filter((s) => (s.status === "VOIDED" || (s.status === "CANCELLED" && s.lines.length)) && scoped(s.branchId) && dateOk(ctx, s.createdAt)).map((s) => ({ date: s.createdAt.slice(0, 10), receipt: s.receiptNo ?? "—", status: s.status, cashier: s.cashierName, reason: s.voidReason ?? s.cancelReason ?? "", approver: s.voidedBy ?? "", amount: s.grandTotal }));
      return { columns: [c("date", "Date", "date"), c("receipt", "Receipt"), c("status", "Status"), c("cashier", "Cashier"), c("reason", "Reason"), c("approver", "Approver"), money("amount", "Value")], rows, totals: totalsOf(rows, ["amount"], "date"), basis: "Voided sales and cancelled sales with items, by creation date." };
    },
  },
  {
    id: "RPT-12", name: "Sales tax summary", group: "Sales", purpose: "Tax preparation support", permission: "reports.tax", needsCost: false, filters: SF,
    run: (ctx) => {
      const { facts } = salesFacts(ctx);
      const rows = aggregate(facts, (f) => `${f.taxCode}|${f.taxRate}`, (f) => ({ code: f.taxCode, rate: f.taxRate })).sort((a, b) => String(a.code).localeCompare(String(b.code)));
      return { columns: [c("code", "Tax code"), c("rate", "Rate %", "percent"), money("netSales", "Taxable base"), money("tax", "Tax")], rows, totals: totalsOf(rows, ["netSales", "tax"], "code"), basis: `Configured basis: prices ${ctx.db.settings.taxInclusive ? "include" : "exclude"} tax. Rates are illustrative placeholders until confirmed (V-01).` };
    },
  },
  {
    id: "RPT-13", name: "Gross profit and margin", group: "Sales", purpose: "Profitability", permission: "reports.profit", needsCost: true, filters: [...SF, "category"],
    run: (ctx) => {
      const output = grossGroup(ctx, (f) => f.productId, (f) => ({ sku: f.sku, product: f.name }), [c("sku", "SKU"), c("product", "Product")], "product");
      output.rows.sort((a, b) => Number(b.grossProfit) - Number(a.grossProfit));
      output.chart = bar("product", "grossProfit", "Gross profit");
      output.rows = output.rows.slice(0);
      return { ...output, basis: `${SALES_BASIS} Gross profit = net sales − COGS. Costing: weighted average.` };
    },
  },
  {
    id: "RPT-14", name: "Current stock", group: "Inventory", purpose: "Stock position", permission: "reports.inventory", needsCost: false, filters: ["branch", "warehouse", "category"],
    run: (ctx) => {
      const { db } = ctx;
      const ids = new Set(warehousesInScope(ctx).map((w) => w.id));
      const rows = productsInScope(ctx).flatMap((p) =>
        db.locations.filter((l) => ids.has(l.warehouseId) && l.type !== "IN_TRANSIT").flatMap((l) => {
          const b = db.balances.find((x) => x.locationId === l.id && x.productId === p.id);
          if (!b || !b.onHand) return [];
          return [{ warehouse: getWarehouse(db, l.warehouseId).name, location: l.name, sku: p.sku, product: p.nameEn, onHand: b.onHand, reserved: b.reserved, available: l.availableToSell ? round(b.onHand - b.reserved, 4) : 0 }];
        }),
      );
      const recon = reconcileBalances(db);
      return { columns: [c("warehouse", "Warehouse"), c("location", "Location"), c("sku", "SKU"), c("product", "Product"), c("onHand", "On hand", "number"), c("reserved", "Reserved", "number"), c("available", "Available", "number")], rows, totals: totalsOf(rows, ["onHand", "reserved", "available"], "warehouse"), basis: "Posted movements as of now.", checks: [check("Balances with differences to movements", 0, recon.differences.length, 0)] };
    },
  },
  {
    id: "RPT-15", name: "Stock valuation", group: "Inventory", purpose: "Inventory value", permission: "reports.inventory", needsCost: true, filters: ["asOf", "warehouse", "category", "branch"],
    run: (ctx) => {
      const { db, query } = ctx;
      const ids = new Set(warehousesInScope(ctx).map((w) => w.id));
      const locIds = new Set(db.locations.filter((l) => ids.has(l.warehouseId)).map((l) => l.id));
      const asOf = query.asOf ? String(query.asOf) : null;
      const rows = productsInScope(ctx).map((p) => {
        const movements = db.movements.filter((m) => m.productId === p.id && (!asOf || m.businessDate <= asOf));
        let qty = 0;
        let value = 0;
        for (const m of movements) {
          const delta = (m.toLocationId && locIds.has(m.toLocationId) ? 1 : 0) - (m.fromLocationId && locIds.has(m.fromLocationId) ? 1 : 0);
          qty += delta * m.quantityBase;
          value += delta * (m.totalCost ?? 0);
        }
        if (!asOf) value = qty * (p.avgCost ?? 0);
        return { sku: p.sku, product: p.nameEn, category: catName(ctx, p.categoryId), qty: round(qty, 4), avgCost: qty ? round(value / qty, 4) : 0, value: round(value) };
      }).filter((r) => r.qty !== 0).sort((a, b) => b.value - a.value);
      return { columns: [c("sku", "SKU"), c("product", "Product"), c("category", "Category"), c("qty", "Quantity", "number"), money("avgCost", "Avg cost"), money("value", "Value")], rows, totals: totalsOf(rows, ["qty", "value"], "sku"), basis: `${asOf ? `As of ${asOf}, from movements` : "Current"}. Costing: weighted average, company scope (D-05).` };
    },
  },
  {
    id: "RPT-16", name: "Stock movement history", group: "Inventory", purpose: "Traceability and reconciliation", permission: "reports.inventory", needsCost: false, filters: ["dateRange", "branch", "warehouse"],
    run: (ctx) => {
      const rows = movementsInScope(ctx).slice().reverse().slice(0, 2000).map((m) => ({ date: m.postedAt, type: m.type, sku: m.sku, product: m.productName, from: m.fromLocationName ?? "", to: m.toLocationName ?? "", qty: m.quantityBase, reference: m.sourceNo, user: m.userName }));
      return { columns: [c("date", "Posted", "datetime"), c("type", "Type"), c("sku", "SKU"), c("product", "Product"), c("from", "From"), c("to", "To"), c("qty", "Base qty", "number"), c("reference", "Reference"), c("user", "User")], rows, basis: "Posted movements (latest 2,000)." };
    },
  },
  {
    id: "RPT-17", name: "Low-stock products", group: "Inventory", purpose: "Replenishment", permission: "reports.inventory", needsCost: false, filters: ["branch", "warehouse", "category"],
    run: (ctx) => {
      const rows = stockLevels(ctx).filter((r) => r.available > 0 && r.available <= r.s.reorderLevel).map((r) => ({ warehouse: r.w.name, sku: r.p.sku, product: r.p.nameEn, available: r.available, reorder: r.s.reorderLevel, shortfall: round(r.s.maxLevel - r.available, 3) })).sort((a, b) => b.shortfall - a.shortfall);
      return { columns: [c("warehouse", "Warehouse"), c("sku", "SKU"), c("product", "Product"), c("available", "Available", "number"), c("reorder", "Reorder level", "number"), c("shortfall", "Suggested qty", "number")], rows, basis: "Available is at or below reorder level." };
    },
  },
  {
    id: "RPT-18", name: "Out-of-stock products", group: "Inventory", purpose: "Lost-sales risk", permission: "reports.inventory", needsCost: false, filters: ["branch", "warehouse"],
    run: (ctx) => {
      const rows = stockLevels(ctx).filter((r) => r.available <= 0).map((r) => ({ warehouse: r.w.name, sku: r.p.sku, product: r.p.nameEn, available: r.available, reorder: r.s.reorderLevel }));
      return { columns: [c("warehouse", "Warehouse"), c("sku", "SKU"), c("product", "Product"), c("available", "Available", "number"), c("reorder", "Reorder level", "number")], rows, basis: "Active products with no available stock." };
    },
  },
  {
    id: "RPT-19", name: "Overstock", group: "Inventory", purpose: "Excess inventory", permission: "reports.inventory", needsCost: false, filters: ["branch", "warehouse"],
    run: (ctx) => {
      const rows = stockLevels(ctx).filter((r) => r.s.maxLevel > 0 && r.onHand > r.s.maxLevel).map((r) => ({ warehouse: r.w.name, sku: r.p.sku, product: r.p.nameEn, onHand: r.onHand, max: r.s.maxLevel, excess: round(r.onHand - r.s.maxLevel, 3) })).sort((a, b) => b.excess - a.excess);
      return { columns: [c("warehouse", "Warehouse"), c("sku", "SKU"), c("product", "Product"), c("onHand", "On hand", "number"), c("max", "Maximum", "number"), c("excess", "Excess", "number")], rows, basis: "On hand above maximum level." };
    },
  },
  ...(["RPT-20", "RPT-21"] as const).map((id): ReportImpl => ({
    id, name: id === "RPT-20" ? "Expiring products" : "Expired products", group: "Inventory", purpose: id === "RPT-20" ? "Waste prevention" : "Disposal", permission: "reports.inventory", needsCost: false, filters: ["branch", "warehouse"],
    run: (ctx) => {
      const showCost = canSeeCost(ctx);
      const rows = batchRows(ctx, id === "RPT-21");
      return { columns: [c("sku", "SKU"), c("product", "Product"), c("batch", "Batch"), c("expiry", "Expiry", "date"), c("location", "Location"), c("qty", "Qty", "number"), ...(showCost ? [money("value", "Value")] : [])], rows, totals: totalsOf(rows, ["qty", ...(showCost ? ["value"] : [])], "sku"), basis: "Batch balances for expiry-tracked products." };
    },
  })),
  {
    id: "RPT-22", name: "Damaged inventory", group: "Inventory", purpose: "Loss tracking", permission: "reports.inventory", needsCost: true, filters: ["dateRange", "branch", "warehouse"],
    run: (ctx) => {
      const rows = movementsInScope(ctx).filter((m) => m.type === "DAMAGE" || m.toLocationName?.includes("Damaged")).map((m) => ({ date: m.businessDate, sku: m.sku, product: m.productName, reason: m.reasonCode ?? m.type, qty: m.quantityBase, value: m.totalCost ?? 0, user: m.userName, approver: m.approvedBy ?? "" }));
      return { columns: [c("date", "Date", "date"), c("sku", "SKU"), c("product", "Product"), c("reason", "Reason"), c("qty", "Qty", "number"), money("value", "Value"), c("user", "User"), c("approver", "Approver")], rows, totals: totalsOf(rows, ["qty", "value"], "date"), basis: "Movements into damaged locations." };
    },
  },
  {
    id: "RPT-23", name: "Stock adjustments", group: "Inventory", purpose: "Adjustment control", permission: "reports.inventory", needsCost: true, filters: ["dateRange", "branch", "warehouse"],
    run: (ctx) => {
      const rows = movementsInScope(ctx).filter((m) => m.sourceType === "ADJUSTMENT").map((m) => ({ date: m.businessDate, reference: m.sourceNo, type: m.type, sku: m.sku, product: m.productName, reason: m.reasonCode ?? "", qty: m.quantityBase, value: m.totalCost ?? 0, user: m.userName, approver: m.approvedBy ?? "" }));
      return { columns: [c("date", "Date", "date"), c("reference", "Reference"), c("type", "Type"), c("sku", "SKU"), c("product", "Product"), c("reason", "Reason"), c("qty", "Qty", "number"), money("value", "Value"), c("user", "User"), c("approver", "Approver")], rows, totals: totalsOf(rows, ["qty", "value"], "date"), basis: "Posted adjustment movements." };
    },
  },
  {
    id: "RPT-24", name: "Stocktake variances", group: "Inventory", purpose: "Count accuracy", permission: "reports.inventory", needsCost: true, filters: ["branch", "warehouse"],
    run: (ctx) => {
      const ids = new Set(warehousesInScope(ctx).map((w) => w.id));
      const rows = ctx.db.counts.filter((x) => ids.has(x.warehouseId) && x.status === "POSTED").flatMap((x) => x.lines.filter((l) => l.variance).map((l) => ({ count: x.countNo, location: l.locationName, sku: l.sku, product: l.productName, snapshot: l.snapshotQty, counted: l.countedQty, variance: l.variance, value: l.valueVariance ?? 0, reason: l.reason })));
      return { columns: [c("count", "Count"), c("location", "Location"), c("sku", "SKU"), c("product", "Product"), c("snapshot", "Snapshot", "number"), c("counted", "Counted", "number"), c("variance", "Variance", "number"), money("value", "Value variance"), c("reason", "Reason")], rows, totals: totalsOf(rows, ["variance", "value"], "count"), basis: "Posted stock counts." };
    },
  },
  {
    id: "RPT-25", name: "Transfer history", group: "Inventory", purpose: "Transfer tracking", permission: "reports.inventory", needsCost: false, filters: ["dateRange"],
    run: (ctx) => {
      const rows = ctx.db.transfers.filter((t) => dateOk(ctx, t.createdAt)).map((t) => {
        const add = (f: (l: (typeof t.lines)[number]) => number) => t.lines.reduce((s, l) => s + f(l), 0);
        return { date: t.createdAt.slice(0, 10), transfer: t.transferNo, source: t.sourceWarehouseName, destination: t.destinationWarehouseName, status: t.status, dispatched: add((l) => l.quantityDispatched), received: add((l) => l.quantityReceived), variance: add((l) => l.quantityShort + l.quantityDamaged) };
      });
      const closed = rows.filter((r) => r.status === "CLOSED" || r.status === "RECEIVED");
      return { columns: [c("date", "Date", "date"), c("transfer", "Transfer"), c("source", "Source"), c("destination", "Destination"), c("status", "Status"), c("dispatched", "Dispatched", "number"), c("received", "Received", "number"), c("variance", "Variance", "number")], rows, basis: "All transfers by request date.", checks: [check("Dispatched = received + variance (completed)", sum(closed, "dispatched"), sum(closed, "received") + sum(closed, "variance"))] };
    },
  },
  {
    id: "RPT-26", name: "Inventory turnover and slow-moving stock", group: "Inventory", purpose: "Velocity", permission: "reports.inventory", needsCost: true, filters: ["dateRange", "category", "branch"],
    run: (ctx) => {
      const { facts } = salesFacts(ctx);
      const days = Math.max(1, Math.round((new Date(String(ctx.query.dateTo ?? ctx.now.toISOString().slice(0, 10))).getTime() - new Date(String(ctx.query.dateFrom ?? "2026-01-01")).getTime()) / 86_400_000) + 1);
      const rows = productsInScope(ctx).map((p) => {
        const own = facts.filter((f) => f.productId === p.id);
        const cogs = own.reduce((s, f) => s + f.cogs, 0);
        const units = own.reduce((s, f) => s + f.qty, 0);
        const onHand = ctx.db.balances.filter((b) => b.productId === p.id).reduce((s, b) => s + b.onHand, 0);
        const avgValue = onHand * (p.avgCost ?? 0);
        return { sku: p.sku, product: p.nameEn, sold: round(units, 3), closing: round(onHand, 3), cogs: round(cogs), turnover: avgValue ? round(cogs / avgValue, 2) : 0, daysInv: cogs > 0 ? round(avgValue / (cogs / days), 0) : 0, sellThrough: units + onHand > 0 ? round((units / (units + onHand)) * 100, 1) : 0, slow: units <= 0 && onHand > 0 ? "Slow-moving" : "" };
      }).sort((a, b) => a.turnover - b.turnover);
      return { columns: [c("sku", "SKU"), c("product", "Product"), c("sold", "Units sold", "number"), c("closing", "Closing units", "number"), money("cogs", "COGS"), c("turnover", "Turnover", "number"), c("daysInv", "Days of inventory", "number"), c("sellThrough", "Sell-through %", "percent"), c("slow", "Flag")], rows, basis: "Turnover uses closing value as the average inventory approximation in this mock." };
    },
  },
  {
    id: "RPT-27", name: "Purchase orders and outstanding POs", group: "Purchasing", purpose: "Procurement status", permission: "reports.purchasing", needsCost: true, filters: ["dateRange", "supplier"],
    run: (ctx) => {
      const rows = ctx.db.purchaseOrders.filter((p) => dateOk(ctx, p.createdAt) && (!ctx.query.supplierId || p.supplierId === ctx.query.supplierId)).map((p) => {
        const ordered = p.lines.reduce((s, l) => s + l.quantityBase, 0);
        const received = p.lines.reduce((s, l) => s + l.receivedBase, 0);
        const cancelled = p.lines.reduce((s, l) => s + l.cancelledBase, 0);
        return { date: p.createdAt.slice(0, 10), po: p.poNo, supplier: p.supplierName, status: p.status, ordered, received, cancelled, open: round(ordered - received - cancelled, 3), total: p.total };
      });
      return { columns: [c("date", "Date", "date"), c("po", "PO"), c("supplier", "Supplier"), c("status", "Status"), c("ordered", "Ordered", "number"), c("received", "Received", "number"), c("open", "Open", "number"), money("total", "Value")], rows, totals: totalsOf(rows, ["ordered", "received", "open", "total"], "date"), basis: "Open = ordered − received − cancelled.", chart: null };
    },
  },
  {
    id: "RPT-28", name: "Goods received; purchases by supplier and product", group: "Purchasing", purpose: "Receiving and spend", permission: "reports.purchasing", needsCost: true, filters: ["dateRange", "supplier", "warehouse"],
    run: (ctx) => {
      const rows = ctx.db.goodsReceipts.filter((g) => g.status === "POSTED" && dateOk(ctx, g.postedAt) && (!ctx.query.supplierId || g.supplierId === ctx.query.supplierId) && (!ctx.query.warehouseId || g.warehouseId === ctx.query.warehouseId)).flatMap((g) => g.lines.map((l) => ({ date: g.postedAt?.slice(0, 10) ?? "", receipt: g.receiptNo, supplier: g.supplierName, sku: l.sku, product: l.productName, qty: l.quantityReceived + l.quantityDamaged, unit: l.unitCode, value: round((l.quantityReceived + l.quantityDamaged) * l.unitCost) })));
      const movementValue = round(ctx.db.movements.filter((m) => m.type === "PURCHASE_RECEIPT" && dateOk(ctx, m.businessDate) && (!ctx.query.warehouseId || m.warehouseId === ctx.query.warehouseId) && (!ctx.query.supplierId || ctx.db.goodsReceipts.find((g) => g.id === m.sourceId)?.supplierId === ctx.query.supplierId)).reduce((s, m) => s + (m.totalCost ?? 0), 0));
      return { columns: [c("date", "Date", "date"), c("receipt", "Receipt"), c("supplier", "Supplier"), c("sku", "SKU"), c("product", "Product"), c("qty", "Qty", "number"), c("unit", "Unit"), money("value", "Value")], rows, totals: totalsOf(rows, ["value"], "date"), basis: "Posted goods receipts.", checks: [check("Sum equals purchase receipt movements", movementValue, sum(rows, "value"), 1)] };
    },
  },
  {
    id: "RPT-29", name: "Purchase returns and delivery discrepancies", group: "Purchasing", purpose: "Supplier quality", permission: "reports.purchasing", needsCost: true, filters: ["dateRange", "supplier"],
    run: (ctx) => {
      const returns = ctx.db.purchaseReturns.filter((r) => dateOk(ctx, r.createdAt) && (!ctx.query.supplierId || r.supplierId === ctx.query.supplierId)).map((r) => ({ date: r.createdAt.slice(0, 10), kind: "Return", reference: r.returnNo, supplier: r.supplierName, detail: r.reason, value: r.total }));
      const disc = ctx.db.goodsReceipts.filter((g) => dateOk(ctx, g.createdAt) && (!ctx.query.supplierId || g.supplierId === ctx.query.supplierId)).flatMap((g) => g.discrepancies.map((d) => ({ date: g.createdAt.slice(0, 10), kind: "Discrepancy", reference: g.receiptNo, supplier: g.supplierName, detail: d, value: 0 })));
      return { columns: [c("date", "Date", "date"), c("kind", "Kind"), c("reference", "Reference"), c("supplier", "Supplier"), c("detail", "Detail"), money("value", "Value")], rows: [...returns, ...disc], basis: "Purchase returns and receipt discrepancies." };
    },
  },
  {
    id: "RPT-30", name: "Cashier session report", group: "Cash", purpose: "Cash accountability (overage and shortage)", permission: "reports.cash", needsCost: false, filters: ["dateRange", "branch", "cashier", "terminal"],
    run: (ctx) => {
      const scoped = branchFilter(ctx);
      const all = can(ctx, "cash.session.view_all");
      const rows = ctx.db.cashSessions.filter((s) => scoped(s.branchId) && dateOk(ctx, s.openedAt) && (all || s.cashierId === ctx.user?.id) && (!ctx.query.cashierId || s.cashierId === ctx.query.cashierId) && (!ctx.query.terminalId || s.terminalId === ctx.query.terminalId)).map((s) => {
        const f = sessionFigures(ctx.db, s);
        return { session: s.sessionNo, opened: s.openedAt, cashier: s.cashierName, terminal: s.terminalName, status: s.status, opening: s.opening.USD, cashSales: f.cashSales.USD, refunds: f.cashRefunds.USD, cashIn: f.totals.CASH_IN.USD, out: f.totals.CASH_OUT.USD + f.totals.PAID_OUT.USD, drops: f.totals.DROP.USD, expected: s.expected?.USD ?? null, counted: s.counted?.USD ?? null, variance: s.variance?.USD ?? null };
      });
      return { columns: [c("session", "Session"), c("opened", "Opened", "datetime"), c("cashier", "Cashier"), c("terminal", "Terminal"), c("status", "Status"), money("opening", "Opening"), money("cashSales", "Cash sales"), money("refunds", "Refunds"), money("cashIn", "Cash in"), money("out", "Cash out"), money("drops", "Drops"), money("expected", "Expected"), money("counted", "Counted"), money("variance", "Variance")], rows, totals: totalsOf(rows, ["variance"], "session"), basis: "USD drawer figures; KHR tracked per session. Expected = opening + cash sales + in − refunds − out − paid-outs − drops." };
    },
  },
  {
    id: "RPT-31", name: "Cash movement report", group: "Cash", purpose: "Cash in/out, paid-outs, drops", permission: "reports.cash", needsCost: false, filters: ["dateRange", "branch"],
    run: (ctx) => {
      const scoped = branchFilter(ctx);
      const rows = ctx.db.cashMovements.filter((m) => dateOk(ctx, m.at) && scoped(ctx.db.cashSessions.find((s) => s.id === m.sessionId)?.branchId ?? null)).map((m) => ({ at: m.at, session: ctx.db.cashSessions.find((s) => s.id === m.sessionId)?.sessionNo ?? "", kind: m.kind, currency: m.currency, amount: m.amount, reason: m.reason, by: m.by, approver: m.approvedBy ?? "" }));
      return { columns: [c("at", "Time", "datetime"), c("session", "Session"), c("kind", "Type"), c("currency", "Currency"), c("amount", "Amount", "number"), c("reason", "Reason"), c("by", "By"), c("approver", "Approver")], rows, basis: "Cash movements per session." };
    },
  },
  {
    id: "RPT-32", name: "Payment reconciliation", group: "Cash", purpose: "Provider and bank matching; pending payments", permission: "reports.cash", needsCost: false, filters: ["dateRange", "branch", "paymentMethod"],
    run: (ctx) => {
      const { sales } = salesFacts(ctx);
      const payments = sales.flatMap((s) => s.payments.map((p) => ({ s, p }))).filter(({ p }) => p.method !== "CASH" && p.method !== "STORE_CREDIT" && (!ctx.query.paymentMethod || p.method === ctx.query.paymentMethod));
      const rows = payments.map(({ s, p }) => ({ date: s.businessDate, receipt: s.receiptNo, method: p.method, provider: p.provider ?? "", reference: p.reference ?? "", status: p.status, reconciled: p.reconciled ? "Matched" : "Unmatched", amount: p.amountApplied })) as ReportRow[];
      const matched = rows.filter((r) => r.reconciled === "Matched");
      return { columns: [c("date", "Date", "date"), c("receipt", "Receipt"), c("method", "Method"), c("provider", "Provider"), c("reference", "Reference"), c("status", "Status"), c("reconciled", "Reconciliation"), money("amount", "Amount")], rows, totals: totalsOf(rows, ["amount"], "date"), basis: "Electronic payments on finalized sales. Settlements are marked manually in this frontend phase.", checks: [check("Matched value", sum(rows, "amount"), sum(matched, "amount"))] };
    },
  },
  {
    id: "RPT-33", name: "Business performance", group: "Business", purpose: "Revenue and gross-profit trends, best and worst sellers, operating result", permission: "reports.business", needsCost: true, filters: SF,
    run: (ctx) => {
      const { facts } = salesFacts(ctx);
      const rows = aggregate(facts, (f) => f.date.slice(0, 7), (f) => ({ period: f.date.slice(0, 7) })).sort((a, b) => String(a.period).localeCompare(String(b.period))).map((r) => {
        const expenses = round(ctx.db.expenses.filter((e) => e.status === "APPROVED" && e.date.startsWith(String(r.period)) && branchFilter(ctx)(e.branchId)).reduce((s, e) => s + e.amountBase, 0));
        return { ...r, expenses, indicative: round(r.grossProfit - expenses) };
      });
      return { columns: [c("period", "Period"), money("netSales", "Net sales"), money("cogs", "COGS"), money("grossProfit", "Gross profit"), c("margin", "Margin %", "percent"), money("expenses", "Operating expenses"), money("indicative", "Indicative operating result")], rows, totals: totalsOf(rows, ["netSales", "cogs", "grossProfit", "expenses", "indicative"], "period"), chart: { type: "line", xKey: "period", series: [{ key: "netSales", label: "Net sales" }, { key: "grossProfit", label: "Gross profit" }] }, basis: "Indicative operating result is gross profit less recorded expenses. It is not net profit (BR-RPT-002)." };
    },
  },
  {
    id: "RPT-34", name: "Control exceptions", group: "Control", purpose: "Overrides, self-approvals, reprints, voids, negative stock, receipts without PO", permission: "reports.exceptions", needsCost: false, filters: ["dateRange"],
    run: (ctx) => {
      const types = ["PRICE_OVERRIDE", "DISCOUNT_ABOVE_LIMIT", "SALE_VOIDED", "RECEIPT_REPRINT", "SESSION_FORCE_CLOSED", "GRN_POSTED", "SELF_PERMISSION_ATTEMPT", "ACCOUNT_LOCKED", "APPROVAL_GRANTED"];
      const rows = ctx.db.auditLogs.filter((a) => dateOk(ctx, a.at) && types.includes(a.action) && (a.flagged || !["GRN_POSTED", "APPROVAL_GRANTED", "RECEIPT_REPRINT"].includes(a.action))).map((a) => ({ at: a.at, event: a.action, user: a.userName, entity: `${a.entity}:${a.entityId.slice(0, 12)}`, detail: a.after ?? "" }));
      return { columns: [c("at", "Time", "datetime"), c("event", "Event"), c("user", "User"), c("entity", "Record"), c("detail", "Detail")], rows, basis: "Exception events from the audit log." };
    },
  },
];

GET("/reports", (ctx) => {
  requireUser(ctx);
  return list(REPORTS.filter((r) => can(ctx, r.permission as Permission) && (!r.needsCost || canSeeCost(ctx))).map(({ run: _run, ...definition }) => { void _run; return definition; }));
});

GET("/reports/:id", (ctx): ReportResult => {
  const report = REPORTS.find((r) => r.id === ctx.params.id);
  if (!report) return fail(404, "NOT_FOUND", "Report not found.") as never;
  requirePerm(ctx, report.permission as Permission);
  if (report.needsCost && !canSeeCost(ctx)) return fail(403, "FORBIDDEN", "This report needs cost visibility.") as never;
  const output = report.run(ctx);
  const { run: _run, ...definition } = report;
  void _run;
  return { definition, basis: output.basis ?? "", columns: output.columns, rows: output.rows, totals: output.totals ?? null, chart: output.chart ?? null, checks: output.checks ?? [], generatedAt: ctx.now.toISOString(), generatedBy: requireUser(ctx).fullName };
});

function periodKpis(ctx: Ctx, query: Ctx["query"]) {
  const { facts, sales, returns } = salesFacts(ctx, query);
  const gross = facts.reduce((s, f) => s + f.gross, 0);
  const discounts = facts.reduce((s, f) => s + f.discount, 0);
  const returnsValue = facts.reduce((s, f) => s + f.returns, 0);
  const netSales = gross - discounts - returnsValue;
  const cogs = facts.reduce((s, f) => s + f.cogs, 0);
  return { gross, discounts, returnsValue, netSales, cogs, grossProfit: netSales - cogs, margin: netSales ? ((netSales - cogs) / netSales) * 100 : 0, transactions: sales.length, returns };
}

function previousRange(from: string, to: string) {
  const span = new Date(to).getTime() - new Date(from).getTime();
  const prevTo = new Date(new Date(from).getTime() - 86_400_000);
  const prevFrom = new Date(prevTo.getTime() - span);
  return { dateFrom: prevFrom.toISOString().slice(0, 10), dateTo: prevTo.toISOString().slice(0, 10) };
}

function dashboardVariant(codes: RoleCode[]): DashboardData["variant"] {
  if (codes.some((x) => x === "OWNER" || x === "ACCT" || x === "AUDITOR")) return "OWNER";
  if (codes.some((x) => x === "STOREMGR" || x === "BRMGR")) return "MANAGER";
  if (codes.some((x) => x === "INVMGR" || x === "WHSTAFF")) return "INVENTORY";
  if (codes.includes("PUROFF")) return "PURCHASING";
  if (codes.some((x) => x === "CASHIER" || x === "SALES")) return "CASHIER";
  return "BASIC";
}

GET("/dashboard", (ctx): DashboardData => {
  requirePerm(ctx, "dashboard.view");
  const { db, query } = ctx;
  const user = requireUser(ctx);
  const today = ctx.now.toISOString().slice(0, 10);
  const from = String(query.dateFrom ?? today);
  const to = String(query.dateTo ?? today);
  const range = { ...query, dateFrom: from, dateTo: to };
  const scoped = branchFilter(ctx);
  const showCost = canSeeCost(ctx);
  const variant = dashboardVariant(effective(db, user).roles.map((r) => r.code));
  const current = periodKpis(ctx, range);
  const previous = periodKpis(ctx, { ...query, ...previousRange(from, to) });
  const facts = salesFacts(ctx, range).facts;

  const warehouses = db.warehouses.filter((w) => scoped(w.branchId));
  const locIds = new Set(db.locations.filter((l) => warehouses.some((w) => w.id === l.warehouseId) && l.type !== "IN_TRANSIT").map((l) => l.id));
  const inventoryValue = db.balances.filter((b) => locIds.has(b.locationId)).reduce((s, b) => s + b.onHand * (db.products.find((p) => p.id === b.productId)?.avgCost ?? 0), 0);
  const openAlerts = db.alerts.filter((a) => scoped(a.branchId) && a.status !== "RESOLVED" && a.status !== "SNOOZED");
  const low = openAlerts.filter((a) => a.type === "LOW_STOCK").length;
  const out = openAlerts.filter((a) => a.type === "OUT_OF_STOCK").length;
  const purchaseValue = db.goodsReceipts.filter((g) => g.status === "POSTED" && scoped(g.branchId) && (g.postedAt ?? "").slice(0, 10) >= from && (g.postedAt ?? "").slice(0, 10) <= to).reduce((s, g) => s + (g.totalCost ?? 0), 0);
  const payments = paymentsReceived({ ...ctx, query: range });
  const received = payments.received.reduce((s, p) => s + p.amountApplied, 0) - payments.refunds.reduce((s, r) => s + r.amount, 0);
  const expiring = db.alerts.filter((a) => a.type === "EXPIRING" && a.status !== "RESOLVED" && scoped(a.branchId)).length;
  const inTransitLoc = inTransitLocation(db);
  const inTransit = db.balances.filter((b) => b.locationId === inTransitLoc.id).reduce((s, b) => s + b.onHand, 0);
  const salesRangeRef = `/reports/RPT-01?dateFrom=${from}&dateTo=${to}`;
  const k = (key: string, label: string, value: number, format: KpiValue["format"], definition: string, href: string, prev: number | null, needsCost = false): KpiValue => ({ key, label, value: round(value), format, definition, href, previous: prev === null ? null : round(prev), needsCost });
  const voids = db.sales.filter((s) => s.status === "VOIDED" && scoped(s.branchId) && s.createdAt.slice(0, 10) >= from && s.createdAt.slice(0, 10) <= to);
  const variances = db.cashSessions.filter((s) => scoped(s.branchId) && s.variance && (s.variance.USD !== 0 || s.variance.KHR !== 0) && (s.closedAt ?? "").slice(0, 10) >= from);

  const approvals: DashboardData["approvals"] = [];
  const add = (show: boolean, rows: { id: string; kind: string; label: string; href: string }[]) => show && approvals.push(...rows);
  add(can(ctx, "purchasing.approve"), db.purchaseOrders.filter((p) => p.status === "PENDING_APPROVAL" && scoped(p.branchId)).map((p) => ({ id: p.id, kind: "Purchase order", label: `${p.poNo} · ${p.total.toFixed(2)} USD`, href: "/purchases" })));
  add(can(ctx, "inventory.adjust.approve"), db.adjustments.filter((a) => a.status === "SUBMITTED" && scoped(a.branchId)).map((a) => ({ id: a.id, kind: "Adjustment", label: a.adjustmentNo, href: "/inventory/adjustments" })));
  add(can(ctx, "inventory.transfer.approve"), db.transfers.filter((t) => t.status === "REQUESTED").map((t) => ({ id: t.id, kind: "Transfer", label: t.transferNo, href: "/inventory/transfers" })));
  add(can(ctx, "cash.session.approve"), db.cashSessions.filter((s) => s.status === "CLOSING" && scoped(s.branchId)).map((s) => ({ id: s.id, kind: "Session variance", label: s.sessionNo, href: "/cashier-sessions" })));
  add(can(ctx, "expenses.approve"), db.expenses.filter((e) => e.status === "SUBMITTED" && scoped(e.branchId)).map((e) => ({ id: e.id, kind: "Expense", label: `${e.expenseNo} · ${e.amountBase.toFixed(2)} USD`, href: "/expenses" })));
  add(can(ctx, "inventory.adjust.approve"), db.goodsReceipts.filter((g) => g.status === "PENDING_APPROVAL" && scoped(g.branchId)).map((g) => ({ id: g.id, kind: "Goods receipt", label: g.receiptNo, href: "/purchases/receiving" })));

  const salesKpis = [
    k("gross", "Total sales", current.gross, "money", "Sum of line amounts before discounts, excluding tax, on finalized sales.", salesRangeRef, previous.gross),
    k("net", "Net sales", current.netSales, "money", "Gross sales − discounts − returns, excluding tax.", salesRangeRef, previous.netSales),
    k("gp", "Gross profit", current.grossProfit, "money", "Net sales − COGS (sale-line costs less returned costs).", `/reports/RPT-13?dateFrom=${from}&dateTo=${to}`, previous.grossProfit, true),
    k("margin", "Gross margin", current.margin, "percent", "Gross profit ÷ net sales × 100.", `/reports/RPT-13?dateFrom=${from}&dateTo=${to}`, previous.margin, true),
    k("purchases", "Total purchases", purchaseValue, "money", "Value of posted goods receipts in the period.", `/reports/RPT-28?dateFrom=${from}&dateTo=${to}`, null, true),
    k("received", "Payments received", received, "money", "Completed payments less refunds. Cash received, not revenue.", `/reports/RPT-08?dateFrom=${from}&dateTo=${to}`, null),
    k("invValue", "Inventory value", inventoryValue, "money", "Sum of on hand × average cost, as of now.", "/reports/RPT-15", null, true),
    k("low", "Low-stock products", low, "number", "Count of open low-stock alerts.", "/inventory/alerts", null),
    k("out", "Out of stock", out, "number", "Count of open out-of-stock alerts.", "/inventory/alerts", null),
  ];
  const managerKpis = [
    k("net", "Daily sales", current.netSales, "money", "Net sales for the selected period.", salesRangeRef, previous.netSales),
    k("tx", "Transactions", current.transactions, "number", "Count of finalized sales.", "/sales", previous.transactions),
    k("refunds", "Refunds", current.returnsValue, "money", "Net value of returned lines by return date.", `/reports/RPT-10?dateFrom=${from}&dateTo=${to}`, previous.returnsValue),
    k("voids", "Voided sales", voids.length, "number", "Count of voided sales in the period.", `/reports/RPT-11?dateFrom=${from}&dateTo=${to}`, null),
    k("disc", "Discounts", current.discounts, "money", "Sum of line and order discounts on finalized sales.", `/reports/RPT-09?dateFrom=${from}&dateTo=${to}`, previous.discounts),
    k("variance", "Session discrepancies", variances.length, "number", "Closed sessions with a non-zero cash variance.", "/cashier-sessions", null),
    k("low", "Stock alerts", openAlerts.length, "number", "Open inventory alerts.", "/inventory/alerts", null),
    k("appr", "Pending approvals", approvals.length, "number", "Approval requests waiting for you.", "/dashboard", null),
  ];
  const stockSkus = new Set(db.balances.filter((b) => locIds.has(b.locationId) && b.onHand !== 0).map((b) => b.productId)).size;
  const inventoryKpis = [
    k("skus", "Products in stock", stockSkus, "number", "Products with a non-zero balance in scope.", "/inventory", null),
    k("invValue", "Stock value", inventoryValue, "money", "Sum of on hand × average cost.", "/reports/RPT-15", null, true),
    k("low", "Low stock", low, "number", "Open low-stock alerts.", "/inventory/alerts", null),
    k("out", "Out of stock", out, "number", "Open out-of-stock alerts.", "/inventory/alerts", null),
    k("exp", "Expiring soon", expiring, "number", "Batches expiring within the warning window.", "/inventory/expiring", null),
    k("transit", "Units in transit", inTransit, "number", "Units dispatched and not yet received.", "/inventory/transfers", null),
  ];
  const openPos = db.purchaseOrders.filter((p) => ["APPROVED", "SENT", "PARTIALLY_RECEIVED"].includes(p.status) && scoped(p.branchId));
  const purchasingKpis = [
    k("open", "Open purchase orders", openPos.length, "number", "Approved, sent or partially received orders.", "/purchases", null),
    k("openValue", "Open PO value", openPos.reduce((s, p) => s + p.total, 0), "money", "Total value of open purchase orders.", "/purchases", null, true),
    k("purchases", "Goods received", purchaseValue, "money", "Value of posted receipts in the period.", "/purchases/receiving", null, true),
    k("low", "Reorder alerts", low, "number", "Open low-stock alerts.", "/inventory/alerts", null),
    k("appr", "Awaiting approval", db.purchaseOrders.filter((p) => p.status === "PENDING_APPROVAL").length, "number", "Purchase orders waiting for approval.", "/purchases", null),
  ];
  const kpisAll = variant === "MANAGER" ? managerKpis : variant === "INVENTORY" ? inventoryKpis : variant === "PURCHASING" ? purchasingKpis : variant === "CASHIER" ? [] : salesKpis;
  const kpis = kpisAll.filter((x) => !x.needsCost || showCost);

  const trendRows = aggregate(facts, (f) => f.date, (f) => ({ date: f.date })).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const sales = salesFacts(ctx, range).sales;
  const trend = trendRows.map((r) => ({ date: String(r.date), netSales: r.netSales, transactions: sales.filter((s) => s.businessDate === r.date).length, ...(showCost ? { grossProfit: r.grossProfit } : {}) }));
  const byCategory = aggregate(facts, (f) => f.categoryId, (f) => ({ name: catName(ctx, f.categoryId) })).sort((a, b) => b.netSales - a.netSales).map((r) => ({ name: String(r.name), netSales: r.netSales }));
  const paymentMap = new Map<string, number>();
  payments.received.forEach((p) => paymentMap.set(p.method, (paymentMap.get(p.method) ?? 0) + p.amountApplied));
  const byPayment = [...paymentMap.entries()].map(([name, amount]) => ({ name: name.replaceAll("_", " "), amount: round(amount) })).sort((a, b) => b.amount - a.amount);
  const count = (pred: (s: Sale) => boolean) => sales.filter(pred).length;
  const branchComparison = aggregate(facts, (f) => f.branchId, (f) => ({ name: f.branchName, id: f.branchId })).sort((a, b) => b.netSales - a.netSales).map((r) => ({ name: String(r.name), netSales: r.netSales, transactions: count((s) => s.branchId === r.id), ...(showCost ? { grossProfit: r.grossProfit } : {}) }));
  const topProducts = aggregate(facts, (f) => f.productId, (f) => ({ productId: f.productId, sku: f.sku, name: f.name })).sort((a, b) => b.netSales - a.netSales).slice(0, 8).map((r, i) => ({ rank: i + 1, productId: String(r.productId), sku: String(r.sku), name: String(r.name), quantity: r.qty, netSales: r.netSales, ...(showCost ? { grossProfit: r.grossProfit } : {}) }));
  const soldIn = new Map<string, number>();
  salesFacts(ctx, { ...query, dateFrom: new Date(ctx.now.getTime() - db.settings.slowMovingDays * 86_400_000).toISOString().slice(0, 10), dateTo: today }).facts.forEach((f) => soldIn.set(f.productId, (soldIn.get(f.productId) ?? 0) + f.qty));
  const slowProducts = db.products.filter((p) => p.status === "ACTIVE" && p.type !== "SERVICE" && p.type !== "VARIANT_PARENT").map((p) => ({ productId: p.id, sku: p.sku, name: p.nameEn, onHand: round(db.balances.filter((b) => b.productId === p.id && locIds.has(b.locationId)).reduce((s, b) => s + b.onHand, 0), 3), soldQty: round(soldIn.get(p.id) ?? 0, 3) })).filter((r) => r.onHand > 0).sort((a, b) => a.soldQty - b.soldQty).slice(0, 5);
  const byCashier = aggregate(facts, (f) => f.cashierId, (f) => ({ name: f.cashierName, id: f.cashierId })).sort((a, b) => b.netSales - a.netSales).map((r) => ({ name: String(r.name), netSales: r.netSales, transactions: count((s) => s.cashierId === r.id) }));
  const byTerminal = aggregate(facts, (f) => f.terminalId, (f) => ({ name: f.terminalName, id: f.terminalId })).sort((a, b) => b.netSales - a.netSales).map((r) => ({ name: String(r.name), netSales: r.netSales, transactions: count((s) => s.terminalId === r.id) }));
  const canAllSales = can(ctx, "sales.view_all");
  const recentTransactions = db.sales.filter((s) => s.status === "FINALIZED" && scoped(s.branchId) && (canAllSales || s.cashierId === user.id)).slice(0, 8).map((s) => ({ id: s.id, receiptNo: s.receiptNo ?? "", at: s.finalizedAt ?? s.createdAt, customer: s.customerName ?? "Walk-in", total: s.grandTotal, status: s.status, paymentStatus: s.paymentStatus }));

  const summaryRange = (label: string, days: number) => {
    const start = new Date(ctx.now.getTime() - (days - 1) * 86_400_000).toISOString().slice(0, 10);
    const p = periodKpis(ctx, { ...query, dateFrom: start, dateTo: today });
    return { label, netSales: round(p.netSales), transactions: p.transactions, ...(showCost ? { grossProfit: round(p.grossProfit) } : {}) };
  };
  let cashier: DashboardData["cashier"] = null;
  if (variant === "CASHIER") {
    const session = db.cashSessions.find((s) => s.cashierId === user.id && s.status === "OPEN") ?? (ctx.terminalId ? openSessionFor(db, ctx.terminalId) : undefined);
    const figures = session ? sessionFigures(db, session) : null;
    const terminal = session ? session.terminalName : db.terminals.find((t) => t.assignedCashierIds.includes(user.id))?.name ?? "Not assigned";
    cashier = { shift: session ? new Date(session.openedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "No open shift", terminal, status: session ? session.status : "CLOSED", salesCompleted: figures?.salesCount ?? 0, cashReceived: figures ? round(figures.cashSales.USD) : 0, pending: figures?.pending ?? 0, sessionId: session?.id ?? null };
  }
  return { variant, kpis, trend, byCategory, byPayment, branchComparison, topProducts, slowProducts, byCashier, byTerminal, recentTransactions, alerts: openAlerts.slice(0, 6).map((a) => ({ id: a.id, type: a.type, message: a.message, productName: a.productName })), approvals, summaries: [summaryRange("Today", 1), summaryRange("Last 7 days", 7), summaryRange("Last 30 days", 30)], cashier };
});
