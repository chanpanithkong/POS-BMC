import type { ActiveStatus, ID, IsoDateTime } from "./common";

export type ProductType = "STANDARD" | "WEIGHED" | "VARIANT_PARENT" | "SERVICE";
export type ProductStatus = "DRAFT" | "ACTIVE" | "INACTIVE" | "DISCONTINUED";
export type BarcodeSymbology = "EAN13" | "EAN8" | "UPCA" | "CODE128";

export interface Category {
  id: ID;
  code: string;
  nameEn: string;
  nameKm: string;
  parentId: ID | null;
  defaultTaxCodeId: ID | null;
  returnable: boolean;
  returnWindowDays: number;
  allowNegativeStock: boolean;
  expiryTrackingDefault: boolean;
  minMarginPct: number;
  /** Lucide icon key used on POS tiles. */
  icon: string;
  status: ActiveStatus;
}

export interface Brand {
  id: ID;
  code: string;
  name: string;
  status: ActiveStatus;
}

export interface Unit {
  id: ID;
  code: string;
  nameEn: string;
  nameKm: string;
  dimension: "COUNT" | "MASS" | "VOLUME" | "LENGTH";
  precision: number;
  status: ActiveStatus;
}

export interface UnitConversion {
  id: ID;
  unitId: ID;
  factor: number;
  isPurchaseDefault: boolean;
  isSalesDefault: boolean;
}

export interface ProductBarcode {
  id: ID;
  barcode: string;
  symbology: BarcodeSymbology;
  unitId: ID;
  active: boolean;
  createdAt: IsoDateTime;
}

export interface ProductSupplierLink {
  supplierId: ID;
  supplierSku: string;
  purchaseUnitId: ID;
  cost: number;
  leadTimeDays: number;
  preferred: boolean;
}

export interface StockSettings {
  reorderLevel: number;
  minLevel: number;
  maxLevel: number;
  reorderQty: number;
}

export interface Product {
  id: ID;
  sku: string;
  nameEn: string;
  nameKm: string;
  description: string;
  type: ProductType;
  parentId: ID | null;
  variantAttrs: Record<string, string> | null;
  categoryId: ID;
  brandId: ID | null;
  baseUnitId: ID;
  allowFraction: boolean;
  precision: number;
  taxCodeId: ID | null;
  status: ProductStatus;
  image: string | null;
  conversions: UnitConversion[];
  barcodes: ProductBarcode[];
  retailPrice: number;
  wholesalePrice: number;
  minSellingPrice: number | null;
  /** Present only with costs.view (BR-SEC-003). */
  lastPurchaseCost?: number;
  avgCost?: number;
  stockSettings: StockSettings;
  warehouseSettings: Record<ID, StockSettings>;
  suppliers: ProductSupplierLink[];
  trackExpiry: boolean;
  isFavourite: boolean;
  hasMovements: boolean;
  branchActivation: Record<ID, boolean>;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

/** Row returned by product search on POS and catalogue lists. */
export interface ProductListItem extends Product {
  categoryName: string;
  brandName: string;
  unitCode: string;
  available: number;
  onHand: number;
}

export interface ProductChange {
  id: ID;
  productId: ID;
  at: IsoDateTime;
  userName: string;
  field: string;
  before: string;
  after: string;
}

export interface BarcodeRow extends ProductBarcode {
  productId: ID;
  sku: string;
  productName: string;
  unitCode: string;
}

export type PriceListType = "RETAIL" | "WHOLESALE" | "GROUP" | "BRANCH";

export interface PriceList {
  id: ID;
  code: string;
  name: string;
  type: PriceListType;
  status: ActiveStatus;
}

export interface ProductPrice {
  id: ID;
  productId: ID;
  unitId: ID;
  priceListId: ID | null;
  branchId: ID | null;
  customerGroupId: ID | null;
  price: number;
  effectiveFrom: IsoDateTime;
  effectiveTo: IsoDateTime | null;
  createdBy: string;
  // Denormalised for display.
  sku?: string;
  productName?: string;
  scopeLabel?: string;
}

export interface PriceHistoryEntry {
  id: ID;
  productId: ID;
  sku: string;
  productName: string;
  scope: string;
  oldPrice: number;
  newPrice: number;
  effectiveFrom: IsoDateTime;
  userName: string;
  at: IsoDateTime;
  approvedBy: string | null;
}

export interface BulkPricePreviewRow {
  productId: ID;
  sku: string;
  productName: string;
  currentPrice: number;
  newPrice: number;
  marginPct: number | null;
  belowMin: boolean;
}

export type PromotionType = "PRODUCT" | "CATEGORY" | "BOGO" | "ORDER" | "TIME_BASED";
export type PromotionStatus = "DRAFT" | "PENDING_APPROVAL" | "ACTIVE" | "EXPIRED" | "DISABLED";

export interface Promotion {
  id: ID;
  code: string;
  name: string;
  type: PromotionType;
  discountPct: number;
  discountAmount: number;
  productIds: ID[];
  categoryIds: ID[];
  branchIds: ID[];
  customerGroupIds: ID[];
  startDate: string;
  endDate: string;
  startTime: string | null;
  endTime: string | null;
  priority: number;
  combinable: boolean;
  usageLimit: number | null;
  usageCount: number;
  status: PromotionStatus;
  createdBy: string;
  approvedBy: string | null;
}

export interface Coupon {
  id: ID;
  code: string;
  description: string;
  discountPct: number;
  discountAmount: number;
  minSpend: number;
  startDate: string;
  endDate: string;
  usageLimit: number;
  usageCount: number;
  perCustomerLimit: number;
  status: ActiveStatus;
}
