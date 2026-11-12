import type { Customer, PriceSource, Product, Promotion, Sale, SaleLine } from "@/types";
import { currentRate, round } from "../core";
import type { MockDb } from "../db";

export interface ResolvedPrice {
  price: number;
  source: PriceSource;
  explanation: string;
  promotionName: string | null;
}

function factorFor(product: Product, unitId: string) {
  if (unitId === product.baseUnitId) return 1;
  return product.conversions.find((c) => c.unitId === unitId)?.factor ?? 1;
}

function isActivePrice(p: { effectiveFrom: string; effectiveTo: string | null }, now: Date) {
  const t = now.toISOString();
  return p.effectiveFrom <= t && (!p.effectiveTo || p.effectiveTo >= t);
}

function promotionApplies(db: MockDb, promo: Promotion, product: Product, branchId: string, customer: Customer | null, now: Date) {
  if (promo.status !== "ACTIVE") return false;
  const today = now.toISOString().slice(0, 10);
  if (today < promo.startDate || today > promo.endDate) return false;
  if (promo.startTime && promo.endTime) {
    const hhmm = now.toTimeString().slice(0, 5);
    if (hhmm < promo.startTime || hhmm > promo.endTime) return false;
  }
  if (promo.branchIds.length && !promo.branchIds.includes(branchId)) return false;
  if (promo.customerGroupIds.length && !(customer?.groupId && promo.customerGroupIds.includes(customer.groupId))) return false;
  if (promo.usageLimit !== null && promo.usageCount >= promo.usageLimit) return false;
  if (promo.type === "ORDER") return false;
  const byProduct = promo.productIds.includes(product.id);
  const byCategory = promo.categoryIds.includes(product.categoryId);
  return byProduct || byCategory || (promo.type === "TIME_BASED" && !promo.productIds.length && !promo.categoryIds.length);
}

export function bestPromotion(db: MockDb, product: Product, branchId: string, customer: Customer | null, now: Date, base: number) {
  const value = (p: Promotion) => (p.type === "BOGO" ? base / 2 : (base * p.discountPct) / 100 + p.discountAmount);
  return db.promotions
    .filter((p) => promotionApplies(db, p, product, branchId, customer, now))
    .sort((a, b) => b.priority - a.priority || value(b) - value(a))[0];
}

/** Resolution order per BR-PRC-002; manual overrides are applied by the caller. */
export function resolvePrice(db: MockDb, product: Product, unitId: string, branchId: string, customer: Customer | null, now: Date): ResolvedPrice {
  const factor = factorFor(product, unitId);
  const unitRecords = db.prices.filter((p) => p.productId === product.id && p.unitId === unitId && isActivePrice(p, now));
  const retailList = db.priceLists.find((l) => l.type === "RETAIL");
  const wholesaleList = db.priceLists.find((l) => l.type === "WHOLESALE");
  const latest = <T extends { effectiveFrom: string }>(rows: T[]) => [...rows].sort((a, b) => b.effectiveFrom.localeCompare(a.effectiveFrom))[0];

  const standardRecord = latest(unitRecords.filter((p) => p.priceListId === retailList?.id && !p.branchId && !p.customerGroupId));
  const group = customer?.groupId ? db.customerGroups.find((g) => g.id === customer.groupId) : undefined;
  const useWholesale = group?.priceListId && group.priceListId === wholesaleList?.id;
  const groupRecord = group ? latest(unitRecords.filter((p) => p.customerGroupId === group.id)) : undefined;
  const branchRecord = db.settings.branchPricingEnabled ? latest(unitRecords.filter((p) => p.branchId === branchId && !p.customerGroupId)) : undefined;

  let result: ResolvedPrice;
  if (groupRecord) {
    result = { price: groupRecord.price, source: "CUSTOMER_GROUP", explanation: `Customer group price (${group?.name})`, promotionName: null };
  } else if (branchRecord) {
    result = { price: branchRecord.price, source: "BRANCH", explanation: "Branch price", promotionName: null };
  } else if (useWholesale) {
    const wholesaleRecord = latest(unitRecords.filter((p) => p.priceListId === wholesaleList?.id && !p.branchId && !p.customerGroupId));
    result = { price: wholesaleRecord?.price ?? round(product.wholesalePrice * factor, 2), source: "WHOLESALE", explanation: "Wholesale price list", promotionName: null };
  } else {
    result = { price: standardRecord?.price ?? round(product.retailPrice * factor, 2), source: "STANDARD", explanation: "Standard retail price", promotionName: null };
  }

  const promo = bestPromotion(db, product, branchId, customer, now, result.price);
  if (promo && promo.type !== "BOGO") {
    const promoPrice = round(Math.max(0, result.price * (1 - promo.discountPct / 100) - promo.discountAmount * factor), 2);
    if (promoPrice < result.price) {
      return { price: promoPrice, source: "PROMOTION", explanation: `Promotion: ${promo.name}`, promotionName: promo.name };
    }
  }
  return result;
}

/** Server-side recalculation of a draft sale, honouring tax configuration (FR-POS-007). */
export function calculateTotals(db: MockDb, sale: Sale) {
  const inclusive = db.settings.taxInclusive;
  let gross = 0;
  for (const line of sale.lines) {
    const taxDivisor = inclusive ? 1 + line.taxRate / 100 : 1;
    line.grossAmount = round((line.unitPrice * line.quantity) / taxDivisor, 4);
    let discount = 0;
    if (line.lineDiscount) {
      discount =
        line.lineDiscount.type === "PERCENT"
          ? (line.grossAmount * line.lineDiscount.value) / 100
          : line.lineDiscount.value / taxDivisor;
    }
    line.discountAmount = round(Math.min(discount, line.grossAmount), 4);
    gross += line.grossAmount - line.discountAmount;
  }
  let orderDiscount = 0;
  if (sale.orderDiscount) {
    orderDiscount =
      sale.orderDiscount.type === "PERCENT" ? (gross * sale.orderDiscount.value) / 100 : sale.orderDiscount.value;
    orderDiscount = Math.min(orderDiscount, gross);
  }
  let allocated = 0;
  sale.lines.forEach((line: SaleLine, index) => {
    const base = line.grossAmount - line.discountAmount;
    const share = index === sale.lines.length - 1 ? orderDiscount - allocated : gross > 0 ? (orderDiscount * base) / gross : 0;
    line.orderDiscountShare = round(share, 4);
    allocated += line.orderDiscountShare;
    const net = base - line.orderDiscountShare;
    line.taxAmount = round((net * line.taxRate) / 100, 4);
    line.lineTotal = round(net + line.taxAmount, 2);
  });
  sale.subtotal = round(sale.lines.reduce((s, l) => s + l.grossAmount, 0), 2);
  sale.discountTotal = round(sale.lines.reduce((s, l) => s + l.discountAmount + l.orderDiscountShare, 0), 2);
  sale.taxTotal = round(sale.lines.reduce((s, l) => s + l.taxAmount, 0), 2);
  sale.grandTotal = round(sale.lines.reduce((s, l) => s + l.lineTotal, 0), 2);
  sale.rounding = 0;
  sale.exchangeRate = currentRate(db);
  sale.grandTotalKhr = roundKhr(db, sale.grandTotal * sale.exchangeRate);
  const paid = sale.payments.filter((p) => p.status === "COMPLETED" || p.status === "PARTIALLY_REFUNDED").reduce((s, p) => s + p.amountApplied, 0);
  sale.paidTotal = round(paid, 2);
  sale.balance = round(sale.grandTotal - sale.paidTotal, 2);
}

export function roundKhr(db: MockDb, amount: number) {
  const increment = db.settings.khrCashIncrement || 100;
  return Math.round(amount / increment) * increment;
}

export function derivePaymentStatus(sale: Sale): Sale["paymentStatus"] {
  if (sale.refundedTotal > 0) {
    return sale.refundedTotal >= sale.grandTotal - 0.005 ? "REFUNDED" : "PARTIALLY_REFUNDED";
  }
  if (sale.paidTotal <= 0) return "UNPAID";
  return sale.paidTotal >= sale.grandTotal - 0.005 ? "PAID" : "PARTIALLY_PAID";
}
