import type { BusinessDate, Currency, ID, IsoDateTime, ActiveStatus } from "./common";
import type { PaymentMethodCode } from "./organization";

export type SaleStatus =
  | "DRAFT"
  | "HELD"
  | "PENDING_PAYMENT"
  | "FINALIZED"
  | "CANCELLED"
  | "VOIDED";

export type SalePaymentStatus =
  | "UNPAID"
  | "PARTIALLY_PAID"
  | "PAID"
  | "PARTIALLY_REFUNDED"
  | "REFUNDED"
  | "ON_ACCOUNT";

export type PaymentStatus =
  | "PENDING"
  | "AUTHORIZED"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "PARTIALLY_REFUNDED"
  | "REFUNDED";

export type FulfilmentStatus = "NOT_REQUIRED" | "PENDING" | "FULFILLED";
export type DiscountType = "PERCENT" | "AMOUNT";
export type PriceSource =
  | "OVERRIDE"
  | "PROMOTION"
  | "CUSTOMER_GROUP"
  | "BRANCH"
  | "WHOLESALE"
  | "STANDARD";

export interface AppliedDiscount {
  type: DiscountType;
  value: number;
  reason: string;
  source: "MANUAL" | "PROMOTION" | "COUPON" | "CUSTOMER";
  approvedBy: string | null;
}

export interface SaleLine {
  id: ID;
  productId: ID;
  sku: string;
  nameEn: string;
  nameKm: string;
  unitId: ID;
  unitCode: string;
  factor: number;
  quantity: number;
  quantityBase: number;
  allowFraction: boolean;
  precision: number;
  unitPrice: number;
  priceSource: PriceSource;
  priceExplanation: string;
  listPrice: number;
  overrideApprovedBy: string | null;
  overrideReason: string | null;
  lineDiscount: AppliedDiscount | null;
  promotionName: string | null;
  grossAmount: number;
  discountAmount: number;
  orderDiscountShare: number;
  taxCodeId: ID | null;
  taxCode: string;
  taxRate: number;
  taxAmount: number;
  lineTotal: number;
  unitCost?: number;
  costTotal?: number;
  returnedQuantity: number;
  available: number;
  isService: boolean;
  priceChanged: boolean;
}

export interface SalePayment {
  id: ID;
  saleId: ID;
  sessionId: ID | null;
  terminalId: ID;
  method: PaymentMethodCode;
  currency: Currency;
  amountTendered: number;
  exchangeRate: number;
  amountApplied: number;
  changeAmount: number;
  changeCurrency: Currency;
  roundingAmount: number;
  status: PaymentStatus;
  provider: string | null;
  reference: string | null;
  approvalCode: string | null;
  cardLast4: string | null;
  failureReason: string | null;
  refundedAmount: number;
  createdAt: IsoDateTime;
  completedAt: IsoDateTime | null;
  reconciled: boolean;
}

export interface Sale {
  id: ID;
  receiptNo: string | null;
  branchId: ID;
  branchName: string;
  terminalId: ID;
  terminalName: string;
  sessionId: ID | null;
  cashierId: ID;
  cashierName: string;
  salespersonId: ID | null;
  customerId: ID | null;
  customerName: string | null;
  status: SaleStatus;
  paymentStatus: SalePaymentStatus;
  fulfilmentStatus: FulfilmentStatus;
  currency: Currency;
  subtotal: number;
  discountTotal: number;
  taxTotal: number;
  rounding: number;
  grandTotal: number;
  paidTotal: number;
  refundedTotal: number;
  balance: number;
  exchangeRate: number;
  grandTotalKhr: number;
  orderDiscount: AppliedDiscount | null;
  couponCode: string | null;
  lines: SaleLine[];
  payments: SalePayment[];
  returnIds: ID[];
  holdLabel: string | null;
  businessDate: BusinessDate | null;
  createdAt: IsoDateTime;
  finalizedAt: IsoDateTime | null;
  reprintCount: number;
  cancelReason: string | null;
  voidReason: string | null;
  voidedBy: string | null;
  invoiceNo: string | null;
  loyaltyEarned: number;
  version: number;
  notices: string[];
}

export type SaleOp =
  | { type: "add_barcode"; barcode: string }
  | { type: "add_product"; productId: string; unitId?: string; quantity?: number }
  | { type: "set_quantity"; lineId: string; quantity: number }
  | { type: "set_unit"; lineId: string; unitId: string }
  | { type: "remove_line"; lineId: string }
  | {
      type: "line_discount";
      lineId: string;
      discountType: DiscountType;
      value: number;
      reason: string;
      approvalToken?: string;
    }
  | {
      type: "order_discount";
      discountType: DiscountType;
      value: number;
      reason: string;
      approvalToken?: string;
    }
  | {
      type: "override_price";
      lineId: string;
      price: number;
      reason: string;
      approvalToken?: string;
    }
  | { type: "set_customer"; customerId: string | null }
  | { type: "apply_coupon"; code: string | null }
  | { type: "hold"; label: string }
  | { type: "resume" };

export interface AddPaymentInput {
  method: PaymentMethodCode;
  currency: Currency;
  amountTendered: number;
  changeCurrency?: Currency;
  reference?: string;
  approvalCode?: string;
  cardLast4?: string;
}

export type ReturnCondition = "RESALABLE" | "DAMAGED" | "EXPIRED" | "NON_RETURNABLE";

export interface SalesReturnLine {
  saleLineId: ID;
  productId: ID;
  sku: string;
  name: string;
  quantity: number;
  condition: ReturnCondition;
  reason: string;
  netAmount: number;
  taxAmount: number;
  refundAmount: number;
  unitCost?: number;
  destinationLocationId: ID;
}

export type RefundMethod = PaymentMethodCode;

export interface Refund {
  id: ID;
  returnId: ID;
  salePaymentId: ID | null;
  method: RefundMethod;
  amount: number;
  currency: Currency;
  status: "PENDING" | "COMPLETED" | "FAILED";
  reference: string | null;
  sessionId: ID | null;
  createdAt: IsoDateTime;
  businessDate: BusinessDate;
}

export interface SalesReturn {
  id: ID;
  returnNo: string;
  originalSaleId: ID;
  originalReceiptNo: string;
  branchId: ID;
  branchName: string;
  terminalId: ID;
  sessionId: ID | null;
  customerName: string | null;
  type: "RETURN" | "EXCHANGE";
  lines: SalesReturnLine[];
  refundMethod: RefundMethod;
  refundTotal: number;
  netTotal: number;
  taxTotal: number;
  refundStatus: "PENDING" | "COMPLETED";
  reference: string | null;
  exchangeSaleId: ID | null;
  differencePaid: number;
  createdBy: string;
  approvedBy: string | null;
  overrideWindow: boolean;
  createdAt: IsoDateTime;
  businessDate: BusinessDate;
}

export interface CreateReturnInput {
  lines: { saleLineId: string; quantity: number; condition: ReturnCondition; reason: string }[];
  refundMethod: RefundMethod;
  reference?: string;
  approvalToken?: string;
  replacementLines?: { productId: string; unitId?: string; quantity: number }[];
  settlementMethod?: PaymentMethodCode;
  settlementReference?: string;
}

export interface ReturnQuote {
  refundTotal: number;
  netTotal: number;
  taxTotal: number;
  lines: { saleLineId: string; quantity: number; netAmount: number; taxAmount: number; refundAmount: number }[];
  windowExpired: boolean;
  approvalReasons: string[];
  replacementTotal: number;
  difference: number;
}

export type CashSessionStatus = "OPEN" | "CLOSING" | "CLOSED" | "FORCE_CLOSED";
export type CashMovementKind = "CASH_IN" | "CASH_OUT" | "PAID_OUT" | "DROP";

export interface CashMovement {
  id: ID;
  sessionId: ID;
  kind: CashMovementKind;
  currency: Currency;
  amount: number;
  reason: string;
  witness: string | null;
  approvedBy: string | null;
  expenseId: ID | null;
  at: IsoDateTime;
  by: string;
}

export type CurrencyAmounts = Record<Currency, number>;

export interface CashSession {
  id: ID;
  sessionNo: string;
  terminalId: ID;
  terminalName: string;
  branchId: ID;
  cashierId: ID;
  cashierName: string;
  status: CashSessionStatus;
  openedAt: IsoDateTime;
  closedAt: IsoDateTime | null;
  opening: CurrencyAmounts;
  witness: string | null;
  counted: CurrencyAmounts | null;
  denominations: Record<string, number> | null;
  /** Hidden from the cashier until the blind count is submitted (FR-CSH-007). */
  expected: CurrencyAmounts | null;
  variance: CurrencyAmounts | null;
  varianceReason: string | null;
  reviewedBy: string | null;
  needsApproval: boolean;
}

export interface SessionSummary {
  session: CashSession;
  movements: CashMovement[];
  cashSales: CurrencyAmounts | null;
  cashRefunds: CurrencyAmounts | null;
  movementTotals: Record<CashMovementKind, CurrencyAmounts> | null;
  nonCashTotals: Record<string, number>;
  salesCount: number;
  salesTotal: number;
  pendingPayments: number;
}

export interface Customer {
  id: ID;
  code: string;
  name: string;
  phone: string;
  email: string;
  address: string;
  groupId: ID | null;
  groupName?: string;
  notes: string;
  consentMarketing: boolean;
  loyaltyPoints: number;
  tier: string;
  storeCredit: number;
  creditLimit: number;
  lastPurchaseAt: IsoDateTime | null;
  totalSpent: number;
  status: ActiveStatus;
  anonymized: boolean;
  createdAt: IsoDateTime;
}

export interface CustomerGroup {
  id: ID;
  code: string;
  name: string;
  priceListId: ID | null;
  discountPct: number;
  status: ActiveStatus;
}
