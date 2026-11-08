import type { ActiveStatus, ID, IsoDateTime } from "./common";

export const PERMISSIONS = [
  "dashboard.view",
  "reports.consolidated",
  "pos.sell",
  "pos.hold",
  "pos.discount",
  "pos.override",
  "pos.cancel",
  "sales.view",
  "sales.view_all",
  "sales.void",
  "returns.create",
  "returns.approve",
  "products.view",
  "products.create",
  "products.edit",
  "products.delete",
  "pricing.view",
  "pricing.edit",
  "costs.view",
  "inventory.view",
  "inventory.adjust",
  "inventory.adjust.approve",
  "inventory.transfer",
  "inventory.transfer.approve",
  "inventory.count",
  "inventory.count.approve",
  "inventory.reverse",
  "purchasing.view",
  "purchasing.create",
  "purchasing.approve",
  "receiving.create",
  "receiving.post",
  "receiving.exception",
  "suppliers.view",
  "suppliers.manage",
  "customers.view",
  "customers.manage",
  "customers.personal_data",
  "promotions.view",
  "promotions.manage",
  "cash.session.open",
  "cash.session.close",
  "cash.session.approve",
  "cash.session.view",
  "cash.session.view_all",
  "reports.sales",
  "reports.tax",
  "reports.profit",
  "reports.inventory",
  "reports.purchasing",
  "reports.cash",
  "reports.business",
  "reports.exceptions",
  "reports.export",
  "expenses.view",
  "expenses.create",
  "expenses.approve",
  "users.view",
  "users.manage",
  "roles.manage",
  "audit.view",
  "settings.view",
  "settings.manage",
  "imports.manage",
  "alerts.view",
  "alerts.manage",
] as const;

export type Permission = (typeof PERMISSIONS)[number];

export type RoleCode =
  | "SYSADMIN"
  | "OWNER"
  | "STOREMGR"
  | "BRMGR"
  | "INVMGR"
  | "PUROFF"
  | "CASHIER"
  | "SALES"
  | "WHSTAFF"
  | "ACCT"
  | "AUDITOR"
  | "READONLY"
  | "CUSTOM";

export interface RoleLimits {
  /** Maximum discount % without approval. */
  discountPct: number;
  /** Maximum price reduction per line without approval (USD). */
  overrideAmount: number;
  /** Maximum refund without approval (USD). */
  refundAmount: number;
  /** Maximum adjustment cost value without approval (USD). */
  adjustmentValue: number;
  /** Maximum purchase order value this role can approve (USD). */
  poApprovalLimit: number;
}

export interface Role {
  id: ID;
  code: RoleCode;
  name: string;
  description: string;
  permissions: Permission[];
  limits: RoleLimits;
  system: boolean;
}

export interface User {
  id: ID;
  username: string;
  email: string;
  fullName: string;
  phone: string;
  language: "en" | "km";
  status: ActiveStatus;
  roleIds: ID[];
  branchIds: ID[];
  warehouseIds: ID[];
  terminalIds: ID[];
  employeeId: ID | null;
  hasPin: boolean;
  mfaEnabled: boolean;
  lastLoginAt: IsoDateTime | null;
  lockedUntil: IsoDateTime | null;
  createdAt: IsoDateTime;
}

/** The signed-in user with effective permissions, as returned by /auth/me. */
export interface SessionUser extends User {
  roles: { id: ID; code: RoleCode; name: string }[];
  permissions: Permission[];
  limits: RoleLimits;
  homePath: string;
}

export interface AuthResponse {
  accessToken: string;
  expiresIn: number;
  user: SessionUser;
}

export interface UserSession {
  id: ID;
  userId: ID;
  userName: string;
  device: string;
  createdAt: IsoDateTime;
  lastSeenAt: IsoDateTime;
  revoked: boolean;
}

export interface Employee {
  id: ID;
  code: string;
  nameEn: string;
  nameKm: string;
  position: string;
  branchId: ID;
  phone: string;
  status: ActiveStatus;
}

export interface AuditLog {
  id: ID;
  at: IsoDateTime;
  userId: ID | null;
  userName: string;
  action: string;
  module: string;
  entity: string;
  entityId: string;
  branchId: ID | null;
  before: string | null;
  after: string | null;
  flagged: boolean;
}

export interface ApprovalGrant {
  token: string;
  approverId: ID;
  approverName: string;
  expiresAt: IsoDateTime;
}

export type ApprovalAction =
  | "DISCOUNT"
  | "PRICE_OVERRIDE"
  | "CANCEL_SALE"
  | "VOID_SALE"
  | "REFUND"
  | "SESSION_VARIANCE"
  | "CASH_MOVEMENT";

export interface PendingApprovalInfo {
  action: ApprovalAction;
  message: string;
}
