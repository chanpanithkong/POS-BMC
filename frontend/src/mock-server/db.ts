import type {
  AppNotification, AuditLog, Batch, Branch, Brand, CashMovement, CashSession, Category, Company, Coupon, Customer,
  CustomerGroup, DocumentSequence, Employee, ExchangeRate, Expense, ExpenseCategory, GoodsReceipt, ImportBatch,
  InventoryAlert, PaymentMethodConfig, PriceHistoryEntry, PriceList, Product, ProductChange, ProductPrice, Promotion,
  PurchaseOrder, PurchaseReturn, ReceiptTemplate, Refund, Role, Sale, SalesReturn, StockAdjustment, StockBalance,
  StockCount, StockLocation, StockMovement, StockTransfer, Supplier, SupplierInvoice, SystemSettings, TaxCode, Terminal,
  Unit, User, UserSession, Warehouse,
} from "@/types";

/** Demo-only credential fields. A real backend stores Argon2id hashes (FR-AUTH-004). */
export interface UserRecord extends User {
  demoPassword: string;
  demoPin: string | null;
  failedAttempts: string[];
}

export interface ApprovalToken {
  token: string;
  action: string;
  approverId: string;
  approverName: string;
  requesterId: string;
  expiresAt: number;
  used: boolean;
  amount: number;
}

export interface IdempotencyRecord {
  bodyHash: string;
  response: unknown;
  at: number;
}

export interface MockDb {
  schemaVersion: number;
  company: Company;
  branches: Branch[];
  warehouses: Warehouse[];
  locations: StockLocation[];
  terminals: Terminal[];
  taxCodes: TaxCode[];
  exchangeRates: ExchangeRate[];
  paymentMethods: PaymentMethodConfig[];
  sequences: DocumentSequence[];
  sequenceCounters: Record<string, number>;
  receiptTemplates: ReceiptTemplate[];
  settings: SystemSettings;
  roles: Role[];
  users: UserRecord[];
  employees: Employee[];
  sessions: UserSession[];
  auditLogs: AuditLog[];
  categories: Category[];
  brands: Brand[];
  units: Unit[];
  products: Product[];
  productChanges: ProductChange[];
  priceLists: PriceList[];
  prices: ProductPrice[];
  priceHistory: PriceHistoryEntry[];
  promotions: Promotion[];
  coupons: Coupon[];
  customers: Customer[];
  customerGroups: CustomerGroup[];
  sales: Sale[];
  returns: SalesReturn[];
  refunds: Refund[];
  cashSessions: CashSession[];
  cashMovements: CashMovement[];
  balances: StockBalance[];
  movements: StockMovement[];
  movementSeq: number;
  batches: Batch[];
  adjustments: StockAdjustment[];
  transfers: StockTransfer[];
  counts: StockCount[];
  alerts: InventoryAlert[];
  suppliers: Supplier[];
  purchaseOrders: PurchaseOrder[];
  goodsReceipts: GoodsReceipt[];
  supplierInvoices: SupplierInvoice[];
  purchaseReturns: PurchaseReturn[];
  expenseCategories: ExpenseCategory[];
  expenses: Expense[];
  notifications: AppNotification[];
  notificationReads: Record<string, string[]>;
  importBatches: ImportBatch[];
  idempotency: Record<string, IdempotencyRecord>;
  approvalTokens: ApprovalToken[];
  importPreviews: Record<string, { type: string; rows: Record<string, string>[]; fileName: string; fileHash: string }>;
}

export const SCHEMA_VERSION = 1;
const STORAGE_KEY = "pims.mock-db.v1";

let db: MockDb | null = null;
let persistTimer: ReturnType<typeof setTimeout> | null = null;

export function setDb(next: MockDb) {
  db = next;
}

export function peekDb(): MockDb | null {
  return db;
}

export function loadPersisted(): MockDb | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as MockDb;
    return parsed.schemaVersion === SCHEMA_VERSION ? parsed : null;
  } catch {
    return null;
  }
}

export function persistSoon() {
  if (typeof window === "undefined" || !db) return;
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(persistNow, 150);
}

export function persistNow() {
  if (typeof window === "undefined" || !db) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(db));
  } catch {
    // Storage quota reached (for example, many product images): keep working in memory.
    console.warn("Mock database could not be saved to browser storage.");
  }
}

export function resetPersisted() {
  if (typeof window === "undefined") return;
  if (persistTimer) clearTimeout(persistTimer);
  window.localStorage.removeItem(STORAGE_KEY);
  db = null;
}
