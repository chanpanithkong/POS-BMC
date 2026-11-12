import type { BusinessDate, ID, IsoDateTime, TimelineEvent } from "./common";
import type { LocationType } from "./organization";

export const MOVEMENT_TYPES = [
  "OPENING",
  "PURCHASE_RECEIPT",
  "PURCHASE_RETURN",
  "SALE",
  "SALE_VOID",
  "SALE_RETURN",
  "TRANSFER_OUT",
  "TRANSFER_RECEIVE",
  "TRANSFER_VARIANCE",
  "ADJUSTMENT_IN",
  "ADJUSTMENT_OUT",
  "COUNT_VARIANCE",
  "DAMAGE",
  "EXPIRY",
  "LOSS",
  "WRITE_OFF",
  "RELOCATION",
  "REVERSAL",
] as const;
export type MovementType = (typeof MOVEMENT_TYPES)[number];

export interface StockBalance {
  locationId: ID;
  productId: ID;
  onHand: number;
  reserved: number;
}

export interface StockOverviewRow {
  productId: ID;
  sku: string;
  productName: string;
  categoryId: ID;
  categoryName: string;
  unitCode: string;
  onHand: number;
  reserved: number;
  available: number;
  onOrder: number;
  inTransit: number;
  reorderLevel: number;
  maxLevel: number;
  avgCost?: number;
  value?: number;
  status: "IN_STOCK" | "LOW" | "OUT" | "NEGATIVE" | "OVER";
  byLocation: {
    locationId: ID;
    locationName: string;
    locationType: LocationType;
    warehouseId: ID;
    warehouseName: string;
    branchId: ID | null;
    onHand: number;
    reserved: number;
  }[];
}

export interface StockMovement {
  id: number;
  branchId: ID | null;
  warehouseId: ID;
  productId: ID;
  sku: string;
  productName: string;
  fromLocationId: ID | null;
  toLocationId: ID | null;
  fromLocationName: string | null;
  toLocationName: string | null;
  type: MovementType;
  quantityBase: number;
  unitCode: string;
  quantityEntered: number;
  unitCost?: number;
  totalCost?: number;
  batchNo: string | null;
  businessDate: BusinessDate;
  postedAt: IsoDateTime;
  sourceType: string;
  sourceId: ID;
  sourceNo: string;
  reasonCode: string | null;
  reversesMovementId: number | null;
  reversedByMovementId: number | null;
  approvedBy: string | null;
  userId: ID;
  userName: string;
  /** Signed effect for the row in the running-balance view, filled by the movement list API. */
  runningBalance?: number | null;
}

export interface Batch {
  id: ID;
  productId: ID;
  locationId: ID;
  batchNo: string;
  expiryDate: string;
  quantity: number;
  receiptId: ID;
}

export interface ExpiringBatchRow extends Batch {
  sku: string;
  productName: string;
  locationName: string;
  warehouseName: string;
  daysToExpiry: number;
  value?: number;
}

export type DocumentFlowStatus =
  | "DRAFT"
  | "SUBMITTED"
  | "APPROVED"
  | "REJECTED"
  | "POSTED"
  | "CANCELLED";

export const ADJUSTMENT_REASONS = [
  "DAMAGED",
  "EXPIRED",
  "LOST",
  "FOUND",
  "DATA_CORRECTION",
  "INTERNAL_USE",
  "WRITE_OFF",
] as const;
export type AdjustmentReason = (typeof ADJUSTMENT_REASONS)[number];

export interface AdjustmentLine {
  id: ID;
  productId: ID;
  sku: string;
  productName: string;
  locationId: ID;
  locationName: string;
  quantity: number;
  unitCode: string;
  reason: AdjustmentReason;
  notes: string;
  unitCost?: number;
  valueImpact?: number;
}

export interface StockAdjustment {
  id: ID;
  adjustmentNo: string;
  warehouseId: ID;
  warehouseName: string;
  branchId: ID | null;
  status: DocumentFlowStatus;
  lines: AdjustmentLine[];
  notes: string;
  attachment: string | null;
  totalValue?: number;
  requiresApproval: boolean;
  createdBy: string;
  createdById: ID;
  approvedBy: string | null;
  createdAt: IsoDateTime;
  postedAt: IsoDateTime | null;
  timeline: TimelineEvent[];
}

export type TransferStatus =
  | "REQUESTED"
  | "APPROVED"
  | "DISPATCHED"
  | "PARTIALLY_RECEIVED"
  | "RECEIVED"
  | "CLOSED"
  | "CANCELLED";

export interface TransferLine {
  id: ID;
  productId: ID;
  sku: string;
  productName: string;
  unitCode: string;
  quantityRequested: number;
  quantityDispatched: number;
  quantityReceived: number;
  quantityShort: number;
  quantityDamaged: number;
  quantityExcess: number;
}

export interface StockTransfer {
  id: ID;
  transferNo: string;
  sourceWarehouseId: ID;
  sourceWarehouseName: string;
  destinationWarehouseId: ID;
  destinationWarehouseName: string;
  status: TransferStatus;
  reason: string;
  lines: TransferLine[];
  value?: number;
  createdBy: string;
  createdById: ID;
  approvedBy: string | null;
  createdAt: IsoDateTime;
  dispatchedAt: IsoDateTime | null;
  receivedAt: IsoDateTime | null;
  timeline: TimelineEvent[];
}

export type CountStatus = "OPEN" | "COUNTING" | "REVIEW" | "APPROVED" | "POSTED" | "CANCELLED";

export interface StockCountLine {
  id: ID;
  locationId: ID;
  locationName: string;
  productId: ID;
  sku: string;
  productName: string;
  unitCode: string;
  /** Hidden in blind mode until submission. */
  snapshotQty: number | null;
  countedQty: number | null;
  countedAt: IsoDateTime | null;
  countedBy: string | null;
  variance: number | null;
  valueVariance?: number | null;
  reason: string;
  recountRequired: boolean;
}

export interface StockCount {
  id: ID;
  countNo: string;
  warehouseId: ID;
  warehouseName: string;
  scope: "FULL" | "CYCLE_CATEGORY" | "CYCLE_LOCATION" | "CYCLE_RANDOM";
  scopeLabel: string;
  freeze: boolean;
  blind: boolean;
  status: CountStatus;
  lines: StockCountLine[];
  createdBy: string;
  createdById: ID;
  approvedBy: string | null;
  createdAt: IsoDateTime;
  postedAt: IsoDateTime | null;
  timeline: TimelineEvent[];
}

export type AlertType =
  | "LOW_STOCK"
  | "OUT_OF_STOCK"
  | "OVERSTOCK"
  | "NEGATIVE_STOCK"
  | "EXPIRING"
  | "EXPIRED"
  | "SLOW_MOVING"
  | "UNUSUAL_ADJUSTMENT";
export type AlertStatus = "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "SNOOZED";

export interface InventoryAlert {
  id: ID;
  type: AlertType;
  productId: ID;
  sku: string;
  productName: string;
  warehouseId: ID | null;
  warehouseName: string;
  branchId: ID | null;
  message: string;
  status: AlertStatus;
  assignedTo: string | null;
  snoozedUntil: IsoDateTime | null;
  note: string | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface ReorderSuggestion {
  productId: ID;
  sku: string;
  productName: string;
  warehouseId: ID;
  warehouseName: string;
  available: number;
  onOrder: number;
  maxLevel: number;
  suggestedBase: number;
  purchaseUnitId: ID;
  purchaseUnitCode: string;
  purchaseFactor: number;
  suggestedQty: number;
  supplierId: ID | null;
  supplierName: string;
  cost?: number;
  leadTimeDays: number;
}

export interface ReconciliationResult {
  checkedAt: IsoDateTime;
  balancesChecked: number;
  differences: { sku: string; location: string; balance: number; movementSum: number }[];
}
