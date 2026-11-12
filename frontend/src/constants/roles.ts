import type { Permission, Role, RoleCode, RoleLimits } from "@/types";
import { PERMISSIONS } from "@/types";

const none: RoleLimits = {
  discountPct: 0,
  overrideAmount: 0,
  refundAmount: 0,
  adjustmentValue: 0,
  poApprovalLimit: 0,
};

const unlimited: RoleLimits = {
  discountPct: 100,
  overrideAmount: 1_000_000,
  refundAmount: 1_000_000,
  adjustmentValue: 1_000_000,
  poApprovalLimit: 1_000_000,
};

const CATALOG_VIEW: Permission[] = ["products.view", "pricing.view"];
const ALL_REPORTS: Permission[] = [
  "reports.sales",
  "reports.tax",
  "reports.profit",
  "reports.inventory",
  "reports.purchasing",
  "reports.cash",
  "reports.business",
  "reports.export",
];

/** Default role matrix from SRS sections 4.3 and 14.2 (proposed, pending D-12). */
const ROLE_DEFINITIONS: Record<
  Exclude<RoleCode, "CUSTOM">,
  { name: string; description: string; permissions: Permission[]; limits: RoleLimits }
> = {
  SYSADMIN: {
    name: "System Administrator",
    description: "Users, roles, terminals, devices and settings. No sales, approvals or inventory posting.",
    permissions: [
      "dashboard.view",
      "products.view",
      "users.view",
      "users.manage",
      "roles.manage",
      "audit.view",
      "settings.view",
      "settings.manage",
      "imports.manage",
      "alerts.view",
      "reports.export",
    ],
    limits: none,
  },
  OWNER: {
    name: "Business Owner",
    description: "All branches, approvals above managers' limits, costs and profits.",
    permissions: PERMISSIONS.filter((p) => p !== "roles.manage"),
    limits: unlimited,
  },
  STOREMGR: {
    name: "Store Manager",
    description: "Operations of assigned stores; pricing; approvals within limit.",
    permissions: [
      "dashboard.view",
      "pos.sell", "pos.hold", "pos.discount", "pos.override", "pos.cancel",
      "sales.view", "sales.view_all", "sales.void",
      "returns.create", "returns.approve",
      "products.view", "products.create", "products.edit", "products.delete",
      "pricing.view", "pricing.edit", "costs.view",
      "inventory.view", "inventory.adjust", "inventory.adjust.approve",
      "inventory.transfer", "inventory.transfer.approve", "inventory.count", "inventory.count.approve", "inventory.reverse",
      "purchasing.view", "purchasing.create", "purchasing.approve",
      "receiving.create", "receiving.post", "receiving.exception",
      "suppliers.view", "suppliers.manage",
      "customers.view", "customers.manage", "customers.personal_data",
      "promotions.view", "promotions.manage",
      "cash.session.open", "cash.session.close", "cash.session.approve", "cash.session.view", "cash.session.view_all",
      ...ALL_REPORTS, "reports.exceptions", "reports.consolidated",
      "expenses.view", "expenses.create",
      "settings.view", "imports.manage",
      "alerts.view", "alerts.manage",
    ],
    limits: { discountPct: 30, overrideAmount: 100, refundAmount: 500, adjustmentValue: 500, poApprovalLimit: 5000 },
  },
  BRMGR: {
    name: "Branch Manager",
    description: "Branch operations, session reviews, refunds and adjustments within limit.",
    permissions: [
      "dashboard.view",
      "pos.sell", "pos.hold", "pos.discount", "pos.override", "pos.cancel",
      "sales.view", "sales.view_all", "sales.void",
      "returns.create", "returns.approve",
      ...CATALOG_VIEW, "products.edit", "costs.view",
      "inventory.view", "inventory.adjust", "inventory.transfer", "inventory.count",
      "purchasing.view", "receiving.create", "receiving.post",
      "suppliers.view",
      "customers.view", "customers.manage", "customers.personal_data",
      "promotions.view",
      "cash.session.open", "cash.session.close", "cash.session.approve", "cash.session.view", "cash.session.view_all",
      "reports.sales", "reports.inventory", "reports.cash", "reports.export",
      "expenses.view", "expenses.create",
      "alerts.view", "alerts.manage",
    ],
    limits: { discountPct: 20, overrideAmount: 50, refundAmount: 200, adjustmentValue: 100, poApprovalLimit: 0 },
  },
  INVMGR: {
    name: "Inventory Manager",
    description: "Stock, adjustments, transfers, stocktakes and alerts. No sales.",
    permissions: [
      "dashboard.view",
      ...CATALOG_VIEW, "products.create", "products.edit", "costs.view",
      "inventory.view", "inventory.adjust", "inventory.adjust.approve",
      "inventory.transfer", "inventory.transfer.approve", "inventory.count", "inventory.count.approve", "inventory.reverse",
      "purchasing.view", "receiving.create", "receiving.post", "receiving.exception",
      "suppliers.view",
      "reports.inventory", "reports.export",
      "settings.view", "imports.manage",
      "alerts.view", "alerts.manage",
    ],
    limits: { ...none, adjustmentValue: 300 },
  },
  PUROFF: {
    name: "Purchasing Officer",
    description: "Suppliers, purchase orders, supplier invoices and purchase returns.",
    permissions: [
      "dashboard.view",
      ...CATALOG_VIEW, "products.create", "products.edit", "costs.view",
      "inventory.view",
      "purchasing.view", "purchasing.create",
      "suppliers.view", "suppliers.manage",
      "reports.purchasing", "reports.export",
      "imports.manage",
      "alerts.view",
    ],
    limits: none,
  },
  CASHIER: {
    name: "Cashier",
    description: "Sales, payments, receipts, own session and initiating returns.",
    permissions: [
      "dashboard.view",
      "pos.sell", "pos.hold", "pos.discount",
      "sales.view", "returns.create",
      ...CATALOG_VIEW,
      "inventory.view",
      "customers.view", "customers.manage",
      "cash.session.open", "cash.session.close", "cash.session.view",
      "reports.cash",
    ],
    limits: { ...none, discountPct: 5, refundAmount: 20 },
  },
  SALES: {
    name: "Salesperson",
    description: "Create and hold sales, look up stock and prices, customers.",
    permissions: [
      "dashboard.view", "pos.hold",
      "sales.view",
      ...CATALOG_VIEW,
      "inventory.view",
      "customers.view", "customers.manage",
    ],
    limits: none,
  },
  WHSTAFF: {
    name: "Warehouse Staff",
    description: "Receive goods, dispatch and receive transfers, count stock.",
    permissions: [
      "dashboard.view",
      ...CATALOG_VIEW,
      "inventory.view", "inventory.adjust", "inventory.transfer", "inventory.count",
      "purchasing.view", "receiving.create", "receiving.post",
      "alerts.view",
    ],
    limits: none,
  },
  ACCT: {
    name: "Accountant",
    description: "Costs, valuation, payment reconciliation, expenses and exports.",
    permissions: [
      "dashboard.view",
      "sales.view", "sales.view_all",
      ...CATALOG_VIEW, "costs.view",
      "inventory.view",
      "purchasing.view",
      "suppliers.view",
      "customers.view",
      "promotions.view",
      "cash.session.view", "cash.session.view_all", "cash.session.approve",
      ...ALL_REPORTS, "reports.consolidated",
      "expenses.view", "expenses.create", "expenses.approve",
      "settings.view",
    ],
    limits: none,
  },
  AUDITOR: {
    name: "Auditor",
    description: "Read-only access including audit logs.",
    permissions: [
      "dashboard.view", "reports.consolidated",
      "sales.view", "sales.view_all",
      ...CATALOG_VIEW, "costs.view",
      "inventory.view", "purchasing.view", "suppliers.view",
      "customers.view", "customers.personal_data", "promotions.view",
      "cash.session.view", "cash.session.view_all",
      ...ALL_REPORTS, "reports.exceptions",
      "expenses.view", "users.view", "audit.view", "settings.view", "alerts.view",
    ],
    limits: none,
  },
  READONLY: {
    name: "Read-only User",
    description: "View permitted data. No changes and no costs.",
    permissions: [
      "dashboard.view",
      "sales.view",
      ...CATALOG_VIEW,
      "inventory.view",
      "reports.sales", "reports.inventory", "reports.export",
    ],
    limits: none,
  },
};

export function buildDefaultRoles(): Role[] {
  return (Object.entries(ROLE_DEFINITIONS) as [Exclude<RoleCode, "CUSTOM">, (typeof ROLE_DEFINITIONS)[Exclude<RoleCode, "CUSTOM">]][]).map(
    ([code, def]) => ({
      id: `role-${code.toLowerCase()}`,
      code,
      name: def.name,
      description: def.description,
      permissions: [...new Set(def.permissions)],
      limits: def.limits,
      system: true,
    }),
  );
}

/** Grouped catalogue used by the role matrix screen. */
export const PERMISSION_GROUPS: { label: string; prefix: string[] }[] = [
  { label: "Dashboard", prefix: ["dashboard."] },
  { label: "Point of sale", prefix: ["pos."] },
  { label: "Sales and returns", prefix: ["sales.", "returns."] },
  { label: "Products and pricing", prefix: ["products.", "pricing.", "costs."] },
  { label: "Inventory", prefix: ["inventory."] },
  { label: "Purchasing", prefix: ["purchasing.", "receiving.", "suppliers."] },
  { label: "Customers and promotions", prefix: ["customers.", "promotions."] },
  { label: "Cashier sessions", prefix: ["cash."] },
  { label: "Reports", prefix: ["reports."] },
  { label: "Expenses", prefix: ["expenses."] },
  { label: "Administration", prefix: ["users.", "roles.", "audit.", "settings.", "imports.", "alerts."] },
];

/** SoD conflicts surfaced on the role and user forms (SRS 4.4). */
export const SOD_CONFLICTS: { a: Permission; b: Permission; label: string }[] = [
  { a: "purchasing.create", b: "purchasing.approve", label: "create PO and approve PO" },
  { a: "expenses.create", b: "expenses.approve", label: "record expense and approve expense" },
  { a: "inventory.adjust", b: "inventory.adjust.approve", label: "request adjustment and approve adjustment" },
];
