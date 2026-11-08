import type { ActiveStatus, Currency, ID, IsoDateTime, TimelineEvent } from "./common";

export interface SupplierContact {
  id: ID;
  name: string;
  position: string;
  phone: string;
  email: string;
}

export interface Supplier {
  id: ID;
  code: string;
  nameEn: string;
  nameKm: string;
  taxId: string;
  phone: string;
  email: string;
  address: string;
  paymentTerms: string;
  currency: Currency;
  leadTimeDays: number;
  status: ActiveStatus;
  contacts: SupplierContact[];
  // Derived by the API.
  openPoCount?: number;
  onTimeRate?: number | null;
  fillRate?: number | null;
  outstandingBalance?: number;
}

export type PoStatus =
  | "DRAFT"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "SENT"
  | "PARTIALLY_RECEIVED"
  | "RECEIVED"
  | "CANCELLED"
  | "SHORT_CLOSED";

export interface PurchaseOrderLine {
  id: ID;
  productId: ID;
  sku: string;
  productName: string;
  supplierSku: string;
  unitId: ID;
  unitCode: string;
  factor: number;
  quantity: number;
  quantityBase: number;
  unitCost: number;
  taxRate: number;
  lineTotal: number;
  receivedBase: number;
  cancelledBase: number;
}

export interface PurchaseOrder {
  id: ID;
  poNo: string;
  supplierId: ID;
  supplierName: string;
  warehouseId: ID;
  warehouseName: string;
  branchId: ID | null;
  expectedDate: string;
  status: PoStatus;
  notes: string;
  lines: PurchaseOrderLine[];
  subtotal: number;
  taxTotal: number;
  total: number;
  createdBy: string;
  createdById: ID;
  approvedBy: string | null;
  createdAt: IsoDateTime;
  sentAt: IsoDateTime | null;
  firstReceivedAt: IsoDateTime | null;
  timeline: TimelineEvent[];
}

export type GrnStatus = "DRAFT" | "PENDING_APPROVAL" | "POSTED";

export interface GoodsReceiptLine {
  id: ID;
  poLineId: ID | null;
  productId: ID;
  sku: string;
  productName: string;
  unitId: ID;
  unitCode: string;
  factor: number;
  orderedOpen: number;
  quantityReceived: number;
  quantityDamaged: number;
  quantityRejected: number;
  unitCost: number;
  batchNo: string;
  expiryDate: string;
  trackExpiry: boolean;
}

export interface GoodsReceipt {
  id: ID;
  receiptNo: string;
  poId: ID | null;
  poNo: string | null;
  supplierId: ID;
  supplierName: string;
  warehouseId: ID;
  warehouseName: string;
  branchId: ID | null;
  status: GrnStatus;
  blind: boolean;
  exceptionReason: string | null;
  deliveryNote: string;
  invoiceRef: string;
  lines: GoodsReceiptLine[];
  discrepancies: string[];
  totalCost?: number;
  createdBy: string;
  createdById: ID;
  approvedBy: string | null;
  postedBy: string | null;
  postedAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  flaggedForReview: boolean;
}

export type SupplierInvoiceStatus = "RECORDED" | "MATCHED" | "MISMATCH" | "PAID" | "PARTIALLY_PAID";

export interface SupplierPayment {
  id: ID;
  amount: number;
  reference: string;
  paidAt: IsoDateTime;
  by: string;
}

export interface SupplierInvoice {
  id: ID;
  invoiceNo: string;
  supplierId: ID;
  supplierName: string;
  poId: ID | null;
  poNo: string | null;
  invoiceDate: string;
  dueDate: string;
  amount: number;
  paidAmount: number;
  status: SupplierInvoiceStatus;
  matchNotes: string;
  payments: SupplierPayment[];
  createdBy: string;
  createdAt: IsoDateTime;
}

export type PurchaseReturnStatus = "DRAFT" | "APPROVED" | "DISPATCHED" | "CREDITED";

export interface PurchaseReturnLine {
  id: ID;
  productId: ID;
  sku: string;
  productName: string;
  locationId: ID;
  locationName: string;
  quantityBase: number;
  unitCost: number;
  total: number;
}

export interface PurchaseReturn {
  id: ID;
  returnNo: string;
  supplierId: ID;
  supplierName: string;
  goodsReceiptId: ID;
  goodsReceiptNo: string;
  warehouseId: ID;
  status: PurchaseReturnStatus;
  reason: string;
  lines: PurchaseReturnLine[];
  total: number;
  creditNoteRef: string | null;
  createdBy: string;
  createdById: ID;
  approvedBy: string | null;
  createdAt: IsoDateTime;
}
