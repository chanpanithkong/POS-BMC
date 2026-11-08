import { http, newIdempotencyKey } from "@/lib/api/client";
import type {
  AddPaymentInput, ApprovalAction, ApprovalGrant, AppNotification, AuditLog, AuthResponse, BarcodeRow, Batch, Branch, Brand, BulkPricePreviewRow, CashMovement, CashMovementKind, CashSession, Category, Company, Coupon, CreateReturnInput, Currency, CurrencyAmounts, Customer, CustomerGroup,
  DashboardData, DocumentSequence, Employee, ExchangeRate, Expense, ExpenseCategory, ExpiringBatchRow, GoodsReceipt, ImportBatch, ImportPreview, ImportType, InventoryAlert, ListParams, ListResponse, PaymentMethodConfig, PriceHistoryEntry, PriceList, Product, ProductChange, ProductListItem, ProductPrice, Promotion,
  PurchaseOrder, PurchaseReturn, ReceiptTemplate, ReconciliationResult, Refund, ReorderSuggestion, ReportDefinition, ReportResult, ReturnQuote, Role, Sale, SaleOp, SalePayment, SalesReturn, SessionSummary, SessionUser, StockAdjustment, StockCount, StockLocation, StockMovement, StockOverviewRow, StockTransfer, Supplier,
  SupplierInvoice, SystemSettings, TaxCode, Terminal, Unit, User, UserSession, Warehouse,
} from "@/types";

const items = <T>(response: ListResponse<T>) => response.items;

/** Standard REST resource. Screens use this rather than building URLs. */
function resource<T extends { id: string }, Input = Partial<T>>(path: string) {
  return {
    list: (query?: ListParams) => http.get<ListResponse<T>>(path, query).then(items),
    create: (input: Input) => http.post<T>(path, input),
    update: (id: string, input: Partial<Input>) => http.patch<T>(`${path}/${id}`, input),
    remove: (id: string) => http.delete<void>(`${path}/${id}`),
  };
}

export const authApi = {
  login: (username: string, password: string) => http.post<AuthResponse>("/auth/login", { username, password }),
  pin: (pin: string, terminalId: string) => http.post<AuthResponse>("/auth/pin", { pin, terminalId }),
  logout: () => http.post<void>("/auth/logout"),
  me: () => http.get<SessionUser>("/auth/me"),
  updateMe: (input: Partial<Pick<User, "fullName" | "phone" | "language">>) => http.patch<SessionUser>("/auth/me", input),
  forgotPassword: (email: string) => http.post<{ message: string }>("/auth/forgot-password", { email }),
  changePassword: (currentPassword: string, newPassword: string) => http.post("/auth/change-password", { currentPassword, newPassword }),
  sessions: () => http.get<ListResponse<UserSession>>("/auth/sessions").then(items),
  revokeSession: (id: string) => http.delete<void>(`/auth/sessions/${id}`),
  verifyApproval: (pin: string, action: ApprovalAction, amount: number) => http.post<ApprovalGrant>("/approvals/verify", { pin, action, amount }),
};

export const usersApi = {
  ...resource<User, Partial<User>>("/users"),
  setStatus: (id: string, status: User["status"]) => http.post<User>(`/users/${id}/status`, { status }),
  unlock: (id: string) => http.post<User>(`/users/${id}/unlock`),
  setPin: (id: string, pin: string) => http.post<User>(`/users/${id}/pin`, { pin }),
};
export const rolesApi = resource<Role>("/roles");
export const employeesApi = resource<Employee>("/employees");
export const auditApi = { list: () => http.get<ListResponse<AuditLog>>("/audit-logs").then(items) };

export const companyApi = { get: () => http.get<Company>("/companies/current"), update: (input: Partial<Company>) => http.patch<Company>("/companies/current", input) };
export const settingsApi = { get: () => http.get<SystemSettings>("/settings"), update: (input: Partial<SystemSettings>) => http.patch<SystemSettings>("/settings", input) };
export const branchesApi = resource<Branch>("/branches");
export const warehousesApi = resource<Warehouse>("/warehouses");
export const locationsApi = resource<StockLocation>("/locations");
export const terminalsApi = resource<Terminal>("/terminals");
export const taxCodesApi = resource<TaxCode>("/tax-codes");
export const paymentMethodsApi = resource<PaymentMethodConfig>("/payment-methods");
export const receiptTemplatesApi = resource<ReceiptTemplate>("/receipt-templates");
export const ratesApi = { list: () => http.get<ListResponse<ExchangeRate>>("/currencies/rates").then(items), create: (rate: number) => http.post<ExchangeRate>("/currencies/rates", { rate }) };
export const sequencesApi = { list: () => http.get<ListResponse<DocumentSequence>>("/document-sequences").then(items), update: (id: string, input: Partial<DocumentSequence>) => http.patch<DocumentSequence>(`/document-sequences/${id}`, input) };

export const productsApi = {
  list: (query?: ListParams) => http.get<ListResponse<ProductListItem>>("/products", query).then(items),
  get: (id: string) => http.get<ProductListItem>(`/products/${id}`),
  history: (id: string) => http.get<ListResponse<ProductChange>>(`/products/${id}/history`).then(items),
  create: (input: Partial<Product> & { variants?: { attrs: Record<string, string>; sku: string; barcode?: string }[] }) => http.post<ProductListItem>("/products", input),
  update: (id: string, input: Partial<Product>) => http.patch<ProductListItem>(`/products/${id}`, input),
  remove: (id: string) => http.delete<void>(`/products/${id}`),
  duplicate: (id: string) => http.post<ProductListItem>(`/products/${id}/duplicate`),
  barcodes: () => http.get<ListResponse<BarcodeRow>>("/products/barcodes").then(items),
  generateBarcode: () => http.post<{ barcode: string; symbology: "EAN13" }>("/products/barcodes/generate"),
};
export const categoriesApi = resource<Category>("/categories");
export const brandsApi = resource<Brand>("/brands");
export const unitsApi = resource<Unit>("/units");

export const pricingApi = {
  lists: () => http.get<ListResponse<PriceList>>("/price-lists").then(items),
  prices: () => http.get<ListResponse<ProductPrice>>("/prices").then(items),
  create: (input: Omit<ProductPrice, "id" | "createdBy">) => http.post<ProductPrice>("/prices", input),
  remove: (id: string) => http.delete<void>(`/prices/${id}`),
  history: () => http.get<ListResponse<PriceHistoryEntry>>("/prices/history").then(items),
  bulkPreview: (input: BulkPriceInput) => http.post<ListResponse<BulkPricePreviewRow>>("/prices/bulk/preview", input).then(items),
  bulkApply: (input: BulkPriceInput) => http.post<{ updated: number; scheduled: boolean }>("/prices/bulk", input),
};
export interface BulkPriceInput {
  categoryId?: string;
  brandId?: string;
  mode: "PERCENT" | "AMOUNT";
  value: number;
  effectiveFrom?: string;
}

export const promotionsApi = {
  ...resource<Promotion>("/promotions"),
  approve: (id: string) => http.post<Promotion>(`/promotions/${id}/approve`),
  disable: (id: string) => http.post<Promotion>(`/promotions/${id}/disable`),
};
export const couponsApi = resource<Coupon>("/coupons");

export const salesApi = {
  list: (query?: ListParams) => http.get<ListResponse<Sale>>("/sales", query).then(items),
  held: (query?: ListParams) => http.get<ListResponse<Sale>>("/sales/held", query).then(items),
  current: () => http.get<Sale | null>("/sales/current"),
  get: (id: string) => http.get<Sale>(`/sales/${id}`),
  create: () => http.post<Sale>("/sales", {}, newIdempotencyKey()),
  apply: (id: string, ops: SaleOp[]) => http.patch<Sale>(`/sales/${id}`, { ops }),
  addPayment: (id: string, input: AddPaymentInput, key = newIdempotencyKey()) => http.post<Sale>(`/sales/${id}/payments`, input, key),
  resolvePayment: (id: string, paymentId: string, outcome: "COMPLETED" | "FAILED" | "CANCELLED", reference?: string, reason?: string) =>
    http.post<Sale>(`/sales/${id}/payments/${paymentId}/resolve`, { outcome, reference, reason }),
  finalize: (id: string, key = newIdempotencyKey()) => http.post<Sale>(`/sales/${id}/finalize`, {}, key),
  cancel: (id: string, reason: string, approvalToken?: string) => http.post<Sale>(`/sales/${id}/cancel`, { reason, approvalToken }, newIdempotencyKey()),
  void: (id: string, reason: string, approvalToken?: string) => http.post<Sale>(`/sales/${id}/void`, { reason, approvalToken }, newIdempotencyKey()),
  reprint: (id: string) => http.post<Sale>(`/sales/${id}/reprint`),
  invoice: (id: string) => http.post<Sale>(`/sales/${id}/invoice`),
  quoteReturn: (id: string, input: CreateReturnInput) => http.post<ReturnQuote>(`/sales/${id}/returns/quote`, input),
  createReturn: (id: string, input: CreateReturnInput) => http.post<SalesReturn>(`/sales/${id}/returns`, input, newIdempotencyKey()),
};
export const returnsApi = {
  list: () => http.get<ListResponse<SalesReturn>>("/returns").then(items),
  refunds: () => http.get<ListResponse<Refund>>("/refunds").then(items),
  confirmRefund: (id: string, reference: string) => http.post<SalesReturn>(`/returns/${id}/confirm-refund`, { reference }),
};
export type PaymentRow = SalePayment & { receiptNo: string; branchName: string; businessDate: string };
export const paymentsApi = {
  list: (query?: ListParams) => http.get<ListResponse<PaymentRow>>("/payments", query).then(items),
  reconcile: (id: string, reconciled: boolean) => http.post<SalePayment>(`/payments/${id}/reconcile`, { reconciled }),
};

export const cashSessionsApi = {
  list: (query?: ListParams) => http.get<ListResponse<CashSession>>("/cashier-sessions", query).then(items),
  current: () => http.get<CashSession | null>("/cashier-sessions/current"),
  open: (opening: CurrencyAmounts, witness?: string) => http.post<CashSession>("/cashier-sessions/open", { opening, witness }, newIdempotencyKey()),
  summary: (id: string) => http.get<SessionSummary>(`/cashier-sessions/${id}/summary`),
  addMovement: (id: string, input: { kind: CashMovementKind; currency: Currency; amount: number; reason: string; witness?: string; approvalToken?: string; expenseCategoryId?: string }) => http.post<CashMovement>(`/cashier-sessions/${id}/movements`, input),
  close: (id: string, counted: CurrencyAmounts, denominations?: Record<string, number>) => http.post<CashSession>(`/cashier-sessions/${id}/close`, { counted, denominations }, newIdempotencyKey()),
  approve: (id: string, reason: string) => http.post<CashSession>(`/cashier-sessions/${id}/approve`, { reason }),
  forceClose: (id: string, reason: string) => http.post<CashSession>(`/cashier-sessions/${id}/force-close`, { reason }),
};

export const customersApi = { ...resource<Customer>("/customers"), get: (id: string) => http.get<Customer>(`/customers/${id}`), anonymize: (id: string) => http.post<Customer>(`/customers/${id}/anonymize`) };
export const customerGroupsApi = resource<CustomerGroup>("/customer-groups");

export const inventoryApi = {
  balances: (query?: ListParams) => http.get<ListResponse<StockOverviewRow>>("/inventory/balances", query).then(items),
  movements: (query?: ListParams) => http.get<ListResponse<StockMovement>>("/inventory/movements", query).then(items),
  reverse: (id: number, reason: string) => http.post<StockMovement>(`/inventory/movements/${id}/reverse`, { reason }, newIdempotencyKey()),
  relocate: (input: { productId: string; fromLocationId: string; toLocationId: string; quantity: number; reason?: string }) => http.post<StockMovement>("/inventory/relocations", input, newIdempotencyKey()),
  reconcile: () => http.post<ReconciliationResult>("/inventory/reconciliation"),
  batches: () => http.get<ListResponse<ExpiringBatchRow>>("/inventory/batches").then(items),
  reorderSuggestions: (query?: ListParams) => http.get<ListResponse<ReorderSuggestion>>("/inventory/reorder-suggestions", query).then(items),
};

type DocAction = (id: string, body?: unknown) => Promise<never>;
const action = <T>(path: string) => (id: string, verb: string, body?: unknown) => http.post<T>(`${path}/${id}/${verb}`, body ?? {}, newIdempotencyKey());

export const adjustmentsApi = { ...resource<StockAdjustment, unknown>("/inventory/adjustments"), action: action<StockAdjustment>("/inventory/adjustments") };
export const transfersApi = { list: () => http.get<ListResponse<StockTransfer>>("/inventory/transfers").then(items), create: (input: unknown) => http.post<StockTransfer>("/inventory/transfers", input), action: action<StockTransfer>("/inventory/transfers") };
export const countsApi = {
  list: () => http.get<ListResponse<StockCount>>("/inventory/counts").then(items),
  create: (input: unknown) => http.post<StockCount>("/inventory/counts", input),
  setLines: (id: string, lines: { lineId: string; countedQty?: number | null; reason?: string }[]) => http.patch<StockCount>(`/inventory/counts/${id}/lines`, { lines }),
  action: action<StockCount>("/inventory/counts"),
};
export const alertsApi = {
  list: () => http.get<ListResponse<InventoryAlert>>("/alerts").then(items),
  act: (id: string, input: { action: "ACKNOWLEDGE" | "RESOLVE" | "SNOOZE" | "ASSIGN"; note?: string; assignedTo?: string; days?: number }) => http.post<InventoryAlert>(`/alerts/${id}/action`, input),
  evaluate: () => http.post<{ raised: number }>("/alerts/evaluate"),
};

export const suppliersApi = { ...resource<Supplier>("/suppliers"), get: (id: string) => http.get<Supplier>(`/suppliers/${id}`) };
export const purchaseOrdersApi = { ...resource<PurchaseOrder, unknown>("/purchase-orders"), action: action<PurchaseOrder>("/purchase-orders") };
export const goodsReceiptsApi = { ...resource<GoodsReceipt, unknown>("/goods-receipts"), action: action<GoodsReceipt>("/goods-receipts") };
export const supplierInvoicesApi = { list: () => http.get<ListResponse<SupplierInvoice>>("/supplier-invoices").then(items), create: (input: unknown) => http.post<SupplierInvoice>("/supplier-invoices", input), pay: (id: string, amount: number, reference: string) => http.post<SupplierInvoice>(`/supplier-invoices/${id}/payments`, { amount, reference }) };
export const purchaseReturnsApi = { list: () => http.get<ListResponse<PurchaseReturn>>("/purchase-returns").then(items), create: (input: unknown) => http.post<PurchaseReturn>("/purchase-returns", input), action: action<PurchaseReturn>("/purchase-returns") };

export const expensesApi = { ...resource<Expense, unknown>("/expenses"), action: action<Expense>("/expenses") };
export const expenseCategoriesApi = resource<ExpenseCategory>("/expense-categories");

export const notificationsApi = {
  list: () => http.get<ListResponse<AppNotification>>("/notifications").then(items),
  markRead: (ids?: string[]) => http.post("/notifications/read", { ids }),
};

export const reportsApi = {
  catalog: () => http.get<ListResponse<ReportDefinition>>("/reports").then(items),
  run: (id: string, query: ListParams) => http.get<ReportResult>(`/reports/${id}`, query),
};
export const dashboardApi = { get: (query: ListParams) => http.get<DashboardData>("/dashboard", query) };
export const importsApi = {
  list: () => http.get<ListResponse<ImportBatch>>("/imports").then(items),
  template: (type: ImportType) => http.get<{ columns: string[] }>(`/imports/templates/${type}`),
  preview: (input: { type: ImportType; fileName: string; fileHash: string; rows: Record<string, string>[] }) => http.post<ImportPreview>("/imports/preview", input),
  commit: (token: string) => http.post<ImportBatch>("/imports/commit", { token }, newIdempotencyKey()),
  rollback: (id: string) => http.post<ImportBatch>(`/imports/${id}/rollback`),
};
export const exportsApi = { audit: (name: string, format: string, rows: number) => http.post("/exports/audit", { name, format, rows }) };

export type { Batch, DocAction };
