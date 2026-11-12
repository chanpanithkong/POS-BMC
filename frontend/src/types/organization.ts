import type { ActiveStatus, Currency, ID, IsoDateTime } from "./common";

export interface Company {
  id: ID;
  legalNameEn: string;
  legalNameKm: string;
  tradingNameEn: string;
  tradingNameKm: string;
  address: string;
  phone: string;
  taxId: string;
  logo: string | null;
  baseCurrency: Currency;
  fiscalYearStartMonth: number;
}

export interface Branch {
  id: ID;
  code: string;
  nameEn: string;
  nameKm: string;
  address: string;
  phone: string;
  receiptHeader: string;
  openTime: string;
  closeTime: string;
  dayCutoff: string;
  status: ActiveStatus;
}

export interface Warehouse {
  id: ID;
  code: string;
  name: string;
  branchId: ID | null;
  isCentral: boolean;
  status: ActiveStatus;
}

export const LOCATION_TYPES = [
  "SELLABLE",
  "STORAGE",
  "RECEIVING",
  "DAMAGED",
  "EXPIRED",
  "QUARANTINE",
  "RETURNS",
  "IN_TRANSIT",
] as const;
export type LocationType = (typeof LOCATION_TYPES)[number];

export interface StockLocation {
  id: ID;
  code: string;
  name: string;
  warehouseId: ID;
  type: LocationType;
  availableToSell: boolean;
  status: ActiveStatus;
}

export interface Terminal {
  id: ID;
  code: string;
  name: string;
  branchId: ID;
  defaultLocationId: ID;
  printerProfile: "58mm" | "80mm";
  cashDrawer: boolean;
  status: ActiveStatus;
  assignedCashierIds: ID[];
}

export interface TaxCode {
  id: ID;
  code: string;
  name: string;
  rate: number;
  status: ActiveStatus;
}

export interface ExchangeRate {
  id: ID;
  from: Currency;
  to: Currency;
  rate: number;
  effectiveAt: IsoDateTime;
  createdBy: string;
}

export type PaymentMethodCode =
  | "CASH"
  | "CARD"
  | "QR"
  | "BANK_TRANSFER"
  | "STORE_CREDIT";

export interface PaymentMethodConfig {
  id: ID;
  code: PaymentMethodCode;
  name: string;
  requiresReference: boolean;
  provider: string;
  status: ActiveStatus;
}

export type DocumentType =
  | "RECEIPT"
  | "INVOICE"
  | "RETURN"
  | "PO"
  | "GRN"
  | "TRANSFER"
  | "ADJUSTMENT"
  | "COUNT"
  | "EXPENSE"
  | "SUPPLIER_RETURN";

export interface DocumentSequence {
  id: ID;
  docType: DocumentType;
  prefix: string;
  nextValue: number;
  padding: number;
  includeBranch: boolean;
  includeYear: boolean;
}

export interface ReceiptTemplate {
  id: ID;
  branchId: ID | null;
  name: string;
  language: "EN" | "KM" | "BILINGUAL";
  paperWidth: "58mm" | "80mm";
  header: string;
  footer: string;
  showLogo: boolean;
  showTaxId: boolean;
  showQr: boolean;
}

export type CostingMethod = "WAC";

export interface SystemSettings {
  taxInclusive: boolean;
  khrCashIncrement: number;
  skuMode: "AUTO" | "MANUAL";
  skuPrefix: string;
  branchPricingEnabled: boolean;
  costingMethod: CostingMethod;
  costingScope: "COMPANY";
  negativeStockAllowed: boolean;
  reducedSodMode: boolean;
  posIdleLockMinutes: number;
  returnWindowDays: number;
  noReceiptReturnsEnabled: boolean;
  storeCreditEnabled: boolean;
  loyaltyEnabled: boolean;
  loyaltyPointsPerUsd: number;
  loyaltyRedeemUsdPerPoint: number;
  expenseApprovalThreshold: number;
  expenseAttachmentThreshold: number;
  overDeliveryTolerancePct: number;
  sessionVarianceToleranceUsd: number;
  sessionVarianceToleranceKhr: number;
  cashMovementApprovalThreshold: number;
  refundCashApprovalThreshold: number;
  adjustmentAlertValue: number;
  countVarianceRecountQty: number;
  transferApprovalValue: number;
  slowMovingDays: number;
  expiryWarningDays: number;
  dateFormat: "DD/MM/YYYY";
  timeZone: string;
}
