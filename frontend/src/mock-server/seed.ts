import { BRANDS, CATEGORIES, CUSTOMER_NAMES, EXPENSE_CATEGORIES, EXPENSE_SAMPLES, PRODUCTS, SUPPLIERS, VARIANT_PARENT, WHOLESALE_CUSTOMERS, type SeedProduct } from "@/mock-data/catalog";
import { buildDefaultRoles } from "@/constants/roles";
import { ean13CheckDigit } from "@/lib/barcode";
import type { Currency, LocationType, Permission, Product, RoleCode, SystemSettings, Unit } from "@/types";
import { round, uid, type Ctx } from "./core";
import { SCHEMA_VERSION, type MockDb, type UserRecord } from "./db";
import { applyWac, evaluateStockAlerts, locationByType, postMovement, sellableLocation } from "./domain/inventory";
import { addPayment, applySaleOps, cancelSale, createDraftSale, createReturn, finalizeSale } from "./domain/sales";

/** Deterministic pseudo-random generator so the demo data is stable. */
function rng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296;
    return s / 4294967296;
  };
}

const SETTINGS: SystemSettings = {
  taxInclusive: false, khrCashIncrement: 100, skuMode: "AUTO", skuPrefix: "", branchPricingEnabled: true, costingMethod: "WAC", costingScope: "COMPANY", negativeStockAllowed: false, reducedSodMode: false, posIdleLockMinutes: 2,
  returnWindowDays: 7, noReceiptReturnsEnabled: false, storeCreditEnabled: true, loyaltyEnabled: true, loyaltyPointsPerUsd: 1, loyaltyRedeemUsdPerPoint: 0.01, expenseApprovalThreshold: 100, expenseAttachmentThreshold: 500,
  overDeliveryTolerancePct: 5, sessionVarianceToleranceUsd: 1, sessionVarianceToleranceKhr: 4000, cashMovementApprovalThreshold: 50, refundCashApprovalThreshold: 50, adjustmentAlertValue: 200, countVarianceRecountQty: 5, transferApprovalValue: 500,
  slowMovingDays: 30, expiryWarningDays: 30, dateFormat: "DD/MM/YYYY", timeZone: "Asia/Phnom_Penh",
};

const UNITS: [string, string, string, Unit["dimension"], number][] = [
  ["PCS", "Piece", "ដុំ", "COUNT", 0], ["BTL", "Bottle", "ដប", "COUNT", 0], ["CAN", "Can", "កំប៉ុង", "COUNT", 0], ["PKT", "Packet", "កញ្ចប់", "COUNT", 0], ["BOX", "Box", "ប្រអប់", "COUNT", 0], ["CTN", "Carton", "កេស", "COUNT", 0], ["PACK", "Pack", "កញ្ចប់ធំ", "COUNT", 0], ["KG", "Kilogram", "គីឡូក្រាម", "MASS", 3], ["G", "Gram", "ក្រាម", "MASS", 0], ["L", "Litre", "លីត្រ", "VOLUME", 3], ["SVC", "Service", "សេវា", "COUNT", 0],
];

function makeBarcode(n: number) {
  const body = `885${String(n).padStart(9, "0")}`;
  return body + ean13CheckDigit(body);
}

const DEMO_USERS: { username: string; name: string; role: RoleCode; pin: string; branches: string[] }[] = [
  { username: "admin", name: "Rotha Chea", role: "SYSADMIN", pin: "4826", branches: [] },
  { username: "owner", name: "Sopheap Nhem", role: "OWNER", pin: "7391", branches: [] },
  { username: "manager", name: "Vicheka Roeun", role: "STOREMGR", pin: "2580", branches: [] },
  { username: "branch", name: "Dalis Sim", role: "BRMGR", pin: "3914", branches: ["br-tk"] },
  { username: "inventory", name: "Kosal Pen", role: "INVMGR", pin: "6152", branches: [] },
  { username: "purchasing", name: "Chenda Oum", role: "PUROFF", pin: "8247", branches: [] },
  { username: "cashier", name: "Sokha Meng", role: "CASHIER", pin: "1593", branches: ["br-tk"] },
  { username: "cashier2", name: "Nary Long", role: "CASHIER", pin: "7204", branches: ["br-bkk"] },
  { username: "sales", name: "Pisey Hak", role: "SALES", pin: "5038", branches: ["br-tk"] },
  { username: "warehouse", name: "Bora Tith", role: "WHSTAFF", pin: "6471", branches: [] },
  { username: "accountant", name: "Mealea Sar", role: "ACCT", pin: "9162", branches: [] },
  { username: "auditor", name: "Samnang Yem", role: "AUDITOR", pin: "3786", branches: [] },
  { username: "viewer", name: "Thavy Keo", role: "READONLY", pin: "5429", branches: ["br-tk"] },
];

function daysAgo(now: Date, days: number, hour: number, minute = 0) {
  const d = new Date(now.getTime() - days * 86_400_000);
  d.setUTCHours(hour - 7, minute, 0, 0);
  return d;
}

export function buildSeed(): MockDb {
  const now = new Date();
  const random = rng(20261027);
  const pick = <T,>(items: T[]) => items[Math.floor(random() * items.length)];
  const roles = buildDefaultRoles();

  const branches = [
    { id: "br-tk", code: "TK01", nameEn: "Toul Kork Store", nameKm: "សាខាទួលគោក", address: "St. 289, Toul Kork, Phnom Penh", phone: "012 000 111", receiptHeader: "Toul Kork Store", openTime: "07:00", closeTime: "22:00", dayCutoff: "02:00", status: "ACTIVE" as const },
    { id: "br-bkk", code: "BK02", nameEn: "BKK1 Store", nameKm: "សាខាបឹងកេងកង១", address: "St. 51, Boeung Keng Kang 1, Phnom Penh", phone: "012 000 222", receiptHeader: "BKK1 Store", openTime: "07:00", closeTime: "23:00", dayCutoff: "02:00", status: "ACTIVE" as const },
    { id: "br-sr", code: "SR03", nameEn: "Siem Reap Store", nameKm: "សាខាសៀមរាប", address: "Sivatha Blvd, Siem Reap", phone: "012 000 333", receiptHeader: "Siem Reap Store", openTime: "08:00", closeTime: "22:00", dayCutoff: "02:00", status: "ACTIVE" as const },
  ];
  const warehouses = [
    { id: "wh-tk", code: "WH-TK", name: "Toul Kork Warehouse", branchId: "br-tk", isCentral: false, status: "ACTIVE" as const },
    { id: "wh-bkk", code: "WH-BK", name: "BKK1 Warehouse", branchId: "br-bkk", isCentral: false, status: "ACTIVE" as const },
    { id: "wh-sr", code: "WH-SR", name: "Siem Reap Warehouse", branchId: "br-sr", isCentral: false, status: "ACTIVE" as const },
    { id: "wh-dc", code: "WH-DC", name: "Central DC", branchId: null, isCentral: true, status: "ACTIVE" as const },
    { id: "wh-sys", code: "WH-SYS", name: "System (In transit)", branchId: null, isCentral: true, status: "ACTIVE" as const },
  ];
  const locTypes: [LocationType, string, string][] = [["SELLABLE", "SHELF", "Shop floor"], ["STORAGE", "BACK", "Back store"], ["RECEIVING", "RCV", "Receiving bay"], ["DAMAGED", "DMG", "Damaged"], ["EXPIRED", "EXP", "Expired"], ["RETURNS", "RET", "Returns"]];
  const locations = warehouses.filter((w) => w.id !== "wh-sys").flatMap((w) => locTypes.map(([type, code, name]) => ({ id: `loc-${w.id}-${code}`, code, name, warehouseId: w.id, type, availableToSell: type === "SELLABLE", status: "ACTIVE" as const })));
  locations.push({ id: "loc-transit", code: "IN-TRANSIT", name: "In transit", warehouseId: "wh-sys", type: "IN_TRANSIT", availableToSell: false, status: "ACTIVE" });

  const terminals = [
    { id: "term-tk1", code: "T01", name: "Toul Kork Counter 1", branchId: "br-tk", defaultLocationId: "loc-wh-tk-SHELF", printerProfile: "80mm" as const, cashDrawer: true, status: "ACTIVE" as const, assignedCashierIds: [] },
    { id: "term-tk2", code: "T02", name: "Toul Kork Counter 2", branchId: "br-tk", defaultLocationId: "loc-wh-tk-SHELF", printerProfile: "80mm" as const, cashDrawer: true, status: "ACTIVE" as const, assignedCashierIds: [] },
    { id: "term-bk1", code: "T03", name: "BKK1 Counter 1", branchId: "br-bkk", defaultLocationId: "loc-wh-bkk-SHELF", printerProfile: "80mm" as const, cashDrawer: true, status: "ACTIVE" as const, assignedCashierIds: [] },
    { id: "term-sr1", code: "T04", name: "Siem Reap Counter 1", branchId: "br-sr", defaultLocationId: "loc-wh-sr-SHELF", printerProfile: "58mm" as const, cashDrawer: true, status: "ACTIVE" as const, assignedCashierIds: [] },
  ];

  const users: UserRecord[] = DEMO_USERS.map((u) => ({
    id: `usr-${u.username}`, username: u.username, email: `${u.username}@abcmart.example`, fullName: u.name, phone: "012 345 678", language: "en", status: "ACTIVE", roleIds: [`role-${u.role.toLowerCase()}`], branchIds: u.branches, warehouseIds: [], terminalIds: [], employeeId: `emp-${u.username}`, hasPin: true, mfaEnabled: false, lastLoginAt: null, lockedUntil: null, createdAt: daysAgo(now, 120, 9).toISOString(), demoPassword: "demo-password", demoPin: u.pin, failedAttempts: [],
  }));

  const units = UNITS.map(([code, nameEn, nameKm, dimension, precision]) => ({ id: `unit-${code}`, code, nameEn, nameKm, dimension, precision, status: "ACTIVE" as const }));
  const taxCodes = [{ id: "tax-std", code: "TAX-STD", name: "Standard (illustrative rate)", rate: 10, status: "ACTIVE" as const }, { id: "tax-zero", code: "TAX-ZERO", name: "Zero-rated", rate: 0, status: "ACTIVE" as const }];
  const categories = CATEGORIES.map((c) => ({ id: `cat-${c.code}`, code: c.code, nameEn: c.nameEn, nameKm: c.nameKm, parentId: null, defaultTaxCodeId: c.taxExempt ? null : "tax-std", returnable: c.returnable ?? true, returnWindowDays: c.returnWindowDays ?? 7, allowNegativeStock: false, expiryTrackingDefault: c.expiry ?? false, minMarginPct: c.minMarginPct ?? 0, icon: c.icon, status: "ACTIVE" as const }));
  const brands = BRANDS.map((name, i) => ({ id: `brn-${i}`, code: `B${String(i + 1).padStart(2, "0")}`, name, status: "ACTIVE" as const }));
  const suppliers = SUPPLIERS.map((s) => ({ id: `sup-${s.code}`, code: s.code, nameEn: s.nameEn, nameKm: s.nameKm, taxId: "", phone: s.phone, email: `orders@${s.code.toLowerCase()}.example`, address: "Phnom Penh", paymentTerms: s.terms, currency: "USD" as Currency, leadTimeDays: s.lead, status: "ACTIVE" as const, contacts: [{ id: uid("con"), name: s.contact, position: "Sales representative", phone: s.phone, email: `sales@${s.code.toLowerCase()}.example` }] }));

  const supplierFor = (category: string) => SUPPLIERS.find((s) => s.categories.includes(category)) ?? SUPPLIERS[0];
  let barcodeSeq = 1000;
  const iso = daysAgo(now, 100, 8).toISOString();

  function toProduct(p: SeedProduct): Product {
    const baseUnitId = `unit-${p.unit}`;
    const barcodes: Product["barcodes"] = p.service || p.weighed ? [] : [{ id: uid("bc"), barcode: p.barcode ?? makeBarcode(barcodeSeq++), symbology: "EAN13", unitId: baseUnitId, active: true, createdAt: iso }];
    if (p.carton) barcodes.push({ id: uid("bc"), barcode: p.carton.barcode ?? makeBarcode(barcodeSeq++), symbology: "EAN13", unitId: `unit-${p.carton.unit}`, active: true, createdAt: iso });
    const sup = supplierFor(p.category);
    const conversions = p.carton ? [{ id: uid("cv"), unitId: `unit-${p.carton.unit}`, factor: p.carton.factor, isPurchaseDefault: true, isSalesDefault: false }] : [];
    const category = categories.find((c) => c.code === p.category)!;
    return {
      id: `prd-${p.sku}`, sku: p.sku, nameEn: p.nameEn, nameKm: p.nameKm, description: "", type: p.service ? "SERVICE" : p.weighed ? "WEIGHED" : "STANDARD", parentId: null, variantAttrs: null, categoryId: category.id, brandId: brands.find((b) => b.name === p.brand)?.id ?? null, baseUnitId,
      allowFraction: Boolean(p.weighed), precision: p.weighed ? 3 : 0, taxCodeId: category.defaultTaxCodeId, status: "ACTIVE", image: null, conversions, barcodes, retailPrice: p.price, wholesalePrice: p.wholesale ?? p.price, minSellingPrice: p.minPrice ?? (p.service ? null : round(p.cost * 1.02, 2)),
      lastPurchaseCost: p.cost, avgCost: 0, stockSettings: { reorderLevel: p.reorder, minLevel: Math.round(p.reorder / 2), maxLevel: p.max, reorderQty: p.carton ? p.carton.factor * 2 : Math.max(1, Math.round(p.max / 3)) }, warehouseSettings: {},
      suppliers: p.service ? [] : [{ supplierId: `sup-${sup.code}`, supplierSku: `${sup.code}-${p.sku}`, purchaseUnitId: p.carton ? `unit-${p.carton.unit}` : baseUnitId, cost: p.carton ? round(p.cost * p.carton.factor, 2) : p.cost, leadTimeDays: sup.lead, preferred: true }],
      trackExpiry: Boolean(p.expiry), isFavourite: Boolean(p.favourite), hasMovements: false, branchActivation: {}, createdAt: iso, updatedAt: iso,
    };
  }
  const products = PRODUCTS.map(toProduct);
  // A variant product: parent plus size/colour SKUs, each with its own stock.
  const parent = toProduct({ sku: VARIANT_PARENT.sku, nameEn: VARIANT_PARENT.nameEn, nameKm: VARIANT_PARENT.nameKm, category: "APP", brand: "Riel Wear", unit: "PCS", price: VARIANT_PARENT.price, cost: VARIANT_PARENT.cost, reorder: 0, max: 0, stock: 0 });
  parent.type = "VARIANT_PARENT";
  parent.barcodes = [];
  products.push(parent);
  VARIANT_PARENT.colours.forEach((colour) =>
    VARIANT_PARENT.sizes.forEach((size) => {
      const v = toProduct({ sku: `APP-8${colour[0]}${size}`, nameEn: `${VARIANT_PARENT.nameEn} - ${colour} / ${size}`, nameKm: VARIANT_PARENT.nameKm, category: "APP", brand: "Riel Wear", unit: "PCS", price: VARIANT_PARENT.price, cost: VARIANT_PARENT.cost, reorder: 4, max: 30, stock: 14 });
      v.parentId = parent.id;
      v.variantAttrs = { Colour: colour, Size: size };
      products.push(v);
    }),
  );

  const customerGroups = [
    { id: "grp-ret", code: "RETAIL", name: "Retail members", priceListId: null, discountPct: 0, status: "ACTIVE" as const },
    { id: "grp-vip", code: "VIP", name: "VIP members", priceListId: null, discountPct: 5, status: "ACTIVE" as const },
    { id: "grp-ws", code: "WHOLESALE", name: "Wholesale buyers", priceListId: "pl-ws", discountPct: 0, status: "ACTIVE" as const },
  ];
  const makeCustomer = (i: number, name: string, group: string, phone: string) => ({ id: `cus-${i}`, code: `C${String(i + 1).padStart(5, "0")}`, name, phone, email: i % 3 === 0 ? `${name.split(" ")[0].toLowerCase()}@mail.example` : "", address: "Phnom Penh", groupId: group, notes: "", consentMarketing: i % 2 === 0, loyaltyPoints: 0, tier: "Member", storeCredit: 0, creditLimit: 0, lastPurchaseAt: null, totalSpent: 0, status: "ACTIVE" as const, anonymized: false, createdAt: iso });
  const customers = [
    ...CUSTOMER_NAMES.map((name, i) => makeCustomer(i, name, i % 5 === 0 ? "grp-vip" : "grp-ret", `0${70 + (i % 20)}${String(100000 + i * 7919).slice(0, 6)}`)),
    ...WHOLESALE_CUSTOMERS.map((name, i) => makeCustomer(100 + i, name, "grp-ws", `023${String(880000 + i * 311).slice(0, 6)}`)),
  ];

  const db: MockDb = {
    schemaVersion: SCHEMA_VERSION,
    company: { id: "co-1", legalNameEn: "ABC Retail Co., Ltd.", legalNameKm: "ក្រុមហ៊ុន អេប៊ីស៊ី រីតេល", tradingNameEn: "ABC Mart", tradingNameKm: "អេប៊ីស៊ី ម៉ាត", address: "No. 12, Monivong Blvd, Phnom Penh", phone: "023 000 000", taxId: "", logo: null, baseCurrency: "USD", fiscalYearStartMonth: 1 },
    branches, warehouses, locations, terminals, taxCodes,
    exchangeRates: [{ id: "fx-1", from: "USD", to: "KHR", rate: 4100, effectiveAt: daysAgo(now, 100, 8).toISOString(), createdBy: "Sopheap Nhem" }],
    paymentMethods: [
      { id: "pm-cash", code: "CASH", name: "Cash", requiresReference: false, provider: "", status: "ACTIVE" },
      { id: "pm-card", code: "CARD", name: "Card (standalone terminal)", requiresReference: true, provider: "Standalone terminal", status: "ACTIVE" },
      { id: "pm-qr", code: "QR", name: "QR payment", requiresReference: false, provider: "QR by reference", status: "ACTIVE" },
      { id: "pm-bank", code: "BANK_TRANSFER", name: "Bank transfer", requiresReference: true, provider: "Bank", status: "ACTIVE" },
      { id: "pm-credit", code: "STORE_CREDIT", name: "Store credit", requiresReference: false, provider: "", status: "ACTIVE" },
    ],
    sequences: ([["RECEIPT", "R", true, true, 6], ["INVOICE", "INV", true, true, 6], ["RETURN", "RET", true, true, 6], ["PO", "PO", false, true, 5], ["GRN", "GRN", false, true, 5], ["TRANSFER", "TRF", false, true, 5], ["ADJUSTMENT", "ADJ", false, true, 5], ["COUNT", "CNT", false, true, 5], ["EXPENSE", "EXP", true, true, 5], ["SUPPLIER_RETURN", "PRT", false, true, 5]] as const).map(([docType, prefix, includeBranch, includeYear, padding]) => ({ id: `seq-${docType}`, docType, prefix, nextValue: 1, padding, includeBranch, includeYear })),
    sequenceCounters: {},
    receiptTemplates: [{ id: "tpl-1", branchId: null, name: "Default receipt", language: "BILINGUAL", paperWidth: "80mm", header: "Thank you for shopping with us", footer: "Returns within 7 days with receipt", showLogo: true, showTaxId: false, showQr: true }],
    settings: SETTINGS,
    roles, users,
    employees: users.map((u, i) => ({ id: `emp-${u.username}`, code: `E${String(i + 1).padStart(3, "0")}`, nameEn: u.fullName, nameKm: "", position: roles.find((r) => r.id === u.roleIds[0])?.name ?? "", branchId: u.branchIds[0] ?? "br-tk", phone: u.phone, status: "ACTIVE" })),
    sessions: [], auditLogs: [], categories, brands, units, products, productChanges: [],
    priceLists: [{ id: "pl-ret", code: "RETAIL", name: "Standard retail", type: "RETAIL", status: "ACTIVE" }, { id: "pl-ws", code: "WHOLESALE", name: "Wholesale", type: "WHOLESALE", status: "ACTIVE" }],
    prices: [], priceHistory: [],
    promotions: [
      { id: "pro-1", code: "SNACK10", name: "Snack Week 10% off", type: "CATEGORY", discountPct: 10, discountAmount: 0, productIds: [], categoryIds: ["cat-SNK"], branchIds: [], customerGroupIds: [], startDate: daysAgo(now, 2, 8).toISOString().slice(0, 10), endDate: daysAgo(now, -10, 8).toISOString().slice(0, 10), startTime: null, endTime: null, priority: 10, combinable: false, usageLimit: null, usageCount: 0, status: "ACTIVE", createdBy: "Vicheka Roeun", approvedBy: "Sopheap Nhem" },
      { id: "pro-2", code: "COLABOGO", name: "Cola buy 1 get 1", type: "BOGO", discountPct: 0, discountAmount: 0, productIds: ["prd-BEV-1004"], categoryIds: [], branchIds: ["br-sr"], customerGroupIds: [], startDate: daysAgo(now, 1, 8).toISOString().slice(0, 10), endDate: daysAgo(now, -6, 8).toISOString().slice(0, 10), startTime: null, endTime: null, priority: 20, combinable: false, usageLimit: 200, usageCount: 0, status: "ACTIVE", createdBy: "Vicheka Roeun", approvedBy: "Sopheap Nhem" },
      { id: "pro-3", code: "PAYDAY", name: "Payday 5% off basket", type: "ORDER", discountPct: 5, discountAmount: 0, productIds: [], categoryIds: [], branchIds: [], customerGroupIds: [], startDate: daysAgo(now, -20, 8).toISOString().slice(0, 10), endDate: daysAgo(now, -22, 8).toISOString().slice(0, 10), startTime: null, endTime: null, priority: 5, combinable: true, usageLimit: null, usageCount: 0, status: "PENDING_APPROVAL", createdBy: "Vicheka Roeun", approvedBy: null },
    ],
    coupons: [{ id: "cpn-1", code: "WELCOME2", description: "2 USD off a basket of 15 USD or more", discountPct: 0, discountAmount: 2, minSpend: 15, startDate: daysAgo(now, 30, 8).toISOString().slice(0, 10), endDate: daysAgo(now, -60, 8).toISOString().slice(0, 10), usageLimit: 100, usageCount: 0, perCustomerLimit: 1, status: "ACTIVE" }],
    customers, customerGroups,
    sales: [], returns: [], refunds: [], cashSessions: [], cashMovements: [], balances: [], movements: [], movementSeq: 0, batches: [], adjustments: [], transfers: [], counts: [], alerts: [], suppliers,
    purchaseOrders: [], goodsReceipts: [], supplierInvoices: [], purchaseReturns: [],
    expenseCategories: EXPENSE_CATEGORIES.map(([code, name]) => ({ id: `exc-${code}`, code, name, status: "ACTIVE" as const })),
    expenses: [], notifications: [], notificationReads: {}, importBatches: [], idempotency: {}, approvalTokens: [], importPreviews: {},
  };

  // Everything below uses the same posting services as live requests, so ledger and balances always agree.
  const asUser = (username: string, when: Date): Ctx => {
    const user = db.users.find((u) => u.username === username)!;
    const role = db.roles.find((r) => r.id === user.roleIds[0])!;
    return { db, user, permissions: new Set<Permission>(role.permissions), limits: role.limits, params: {}, query: {}, body: null, terminalId: null, now: when, touchedProducts: new Set() };
  };

  const openingAt = daysAgo(now, 95, 7);
  const opening = asUser("inventory", openingAt);
  const stocked = db.products.filter((p) => p.type !== "SERVICE" && p.type !== "VARIANT_PARENT");
  const stockFor = (p: Product) => PRODUCTS.find((x) => x.sku === p.sku)?.stock ?? 14;
  const shelves: [string, number][] = [["wh-tk", 2.6], ["wh-bkk", 2.1], ["wh-sr", 1.6]];
  for (const product of stocked) {
    const baseCost = product.lastPurchaseCost ?? 0;
    const target = stockFor(product);
    // Skip seeding stock only for the deliberately out-of-stock SKU.
    for (const [warehouseId, multiplier] of shelves) {
      const shelf = sellableLocation(db, warehouseId);
      let qty = target === 0 ? 10 : target * multiplier + 40 * (product.allowFraction ? 1 : Math.ceil(random() * 3));
      qty = product.allowFraction ? round(qty, 2) : Math.ceil(qty);
      applyWac(db, product, qty, baseCost);
      postMovement(opening, { type: "OPENING", productId: product.id, toLocationId: shelf.id, quantityBase: qty, unitCost: baseCost, sourceType: "IMPORT", sourceId: "seed", sourceNo: "OPENING-STOCK" });
      if (product.trackExpiry) {
        db.batches.push({ id: uid("bat"), productId: product.id, locationId: shelf.id, batchNo: `L${product.sku.slice(-2)}A`, expiryDate: daysAgo(now, -18, 8).toISOString().slice(0, 10), quantity: Math.ceil(qty * 0.4), receiptId: "seed" });
        db.batches.push({ id: uid("bat"), productId: product.id, locationId: shelf.id, batchNo: `L${product.sku.slice(-2)}B`, expiryDate: daysAgo(now, -120, 8).toISOString().slice(0, 10), quantity: qty - Math.ceil(qty * 0.4), receiptId: "seed" });
      }
    }
  }

  const seller = [...stocked, ...db.products.filter((p) => p.type === "SERVICE")];
  const weighted = seller.flatMap((p) => Array(p.isFavourite ? 6 : p.status === "ACTIVE" ? 2 : 1).fill(p) as Product[]);
  const cashierFor: Record<string, string> = { "term-tk1": "cashier", "term-tk2": "manager", "term-bk1": "cashier2", "term-sr1": "branch" };
  // The Siem Reap and BKK1 demo sellers need branch scope for finalization only; seeding runs as a system context.
  const DAYS = 75;
  for (let day = DAYS; day >= 0; day--) {
    for (const terminal of db.terminals) {
      const username = cashierFor[terminal.id];
      const open = daysAgo(now, day, 7, 15);
      const isToday = day === 0;
      if (isToday && terminal.id !== "term-tk2") continue;
      const sessionCtx = asUser(username, open);
      const sessionNo = `S-${String(db.cashSessions.length + 1).padStart(4, "0")}`;
      const session = { id: uid("cs"), sessionNo, terminalId: terminal.id, terminalName: terminal.name, branchId: terminal.branchId, cashierId: sessionCtx.user!.id, cashierName: sessionCtx.user!.fullName, status: "OPEN" as const, openedAt: open.toISOString(), closedAt: null, opening: { USD: 50, KHR: 100000 }, witness: null, counted: null, denominations: null, expected: null, variance: null, varianceReason: null, reviewedBy: null, needsApproval: false };
      db.cashSessions.unshift(session as never);
      const volume = isToday ? 3 : terminal.id === "term-tk1" ? 4 : terminal.id === "term-tk2" ? 2 : 3;
      const dailyCount = volume + Math.floor(random() * 3);
      let cashExpectedUsd = 50;
      let cashExpectedKhr = 100000;
      for (let n = 0; n < dailyCount; n++) {
        const at = isToday ? new Date(now.getTime() - (dailyCount - n) * 15 * 60_000) : daysAgo(now, day, 8 + Math.floor(random() * 12), Math.floor(random() * 59));
        const ctx = asUser(username, at);
        const customerRoll = random();
        const customer = customerRoll < 0.3 ? pick(db.customers) : null;
        const sale = createDraftSale(ctx, terminal, customer?.id ?? null);
        const lineCount = 1 + Math.floor(random() * 4);
        const chosen = new Set<string>();
        for (let i = 0; i < lineCount; i++) chosen.add(pick(weighted).id);
        const ops = [...chosen].map((productId) => {
          const product = db.products.find((p) => p.id === productId)!;
          const quantity = product.allowFraction ? round(0.25 + random() * 2, 3) : 1 + Math.floor(random() * 3);
          return { type: "add_product" as const, productId, quantity };
        });
        applySaleOps(ctx, sale, ops, terminal);
        const roll = random();
        if (roll < 0.04 && !isToday) {
          ctx.limits = { ...ctx.limits };
          cancelSale({ ...ctx, permissions: new Set([...ctx.permissions, "pos.cancel" as Permission]) }, sale, "Customer changed their mind");
          continue;
        }
        try {
          if (roll < 0.62) {
            const khr = random() < 0.25;
            if (khr) {
              const due = Math.ceil((sale.balance * sale.exchangeRate) / 500) * 500;
              addPayment(ctx, sale, { method: "CASH", currency: "KHR", amountTendered: due + (random() < 0.5 ? 5000 : 0), changeCurrency: "KHR" });
            } else {
              addPayment(ctx, sale, { method: "CASH", currency: "USD", amountTendered: Math.ceil(sale.balance), changeCurrency: "USD" });
            }
          } else if (roll < 0.8) {
            addPayment(ctx, sale, { method: "QR", currency: "USD", amountTendered: sale.balance, reference: undefined });
            const payment = sale.payments[sale.payments.length - 1];
            payment.status = "COMPLETED";
            payment.reference = `QR${Math.floor(random() * 1e9)}`;
            payment.completedAt = at.toISOString();
            payment.reconciled = day > 3;
            sale.status = "DRAFT";
            sale.paidTotal = sale.grandTotal;
            sale.balance = 0;
          } else if (roll < 0.96) {
            addPayment(ctx, sale, { method: "CARD", currency: "USD", amountTendered: sale.balance, reference: `TXN${Math.floor(random() * 1e8)}`, approvalCode: String(Math.floor(100000 + random() * 899999)), cardLast4: String(1000 + Math.floor(random() * 8999)) });
            sale.payments[sale.payments.length - 1].reconciled = day > 3;
          } else {
            addPayment(ctx, sale, { method: "BANK_TRANSFER", currency: "USD", amountTendered: sale.balance, reference: `ABA${Math.floor(random() * 1e8)}` });
          }
          finalizeSale(ctx, sale, terminal);
          sale.sessionId = session.id;
          sale.payments.forEach((p) => (p.sessionId = session.id));
        } catch {
          sale.status = "CANCELLED";
          sale.cancelReason = "Insufficient stock";
          sale.payments = [];
          continue;
        }
        for (const p of sale.payments) {
          if (p.method !== "CASH") continue;
          if (p.currency === "USD") cashExpectedUsd += p.amountTendered;
          else cashExpectedKhr += p.amountTendered;
          if (p.changeCurrency === "USD") cashExpectedUsd -= p.changeAmount;
          else cashExpectedKhr -= p.changeAmount;
        }
        if (random() < 0.05 && !isToday && sale.lines.length && sale.customerId) {
          const line = sale.lines[0];
          const returnCtx = asUser("manager", new Date(at.getTime() + 3600_000));
          returnCtx.terminalId = terminal.id;
          returnCtx.limits = { ...returnCtx.limits, refundAmount: 100000 };
          try {
            createReturn(returnCtx, sale, { lines: [{ saleLineId: line.id, quantity: line.allowFraction ? line.quantity : 1, condition: random() < 0.75 ? "RESALABLE" : "DAMAGED", reason: pick(["Customer changed mind", "Wrong item", "Faulty item"]) }], refundMethod: "STORE_CREDIT", reference: "seed" });
          } catch {
            // Non-returnable or already-returned items are simply skipped in seed data.
          }
        }
      }
      if (!isToday) {
        const closeAt = daysAgo(now, day, 21, 30);
        const drift = random() < 0.12 ? round((random() - 0.5) * 4, 2) : 0;
        Object.assign(session, { status: "CLOSED", closedAt: closeAt.toISOString(), counted: { USD: round(cashExpectedUsd + drift), KHR: cashExpectedKhr }, expected: { USD: round(cashExpectedUsd), KHR: cashExpectedKhr }, variance: { USD: drift, KHR: 0 }, reviewedBy: Math.abs(drift) > 1 ? "Vicheka Roeun" : null, varianceReason: Math.abs(drift) > 1 ? "Reviewed with cashier" : null });
      }
    }
  }

  // Purchasing history and open documents.
  const buyer = asUser("purchasing", daysAgo(now, 20, 9));
  const po = (daysBack: number, supplierCode: string, warehouseId: string, status: "RECEIVED" | "SENT" | "PENDING_APPROVAL" | "APPROVED", count: number) => {
    const when = daysAgo(now, daysBack, 9);
    const supplier = db.suppliers.find((s) => s.code === supplierCode)!;
    const items = stocked.filter((p) => p.suppliers.some((s) => s.supplierId === supplier.id)).slice(0, count);
    const warehouse = db.warehouses.find((w) => w.id === warehouseId)!;
    const year = when.getFullYear();
    const key = `PO::${year}`;
    const seq = db.sequenceCounters[key] ?? 1;
    db.sequenceCounters[key] = seq + 1;
    const lines = items.map((p) => {
      const link = p.suppliers[0];
      const factor = p.conversions.find((c) => c.unitId === link.purchaseUnitId)?.factor ?? 1;
      const quantity = factor > 1 ? 4 : 20;
      return { id: uid("pol"), productId: p.id, sku: p.sku, productName: p.nameEn, supplierSku: link.supplierSku, unitId: link.purchaseUnitId, unitCode: db.units.find((u) => u.id === link.purchaseUnitId)!.code, factor, quantity, quantityBase: quantity * factor, unitCost: link.cost, taxRate: 0, lineTotal: round(quantity * link.cost), receivedBase: status === "RECEIVED" ? quantity * factor : 0, cancelledBase: 0 };
    });
    const total = round(lines.reduce((s, l) => s + l.lineTotal, 0));
    const record = {
      id: uid("po"), poNo: `PO-${year}-${String(seq).padStart(5, "0")}`, supplierId: supplier.id, supplierName: supplier.nameEn, warehouseId, warehouseName: warehouse.name, branchId: warehouse.branchId, expectedDate: new Date(when.getTime() + supplier.leadTimeDays * 86_400_000).toISOString().slice(0, 10), status, notes: "", lines, subtotal: total, taxTotal: 0, total, createdBy: buyer.user!.fullName, createdById: buyer.user!.id, approvedBy: status === "PENDING_APPROVAL" ? null : "Vicheka Roeun", createdAt: when.toISOString(), sentAt: status === "SENT" || status === "RECEIVED" ? when.toISOString() : null, firstReceivedAt: status === "RECEIVED" ? new Date(when.getTime() + supplier.leadTimeDays * 86_400_000).toISOString() : null,
      timeline: [{ at: when.toISOString(), label: "Created", by: buyer.user!.fullName }, ...(status === "PENDING_APPROVAL" ? [] : [{ at: when.toISOString(), label: "Approved", by: "Vicheka Roeun" }])],
    };
    db.purchaseOrders.unshift(record);
    if (status === "RECEIVED") {
      const receiver = asUser("warehouse", new Date(record.firstReceivedAt!));
      const shelf = sellableLocation(db, warehouseId);
      const grnKey = `GRN::${year}`;
      const grnSeq = db.sequenceCounters[grnKey] ?? 1;
      db.sequenceCounters[grnKey] = grnSeq + 1;
      const receiptNo = `GRN-${year}-${String(grnSeq).padStart(5, "0")}`;
      const grnId = uid("grn");
      lines.forEach((l) => {
        const product = db.products.find((p) => p.id === l.productId)!;
        const unitCost = l.unitCost / l.factor;
        applyWac(db, product, l.quantityBase, unitCost);
        postMovement(receiver, { type: "PURCHASE_RECEIPT", productId: l.productId, toLocationId: shelf.id, quantityBase: l.quantityBase, unitCode: l.unitCode, quantityEntered: l.quantity, unitCost, sourceType: "GRN", sourceId: grnId, sourceNo: receiptNo });
      });
      db.goodsReceipts.unshift({ id: grnId, receiptNo, poId: record.id, poNo: record.poNo, supplierId: supplier.id, supplierName: supplier.nameEn, warehouseId, warehouseName: warehouse.name, branchId: warehouse.branchId, status: "POSTED", blind: false, exceptionReason: null, deliveryNote: `DN-${1000 + seq}`, invoiceRef: `SI-${2000 + seq}`, lines: lines.map((l) => ({ id: uid("grl"), poLineId: l.id, productId: l.productId, sku: l.sku, productName: l.productName, unitId: l.unitId, unitCode: l.unitCode, factor: l.factor, orderedOpen: l.quantity, quantityReceived: l.quantity, quantityDamaged: 0, quantityRejected: 0, unitCost: l.unitCost, batchNo: "", expiryDate: "", trackExpiry: false })), discrepancies: [], totalCost: total, createdBy: receiver.user!.fullName, createdById: receiver.user!.id, approvedBy: null, postedBy: receiver.user!.fullName, postedAt: record.firstReceivedAt, createdAt: record.firstReceivedAt!, flaggedForReview: false });
      const paid = daysBack > 25;
      db.supplierInvoices.unshift({ id: uid("inv"), invoiceNo: `SI-${2000 + seq}`, supplierId: supplier.id, supplierName: supplier.nameEn, poId: record.id, poNo: record.poNo, invoiceDate: record.firstReceivedAt!.slice(0, 10), dueDate: new Date(new Date(record.firstReceivedAt!).getTime() + 30 * 86_400_000).toISOString().slice(0, 10), amount: total, paidAmount: paid ? total : 0, status: paid ? "PAID" : "MATCHED", matchNotes: `Matches received value ${total.toFixed(2)} USD`, payments: paid ? [{ id: uid("sp"), amount: total, reference: `ABA-TRF-${1000 + seq}`, paidAt: when.toISOString(), by: "Mealea Sar" }] : [], createdBy: "Mealea Sar", createdAt: record.firstReceivedAt! });
    }
  };
  po(60, "SUP-001", "wh-tk", "RECEIVED", 6); po(45, "SUP-002", "wh-bkk", "RECEIVED", 7); po(30, "SUP-004", "wh-tk", "RECEIVED", 5); po(14, "SUP-003", "wh-sr", "RECEIVED", 3); po(6, "SUP-001", "wh-bkk", "SENT", 5); po(3, "SUP-002", "wh-tk", "APPROVED", 4); po(1, "SUP-004", "wh-sr", "PENDING_APPROVAL", 4);

  const moverAt = daysAgo(now, 12, 10);
  const mover = asUser("inventory", moverAt);
  const trfItems = stocked.slice(0, 3);
  db.sequenceCounters[`TRANSFER::${now.getFullYear()}`] = 3;
  (["CLOSED", "DISPATCHED"] as const).forEach((status, i) => {
    const when = daysAgo(now, status === "CLOSED" ? 12 : 1, 10);
    const lines = trfItems.map((p) => ({ id: uid("trl"), productId: p.id, sku: p.sku, productName: p.nameEn, unitCode: db.units.find((u) => u.id === p.baseUnitId)!.code, quantityRequested: 12, quantityDispatched: 12, quantityReceived: status === "CLOSED" ? 12 : 0, quantityShort: 0, quantityDamaged: 0, quantityExcess: 0 }));
    const transferNo = `TRF-${now.getFullYear()}-${String(i + 1).padStart(5, "0")}`;
    const id = uid("trf");
    const moverCtx = { ...mover, now: when };
    const source = sellableLocation(db, "wh-tk");
    const destination = sellableLocation(db, "wh-bkk");
    lines.forEach((l) => {
      const product = db.products.find((p) => p.id === l.productId)!;
      postMovement(moverCtx, { type: "TRANSFER_OUT", productId: l.productId, fromLocationId: source.id, toLocationId: "loc-transit", quantityBase: 12, unitCost: product.avgCost ?? 0, sourceType: "TRANSFER", sourceId: id, sourceNo: transferNo });
      if (status === "CLOSED") postMovement(moverCtx, { type: "TRANSFER_RECEIVE", productId: l.productId, fromLocationId: "loc-transit", toLocationId: destination.id, quantityBase: 12, unitCost: product.avgCost ?? 0, sourceType: "TRANSFER", sourceId: id, sourceNo: transferNo });
    });
    db.transfers.unshift({ id, transferNo, sourceWarehouseId: "wh-tk", sourceWarehouseName: "Toul Kork Warehouse", destinationWarehouseId: "wh-bkk", destinationWarehouseName: "BKK1 Warehouse", status, reason: "Rebalance stock between stores", lines, value: round(lines.reduce((s, l) => s + 12 * (db.products.find((p) => p.id === l.productId)?.avgCost ?? 0), 0)), createdBy: "Dalis Sim", createdById: "usr-branch", approvedBy: "Kosal Pen", createdAt: when.toISOString(), dispatchedAt: when.toISOString(), receivedAt: status === "CLOSED" ? when.toISOString() : null, timeline: [{ at: when.toISOString(), label: "Requested", by: "Dalis Sim" }, { at: when.toISOString(), label: "Approved", by: "Kosal Pen" }, { at: when.toISOString(), label: "Dispatched", by: "Bora Tith" }] });
  });

  const adjProduct = stocked[6];
  const shelfTk = sellableLocation(db, "wh-tk");
  db.sequenceCounters[`ADJUSTMENT::${now.getFullYear()}`] = 2;
  db.adjustments.unshift({ id: uid("adj"), adjustmentNo: `ADJ-${now.getFullYear()}-00001`, warehouseId: "wh-tk", warehouseName: "Toul Kork Warehouse", branchId: "br-tk", status: "SUBMITTED", lines: [{ id: uid("adl"), productId: adjProduct.id, sku: adjProduct.sku, productName: adjProduct.nameEn, locationId: shelfTk.id, locationName: shelfTk.name, quantity: -3, unitCode: "BOX", reason: "DAMAGED", notes: "Crushed by forklift", unitCost: adjProduct.avgCost, valueImpact: round(-3 * (adjProduct.avgCost ?? 0)) }], notes: "Found during morning check", attachment: null, totalValue: round(3 * (adjProduct.avgCost ?? 0)), requiresApproval: true, createdBy: "Bora Tith", createdById: "usr-warehouse", approvedBy: null, createdAt: daysAgo(now, 0, 8).toISOString(), postedAt: null, timeline: [{ at: daysAgo(now, 0, 8).toISOString(), label: "Submitted", by: "Bora Tith" }] });

  const expenseCtx = asUser("manager", daysAgo(now, 60, 9));
  for (let month = 2; month >= 0; month--) {
    for (const branch of db.branches) {
      for (const [code, description, amount] of EXPENSE_SAMPLES) {
        const when = daysAgo(now, month * 30 + 2 + Math.floor(random() * 3), 10);
        const varied = round(amount * (0.85 + random() * 0.3));
        const key = `EXPENSE:${branch.code}:${when.getFullYear()}`;
        const seq = db.sequenceCounters[key] ?? 1;
        db.sequenceCounters[key] = seq + 1;
        db.expenses.unshift({ id: uid("exp"), expenseNo: `EXP-${branch.code}-${when.getFullYear()}-${String(seq).padStart(5, "0")}`, date: when.toISOString().slice(0, 10), categoryId: `exc-${code}`, categoryName: EXPENSE_CATEGORIES.find(([c]) => c === code)![1], description, amount: varied, currency: "USD", amountBase: varied, paymentMethod: code === "RENT" ? "Bank transfer" : "Cash", branchId: branch.id, branchName: branch.nameEn, attachment: null, status: month === 0 && code === "REPR" ? "SUBMITTED" : "APPROVED", rejectReason: null, sessionId: null, createdBy: expenseCtx.user!.fullName, createdById: expenseCtx.user!.id, approvedBy: month === 0 && code === "REPR" ? null : "Mealea Sar", createdAt: when.toISOString() });
      }
    }
  }

  // Bring current stock in line with the demo's intended low and out-of-stock states.
  const settle = asUser("inventory", daysAgo(now, 0, 7));
  for (const product of stocked) {
    const target = stockFor(product);
    const shelf = sellableLocation(db, "wh-tk");
    const balance = db.balances.find((b) => b.locationId === shelf.id && b.productId === product.id);
    const difference = round((balance?.onHand ?? 0) - target, product.allowFraction ? 3 : 0);
    if (difference > 0) postMovement(settle, { type: "RELOCATION", productId: product.id, fromLocationId: shelf.id, toLocationId: locationByType(db, "wh-tk", "STORAGE")!.id, quantityBase: difference, unitCost: product.avgCost ?? 0, sourceType: "RELOCATION", sourceId: "seed", sourceNo: "BACK-STORE-MOVE", reasonCode: "Moved to back store" });
    if (difference < 0) {
      const back = -difference;
      applyWac(db, product, back, product.lastPurchaseCost ?? 0);
      postMovement(settle, { type: "ADJUSTMENT_IN", productId: product.id, toLocationId: shelf.id, quantityBase: back, unitCost: product.lastPurchaseCost ?? 0, sourceType: "IMPORT", sourceId: "seed", sourceNo: "REPLENISHMENT" });
    }
    // Keep the other stores healthy so alerts stay meaningful in the demo.
    for (const warehouseId of ["wh-bkk", "wh-sr"]) {
      const other = sellableLocation(db, warehouseId);
      const onHand = db.balances.find((b) => b.locationId === other.id && b.productId === product.id)?.onHand ?? 0;
      const floor = product.stockSettings.reorderLevel + product.stockSettings.maxLevel * 0.3;
      if (onHand <= product.stockSettings.reorderLevel * 1.2 && target > 0) {
        const qty = product.allowFraction ? round(floor - onHand, 2) : Math.ceil(floor - onHand);
        if (qty > 0) {
          applyWac(db, product, qty, product.lastPurchaseCost ?? 0);
          postMovement(settle, { type: "ADJUSTMENT_IN", productId: product.id, toLocationId: other.id, quantityBase: qty, unitCost: product.lastPurchaseCost ?? 0, sourceType: "IMPORT", sourceId: "seed", sourceNo: "REPLENISHMENT" });
        }
      }
    }
  }
  evaluateStockAlerts(asUser("inventory", now), db.products.map((p) => p.id));
  db.batches = db.batches.filter((b) => b.quantity > 0);
  db.auditLogs = db.auditLogs.slice(0, 400);
  db.notifications = db.notifications.slice(0, 40);
  db.sales.sort((a, b) => (b.finalizedAt ?? b.createdAt).localeCompare(a.finalizedAt ?? a.createdAt));
  return db;
}
