import type { ActiveStatus, Currency, ID, IsoDateTime } from "./common";

export interface ExpenseCategory {
  id: ID;
  code: string;
  name: string;
  status: ActiveStatus;
}

export type ExpenseStatus = "SUBMITTED" | "APPROVED" | "REJECTED";

export interface Expense {
  id: ID;
  expenseNo: string;
  date: string;
  categoryId: ID;
  categoryName: string;
  description: string;
  amount: number;
  currency: Currency;
  amountBase: number;
  paymentMethod: string;
  branchId: ID;
  branchName: string;
  attachment: string | null;
  status: ExpenseStatus;
  rejectReason: string | null;
  sessionId: ID | null;
  createdBy: string;
  createdById: ID;
  approvedBy: string | null;
  createdAt: IsoDateTime;
}

export type NotificationKind =
  | "STOCK_ALERT"
  | "PO_APPROVAL"
  | "RECEIPT_DISCREPANCY"
  | "TRANSFER"
  | "REFUND_APPROVAL"
  | "SESSION_REMINDER"
  | "SYSTEM_ERROR"
  | "APPROVAL";

export interface AppNotification {
  id: ID;
  kind: NotificationKind;
  title: string;
  message: string;
  link: string | null;
  read: boolean;
  createdAt: IsoDateTime;
  /** Recipient resolution by permission and branch scope. */
  audiencePermission: string | null;
  branchId: ID | null;
}

export type ImportType = "PRODUCTS" | "BARCODES" | "SUPPLIERS" | "CUSTOMERS" | "OPENING_STOCK" | "PRICES" | "STOCK_COUNT";

export interface ImportError {
  row: number;
  field: string;
  value: string;
  message: string;
}

export interface ImportPreview {
  type: ImportType;
  fileName: string;
  totalRows: number;
  validRows: number;
  errors: ImportError[];
  sample: Record<string, string>[];
  columns: string[];
  token: string;
}

export interface ImportBatch {
  id: ID;
  type: ImportType;
  fileName: string;
  fileHash: string;
  userName: string;
  at: IsoDateTime;
  totalRows: number;
  importedRows: number;
  status: "COMMITTED" | "ROLLED_BACK";
  createdIds: ID[];
  canRollback: boolean;
}

export interface ReportColumn {
  key: string;
  label: string;
  type: "text" | "money" | "number" | "percent" | "date" | "datetime";
}

export type ReportCell = string | number | null;
export type ReportRow = Record<string, ReportCell>;

export interface ReportCheck {
  label: string;
  expected: number;
  actual: number;
  passed: boolean;
}

export interface ReportChartSpec {
  type: "bar" | "line" | "pie";
  xKey: string;
  series: { key: string; label: string }[];
}

export type ReportFilterKey =
  | "dateRange"
  | "asOf"
  | "month"
  | "branch"
  | "warehouse"
  | "category"
  | "terminal"
  | "cashier"
  | "paymentMethod"
  | "supplier";

export interface ReportDefinition {
  id: string;
  name: string;
  group: "Sales" | "Inventory" | "Purchasing" | "Cash" | "Business" | "Control";
  purpose: string;
  permission: string;
  needsCost: boolean;
  filters: ReportFilterKey[];
}

export interface ReportResult {
  definition: ReportDefinition;
  basis: string;
  columns: ReportColumn[];
  rows: ReportRow[];
  totals: ReportRow | null;
  chart: ReportChartSpec | null;
  checks: ReportCheck[];
  generatedAt: IsoDateTime;
  generatedBy: string;
}

export interface KpiValue {
  key: string;
  label: string;
  value: number;
  format: "money" | "number" | "percent";
  definition: string;
  href: string;
  previous: number | null;
  needsCost: boolean;
}

export interface DashboardData {
  variant: "OWNER" | "MANAGER" | "INVENTORY" | "CASHIER" | "PURCHASING" | "BASIC";
  kpis: KpiValue[];
  trend: { date: string; netSales: number; grossProfit?: number; transactions: number }[];
  byCategory: { name: string; netSales: number }[];
  byPayment: { name: string; amount: number }[];
  branchComparison: { name: string; netSales: number; grossProfit?: number; transactions: number }[];
  topProducts: { rank: number; productId: string; sku: string; name: string; quantity: number; netSales: number; grossProfit?: number }[];
  slowProducts: { productId: string; sku: string; name: string; onHand: number; soldQty: number }[];
  byCashier: { name: string; netSales: number; transactions: number }[];
  byTerminal: { name: string; netSales: number; transactions: number }[];
  recentTransactions: { id: string; receiptNo: string; at: string; customer: string; total: number; status: string; paymentStatus: string }[];
  alerts: { id: string; type: string; message: string; productName: string }[];
  approvals: { id: string; kind: string; label: string; href: string }[];
  summaries: { label: string; netSales: number; transactions: number; grossProfit?: number }[];
  cashier: null | {
    shift: string;
    terminal: string;
    status: string;
    salesCompleted: number;
    cashReceived: number;
    pending: number;
    sessionId: string | null;
  };
}
