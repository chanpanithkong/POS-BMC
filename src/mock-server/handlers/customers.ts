import type { AppNotification, Customer, Expense, ExpenseCategory, ImportBatch, ImportError, ImportPreview, ImportType, Product } from "@/types";
import {
  allowedBranchIds, assertNotSelfApproval, audit, badState, branchFilter, can, fail, list, nextDocNo, notFound, requirePerm, requireUser, round, uid, validation, type Ctx,
} from "../core";
import { applyWac, getProduct, postMovement } from "../domain/inventory";
import { createProduct } from "./catalog";
import { DELETE, GET, PATCH, POST, assertUniqueCode, crud } from "../registry";
import { detectSymbology, validateBarcode } from "@/lib/barcode";

// Customers
function mask(phone: string) {
  return phone.length > 4 ? `${"*".repeat(phone.length - 3)}${phone.slice(-3)}` : "***";
}

function customerView(ctx: Ctx, customer: Customer): Customer {
  const view = { ...customer, groupName: ctx.db.customerGroups.find((g) => g.id === customer.groupId)?.name ?? "" };
  if (can(ctx, "customers.personal_data")) return view;
  return { ...view, phone: mask(view.phone), email: view.email ? "***" : "", address: view.address ? "***" : "", notes: "" };
}

function validateCustomer(ctx: Ctx, input: Partial<Customer>, existing: Customer | null) {
  assertUniqueCode(ctx.db.customers, input.code, existing);
  if (input.name !== undefined && !input.name.trim()) validation("name", "Name is required.");
  if (input.phone !== undefined) {
    if (!/^(\+855|0)\d{8,9}$/.test(input.phone.replace(/\s/g, ""))) validation("phone", "Enter a phone number in +855 or local format.");
    if (ctx.db.customers.some((c) => c.phone.replace(/\s/g, "") === input.phone?.replace(/\s/g, "") && c.id !== existing?.id && !c.anonymized)) {
      fail(422, "DUPLICATE_PHONE", "A customer with this phone already exists", [{ field: "phone", message: "A customer with this phone already exists" }]);
    }
  }
}

function newCustomer(ctx: Ctx, input: Partial<Customer>): Customer {
  const code = input.code?.trim() || `C${String(ctx.db.customers.length + 1).padStart(5, "0")}`;
  return {
    id: uid("cus"), code, name: input.name ?? "", phone: input.phone ?? "", email: input.email ?? "", address: input.address ?? "", groupId: input.groupId ?? null, notes: input.notes ?? "",
    consentMarketing: input.consentMarketing ?? false, loyaltyPoints: 0, tier: "Member", storeCredit: 0, creditLimit: input.creditLimit ?? 0, lastPurchaseAt: null, totalSpent: 0, status: "ACTIVE", anonymized: false, createdAt: ctx.now.toISOString(),
  };
}

GET("/customers", (ctx) => {
  requirePerm(ctx, "customers.view", "pos.sell");
  return list(ctx.db.customers.filter((c) => !c.anonymized).map((c) => customerView(ctx, c)));
});
GET("/customers/:id", (ctx) => {
  requirePerm(ctx, "customers.view");
  const customer = ctx.db.customers.find((c) => c.id === ctx.params.id);
  return customer ? customerView(ctx, customer) : notFound("Customer");
});
POST("/customers", (ctx) => {
  requirePerm(ctx, "customers.manage");
  const input = ctx.body as Partial<Customer>;
  validateCustomer(ctx, input, null);
  const customer = newCustomer(ctx, input);
  ctx.db.customers.unshift(customer);
  audit(ctx, "CUSTOMER_CREATED", "CUS", "customer", customer.id);
  return customerView(ctx, customer);
});
PATCH("/customers/:id", (ctx) => {
  requirePerm(ctx, "customers.manage");
  const customer = ctx.db.customers.find((c) => c.id === ctx.params.id);
  if (!customer) return notFound("Customer");
  const input = ctx.body as Partial<Customer>;
  validateCustomer(ctx, input, customer);
  const { loyaltyPoints: _l, storeCredit: _s, totalSpent: _t, ...patch } = input;
  void _l; void _s; void _t;
  Object.assign(customer, patch);
  audit(ctx, "CUSTOMER_UPDATED", "CUS", "customer", customer.id);
  return customerView(ctx, customer);
});
POST("/customers/:id/anonymize", (ctx) => {
  requirePerm(ctx, "customers.personal_data");
  const customer = ctx.db.customers.find((c) => c.id === ctx.params.id);
  if (!customer) return notFound("Customer");
  Object.assign(customer, { name: "Anonymised customer", phone: "", email: "", address: "", notes: "", consentMarketing: false, anonymized: true, status: "INACTIVE" });
  ctx.db.sales.filter((s) => s.customerId === customer.id).forEach((s) => (s.customerName = "Anonymised customer"));
  audit(ctx, "CUSTOMER_ANONYMISED", "CUS", "customer", customer.id, { flagged: true });
  return customer;
});
DELETE("/customers/:id", (ctx) => {
  requirePerm(ctx, "customers.manage");
  if (ctx.db.sales.some((s) => s.customerId === ctx.params.id)) return fail(409, "IN_USE", "This customer has sales history. Deactivate or anonymise instead.");
  ctx.db.customers = ctx.db.customers.filter((c) => c.id !== ctx.params.id);
  audit(ctx, "CUSTOMER_DELETED", "CUS", "customer", ctx.params.id);
  return undefined;
});

// Expenses (kept separate from COGS and inventory, FR-EXP-006)
crud<ExpenseCategory>("/expense-categories", "expenseCategories", {
  view: ["expenses.view", "cash.session.open"],
  manage: ["expenses.approve", "settings.manage"],
  prefix: "exc",
  module: "EXP",
  validate: (ctx, input, existing) => assertUniqueCode(ctx.db.expenseCategories, input.code, existing),
  beforeDelete: (ctx, row) => {
    if (ctx.db.expenses.some((e) => e.categoryId === row.id)) fail(409, "IN_USE", "Expenses use this category.");
  },
});

const getExpense = (ctx: Ctx, id: string): Expense => ctx.db.expenses.find((e) => e.id === id) ?? (notFound("Expense") as never);

GET("/expenses", (ctx) => {
  requirePerm(ctx, "expenses.view");
  const inBranch = branchFilter(ctx);
  return list(ctx.db.expenses.filter((e) => inBranch(e.branchId)));
});

type ExpenseInput = Pick<Expense, "date" | "categoryId" | "description" | "amount" | "currency" | "paymentMethod" | "branchId"> & { attachment?: string | null };

function checkExpense(ctx: Ctx, input: ExpenseInput) {
  if (!(input.amount > 0)) validation("amount", "Amount must be greater than zero.");
  if (!allowedBranchIds(ctx).includes(input.branchId)) validation("branchId", "Select one of your branches.");
  const base = input.currency === "KHR" ? input.amount / (ctx.db.exchangeRates[0]?.rate ?? 4100) : input.amount;
  if (base > ctx.db.settings.expenseAttachmentThreshold && !input.attachment) validation("attachment", `A supporting document is required above ${ctx.db.settings.expenseAttachmentThreshold} USD.`);
  return round(base, 2);
}

POST("/expenses", (ctx) => {
  requirePerm(ctx, "expenses.create");
  const user = requireUser(ctx);
  const input = ctx.body as ExpenseInput;
  const base = checkExpense(ctx, input);
  const auto = base <= ctx.db.settings.expenseApprovalThreshold;
  const branch = ctx.db.branches.find((b) => b.id === input.branchId);
  const expense: Expense = {
    id: uid("exp"), expenseNo: nextDocNo(ctx, "EXPENSE", branch?.code), date: input.date, categoryId: input.categoryId, categoryName: ctx.db.expenseCategories.find((c) => c.id === input.categoryId)?.name ?? "", description: input.description,
    amount: input.amount, currency: input.currency, amountBase: base, paymentMethod: input.paymentMethod, branchId: input.branchId, branchName: branch?.nameEn ?? "", attachment: input.attachment ?? null, status: auto ? "APPROVED" : "SUBMITTED",
    rejectReason: null, sessionId: null, createdBy: user.fullName, createdById: user.id, approvedBy: auto ? "Auto-approved within limit" : null, createdAt: ctx.now.toISOString(),
  };
  ctx.db.expenses.unshift(expense);
  audit(ctx, "EXPENSE_RECORDED", "EXP", "expense", expense.id, { after: { amount: base }, branchId: expense.branchId });
  return expense;
});

PATCH("/expenses/:id", (ctx) => {
  requirePerm(ctx, "expenses.create");
  const expense = getExpense(ctx, ctx.params.id);
  if (expense.status === "APPROVED" && expense.approvedBy !== "Auto-approved within limit") return badState("An approved expense cannot be edited.");
  const input = { ...expense, ...(ctx.body as Partial<ExpenseInput>) };
  const base = checkExpense(ctx, input);
  const auto = base <= ctx.db.settings.expenseApprovalThreshold;
  Object.assign(expense, input, { amountBase: base, status: auto ? "APPROVED" : "SUBMITTED", approvedBy: auto ? "Auto-approved within limit" : null, rejectReason: null, categoryName: ctx.db.expenseCategories.find((c) => c.id === input.categoryId)?.name ?? "", branchName: ctx.db.branches.find((b) => b.id === input.branchId)?.nameEn ?? "" });
  audit(ctx, "EXPENSE_UPDATED", "EXP", "expense", expense.id, { branchId: expense.branchId });
  return expense;
});

POST("/expenses/:id/approve", (ctx) => {
  requirePerm(ctx, "expenses.approve");
  const expense = getExpense(ctx, ctx.params.id);
  if (expense.status !== "SUBMITTED") return badState("Only a submitted expense can be approved.");
  assertNotSelfApproval(ctx, expense.createdById, "expense");
  expense.status = "APPROVED";
  expense.approvedBy = requireUser(ctx).fullName;
  audit(ctx, "EXPENSE_APPROVED", "EXP", "expense", expense.id, { branchId: expense.branchId });
  return expense;
});

POST("/expenses/:id/reject", (ctx) => {
  requirePerm(ctx, "expenses.approve");
  const expense = getExpense(ctx, ctx.params.id);
  if (expense.status !== "SUBMITTED") return badState("Only a submitted expense can be rejected.");
  const { reason } = ctx.body as { reason: string };
  if (!reason?.trim()) return validation("reason", "A rejection reason is required.");
  expense.status = "REJECTED";
  expense.rejectReason = reason.trim();
  return expense;
});

DELETE("/expenses/:id", (ctx) => {
  requirePerm(ctx, "expenses.create");
  const expense = getExpense(ctx, ctx.params.id);
  if (expense.status !== "REJECTED" && expense.status !== "SUBMITTED") return badState("Only unapproved expenses can be deleted.");
  ctx.db.expenses = ctx.db.expenses.filter((e) => e.id !== expense.id);
  audit(ctx, "EXPENSE_DELETED", "EXP", "expense", expense.id);
  return undefined;
});

// Notifications
function visibleNotifications(ctx: Ctx): (AppNotification & { read: boolean })[] {
  const user = requireUser(ctx);
  const scope = new Set(allowedBranchIds(ctx));
  const read = new Set(ctx.db.notificationReads[user.id] ?? []);
  return ctx.db.notifications
    .filter((n) => (!n.audiencePermission || ctx.permissions.has(n.audiencePermission as never)) && (!n.branchId || scope.has(n.branchId)))
    .slice(0, 200)
    .map((n) => ({ ...n, read: read.has(n.id) }));
}

GET("/notifications", (ctx) => list(visibleNotifications(ctx)));

POST("/notifications/read", (ctx) => {
  const user = requireUser(ctx);
  const { ids } = ctx.body as { ids?: string[] };
  const targets = ids ?? visibleNotifications(ctx).map((n) => n.id);
  ctx.db.notificationReads[user.id] = [...new Set([...(ctx.db.notificationReads[user.id] ?? []), ...targets])];
  return { ok: true };
});

// Imports (two-phase, BR-IMP-001)
const COLUMNS: Record<ImportType, string[]> = {
  PRODUCTS: ["sku", "name_en", "name_km", "category", "brand", "base_unit", "tax_code", "status", "retail_price", "wholesale_price"],
  BARCODES: ["sku", "barcode", "unit"],
  SUPPLIERS: ["code", "name", "currency", "phone"],
  CUSTOMERS: ["code", "name", "phone"],
  OPENING_STOCK: ["warehouse", "location", "sku", "quantity", "unit", "unit_cost"],
  PRICES: ["sku", "unit", "price_list", "branch", "price", "effective_from"],
  STOCK_COUNT: ["count_no", "location", "sku", "counted_quantity", "unit"],
};

const REQUIRED: Record<ImportType, string[]> = {
  PRODUCTS: ["sku", "name_en", "category", "base_unit", "tax_code", "status"],
  BARCODES: ["sku", "barcode", "unit"],
  SUPPLIERS: ["code", "name", "currency"],
  CUSTOMERS: ["code", "name", "phone"],
  OPENING_STOCK: ["warehouse", "location", "sku", "quantity", "unit", "unit_cost"],
  PRICES: ["sku", "unit", "price_list", "price", "effective_from"],
  STOCK_COUNT: ["count_no", "location", "sku", "counted_quantity"],
};

GET("/imports/templates/:type", (ctx) => {
  requirePerm(ctx, "imports.manage");
  return { columns: COLUMNS[ctx.params.type as ImportType] ?? [] };
});

function validateRows(ctx: Ctx, type: ImportType, rows: Record<string, string>[]) {
  const { db } = ctx;
  const errors: ImportError[] = [];
  const seen = new Set<string>();
  const err = (row: number, field: string, value: string, message: string) => errors.push({ row, field, value, message });
  const number = (i: number, field: string, value: string) => {
    if (value !== "" && !Number.isFinite(Number(value))) err(i, field, value, "Must be a number.");
  };
  rows.forEach((row, index) => {
    const i = index + 2;
    for (const field of REQUIRED[type]) if (!row[field]?.trim()) err(i, field, row[field] ?? "", "Required field is empty.");
    const dup = (key: string, field: string, value: string) => {
      if (seen.has(key)) err(i, field, value, "Duplicate within this file.");
      seen.add(key);
    };
    if (type === "PRODUCTS") {
      dup(`sku:${row.sku}`, "sku", row.sku);
      if (db.products.some((p) => p.sku === row.sku)) err(i, "sku", row.sku, "SKU already exists.");
      if (row.category && !db.categories.some((c) => c.code === row.category || c.nameEn === row.category)) err(i, "category", row.category, "Unknown category.");
      if (row.base_unit && !db.units.some((u) => u.code === row.base_unit)) err(i, "base_unit", row.base_unit, "Unknown unit.");
      if (row.tax_code && row.tax_code !== "EXEMPT" && !db.taxCodes.some((t) => t.code === row.tax_code)) err(i, "tax_code", row.tax_code, "Unknown tax code.");
      if (row.status && !["DRAFT", "ACTIVE", "INACTIVE", "DISCONTINUED"].includes(row.status)) err(i, "status", row.status, "Unknown status.");
      number(i, "retail_price", row.retail_price ?? "");
    }
    if (type === "BARCODES") {
      dup(`bc:${row.barcode}`, "barcode", row.barcode);
      const message = row.barcode ? validateBarcode(row.barcode, detectSymbology(row.barcode)) : null;
      if (message) err(i, "barcode", row.barcode, message);
      if (db.products.some((p) => p.barcodes.some((b) => b.active && b.barcode === row.barcode))) err(i, "barcode", row.barcode, "Barcode already in use.");
      if (row.sku && !db.products.some((p) => p.sku === row.sku)) err(i, "sku", row.sku, "Unknown SKU.");
      if (row.unit && !db.units.some((u) => u.code === row.unit)) err(i, "unit", row.unit, "Unknown unit.");
    }
    if (type === "SUPPLIERS") {
      dup(`c:${row.code}`, "code", row.code);
      if (db.suppliers.some((s) => s.code === row.code)) err(i, "code", row.code, "Supplier code already exists.");
      if (row.currency && !["USD", "KHR"].includes(row.currency)) err(i, "currency", row.currency, "Currency must be USD or KHR.");
    }
    if (type === "CUSTOMERS") {
      dup(`c:${row.code}`, "code", row.code);
      dup(`p:${row.phone}`, "phone", row.phone);
      if (db.customers.some((s) => s.code === row.code)) err(i, "code", row.code, "Customer code already exists.");
      if (db.customers.some((s) => s.phone === row.phone)) err(i, "phone", row.phone, "A customer with this phone already exists.");
    }
    if (type === "OPENING_STOCK") {
      dup(`${row.sku}:${row.location}`, "sku", row.sku);
      const warehouse = db.warehouses.find((w) => w.code === row.warehouse);
      if (row.warehouse && !warehouse) err(i, "warehouse", row.warehouse, "Unknown warehouse.");
      const location = db.locations.find((l) => l.code === row.location && l.warehouseId === warehouse?.id);
      if (row.location && !location) err(i, "location", row.location, "Unknown location in this warehouse.");
      const product = db.products.find((p) => p.sku === row.sku);
      if (row.sku && !product) err(i, "sku", row.sku, "Unknown SKU.");
      if (product && location && db.movements.some((m) => m.type === "OPENING" && m.productId === product.id && m.toLocationId === location.id)) err(i, "sku", row.sku, "Opening stock already posted for this location.");
      number(i, "quantity", row.quantity ?? "");
      number(i, "unit_cost", row.unit_cost ?? "");
      if (product && !product.allowFraction && row.quantity && !Number.isInteger(Number(row.quantity))) err(i, "quantity", row.quantity, "Must be a whole number for this unit.");
    }
    if (type === "PRICES") {
      dup(`${row.sku}:${row.unit}:${row.price_list}:${row.branch}`, "sku", row.sku);
      if (row.sku && !db.products.some((p) => p.sku === row.sku)) err(i, "sku", row.sku, "Unknown SKU.");
      if (row.unit && !db.units.some((u) => u.code === row.unit)) err(i, "unit", row.unit, "Unknown unit.");
      if (row.price_list && !db.priceLists.some((l) => l.code === row.price_list)) err(i, "price_list", row.price_list, "Unknown price list.");
      if (row.branch && !db.branches.some((b) => b.code === row.branch)) err(i, "branch", row.branch, "Unknown branch.");
      number(i, "price", row.price ?? "");
      if (row.effective_from && Number.isNaN(new Date(row.effective_from).getTime())) err(i, "effective_from", row.effective_from, "Not a valid date.");
    }
    if (type === "STOCK_COUNT") {
      dup(`${row.sku}:${row.location}`, "sku", row.sku);
      const count = db.counts.find((c) => c.countNo === row.count_no);
      if (row.count_no && !count) err(i, "count_no", row.count_no, "Unknown stock count.");
      if (count && !["OPEN", "COUNTING"].includes(count.status)) err(i, "count_no", row.count_no, "This count is not open.");
      if (count && !count.lines.some((l) => l.sku === row.sku && db.locations.find((x) => x.id === l.locationId)?.code === row.location)) err(i, "sku", row.sku, "Not part of this count.");
      number(i, "counted_quantity", row.counted_quantity ?? "");
    }
  });
  return errors;
}

POST("/imports/preview", (ctx): ImportPreview => {
  requirePerm(ctx, "imports.manage");
  const { type, fileName, fileHash, rows } = ctx.body as { type: ImportType; fileName: string; fileHash: string; rows: Record<string, string>[] };
  if (!rows?.length) return validation("file", "The file has no data rows.") as never;
  if (rows.length > 50000) return validation("file", "The file exceeds 50,000 rows.") as never;
  const missing = REQUIRED[type].filter((c) => !(c in rows[0]));
  if (missing.length) return validation("file", `Missing column(s): ${missing.join(", ")}. Download the template for the correct format.`) as never;
  const errors = validateRows(ctx, type, rows);
  const badRows = new Set(errors.map((e) => e.row));
  const token = uid("imp");
  ctx.db.importPreviews = { [token]: { type, rows, fileName, fileHash } };
  return { type, fileName, totalRows: rows.length, validRows: rows.length - badRows.size, errors: errors.slice(0, 2000), sample: rows.slice(0, 20), columns: COLUMNS[type], token };
});

POST("/imports/commit", (ctx) => {
  requirePerm(ctx, "imports.manage");
  const user = requireUser(ctx);
  const { db } = ctx;
  const { token } = ctx.body as { token: string };
  const preview = db.importPreviews[token];
  if (!preview) return fail(409, "IMPORT_EXPIRED", "This preview has expired. Please upload the file again.");
  const type = preview.type as ImportType;
  const errors = validateRows(ctx, type, preview.rows);
  if (errors.length) return fail(422, "IMPORT_INVALID", "This file has blocking errors. Nothing was imported.");
  const createdIds: string[] = [];
  const batchId = uid("batch");
  for (const row of preview.rows) {
    if (type === "PRODUCTS") {
      const category = db.categories.find((c) => c.code === row.category || c.nameEn === row.category)!;
      const unit = db.units.find((u) => u.code === row.base_unit)!;
      const p = createProduct(ctx, { sku: row.sku, nameEn: row.name_en, nameKm: row.name_km, categoryId: category.id, brandId: db.brands.find((b) => b.name === row.brand)?.id ?? null, baseUnitId: unit.id, taxCodeId: db.taxCodes.find((t) => t.code === row.tax_code)?.id ?? null, status: row.status as Product["status"], retailPrice: Number(row.retail_price || 0), wholesalePrice: Number(row.wholesale_price || row.retail_price || 0) });
      createdIds.push(p.id);
    }
    if (type === "BARCODES") {
      const product = db.products.find((p) => p.sku === row.sku)!;
      product.barcodes.push({ id: uid("bc"), barcode: row.barcode, symbology: detectSymbology(row.barcode), unitId: db.units.find((u) => u.code === row.unit)!.id, active: true, createdAt: ctx.now.toISOString() });
    }
    if (type === "SUPPLIERS") {
      const supplier = { id: uid("sup"), code: row.code, nameEn: row.name, nameKm: "", taxId: "", phone: row.phone ?? "", email: "", address: "", paymentTerms: "Net 30", currency: row.currency as "USD" | "KHR", leadTimeDays: 7, status: "ACTIVE" as const, contacts: [] };
      db.suppliers.unshift(supplier);
      createdIds.push(supplier.id);
    }
    if (type === "CUSTOMERS") {
      const customer = newCustomer(ctx, { code: row.code, name: row.name, phone: row.phone });
      db.customers.unshift(customer);
      createdIds.push(customer.id);
    }
    if (type === "OPENING_STOCK") {
      const warehouse = db.warehouses.find((w) => w.code === row.warehouse)!;
      const location = db.locations.find((l) => l.code === row.location && l.warehouseId === warehouse.id)!;
      const product = getProduct(db, db.products.find((p) => p.sku === row.sku)!.id);
      const quantity = Number(row.quantity);
      const cost = Number(row.unit_cost);
      applyWac(db, product, quantity, cost);
      postMovement(ctx, { type: "OPENING", productId: product.id, toLocationId: location.id, quantityBase: quantity, unitCost: cost, sourceType: "IMPORT", sourceId: batchId, sourceNo: preview.fileName });
    }
    if (type === "PRICES") {
      const product = db.products.find((p) => p.sku === row.sku)!;
      const list_ = db.priceLists.find((l) => l.code === row.price_list)!;
      db.prices.unshift({ id: uid("prc"), productId: product.id, unitId: db.units.find((u) => u.code === row.unit)!.id, priceListId: list_.id, branchId: db.branches.find((b) => b.code === row.branch)?.id ?? null, customerGroupId: null, price: Number(row.price), effectiveFrom: new Date(row.effective_from).toISOString(), effectiveTo: null, createdBy: user.fullName });
    }
    if (type === "STOCK_COUNT") {
      const count = db.counts.find((c) => c.countNo === row.count_no)!;
      const line = count.lines.find((l) => l.sku === row.sku && db.locations.find((x) => x.id === l.locationId)?.code === row.location)!;
      line.snapshotQty = db.balances.find((b) => b.locationId === line.locationId && b.productId === line.productId)?.onHand ?? 0;
      line.countedQty = Number(row.counted_quantity);
      line.countedAt = ctx.now.toISOString();
      line.countedBy = user.fullName;
      line.variance = round(line.countedQty - line.snapshotQty, 4);
      count.status = "COUNTING";
    }
  }
  const batch: ImportBatch = { id: batchId, type, fileName: preview.fileName, fileHash: preview.fileHash, userName: user.fullName, at: ctx.now.toISOString(), totalRows: preview.rows.length, importedRows: preview.rows.length, status: "COMMITTED", createdIds, canRollback: ["PRODUCTS", "SUPPLIERS", "CUSTOMERS"].includes(type) };
  db.importBatches.unshift(batch);
  delete db.importPreviews[token];
  audit(ctx, "IMPORT_COMMITTED", "IMP", "import", batch.id, { after: { type, rows: batch.importedRows, file: batch.fileName } });
  return batch;
});

GET("/imports", (ctx) => {
  requirePerm(ctx, "imports.manage");
  return list(ctx.db.importBatches);
});

POST("/imports/:id/rollback", (ctx) => {
  requirePerm(ctx, "imports.manage");
  const { db } = ctx;
  const batch = db.importBatches.find((b) => b.id === ctx.params.id);
  if (!batch) return notFound("Import");
  if (batch.status !== "COMMITTED" || !batch.canRollback) return badState("This import cannot be rolled back. Correct inventory imports with adjustments.");
  const ids = new Set(batch.createdIds);
  if (batch.type === "PRODUCTS" && db.products.some((p) => ids.has(p.id) && p.hasMovements)) return fail(409, "IN_USE", "Some products already have stock movements.");
  if (batch.type === "CUSTOMERS" && db.sales.some((s) => s.customerId && ids.has(s.customerId))) return fail(409, "IN_USE", "Some customers already have sales.");
  if (batch.type === "SUPPLIERS" && db.purchaseOrders.some((p) => ids.has(p.supplierId))) return fail(409, "IN_USE", "Some suppliers already have purchase orders.");
  if (batch.type === "PRODUCTS") db.products = db.products.filter((p) => !ids.has(p.id));
  if (batch.type === "CUSTOMERS") db.customers = db.customers.filter((c) => !ids.has(c.id));
  if (batch.type === "SUPPLIERS") db.suppliers = db.suppliers.filter((s) => !ids.has(s.id));
  batch.status = "ROLLED_BACK";
  audit(ctx, "IMPORT_ROLLED_BACK", "IMP", "import", batch.id);
  return batch;
});

POST("/exports/audit", (ctx) => {
  requireUser(ctx);
  const { name, format, rows } = ctx.body as { name: string; format: string; rows: number };
  audit(ctx, "EXPORT", "IMP", "export", name, { after: { format, rows } });
  return { ok: true };
});
