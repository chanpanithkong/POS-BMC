import { ApiError } from "@/lib/api/errors";
import type {
  ApiFieldError, AppNotification, AuditLog, Branch, Currency, DocumentType, ListParams, ListResponse, NotificationKind,
  Permission, RoleLimits,
} from "@/types";
import type { MockDb, UserRecord } from "./db";

export interface Ctx {
  db: MockDb;
  user: UserRecord | null;
  permissions: Set<Permission>;
  limits: RoleLimits;
  params: Record<string, string>;
  query: ListParams;
  body: unknown;
  terminalId: string | null;
  now: Date;
  touchedProducts: Set<string>;
}

export const uid = (prefix: string) => `${prefix}-${crypto.randomUUID().slice(0, 13)}`;

/** Rounds away binary floating-point noise. The real backend uses Decimal (NFR-INT-010). */
export const round = (value: number, dp = 2) => {
  const f = 10 ** dp;
  return Math.round((value + Number.EPSILON * Math.sign(value)) * f) / f;
};

export const fail = (status: number, code: string, message: string, details: ApiFieldError[] = []): never => {
  throw new ApiError(status, code, message, details);
};

export const notFound = (what = "Record"): never => fail(404, "NOT_FOUND", `${what} not found.`);

export const validation = (field: string, message: string): never =>
  fail(422, "VALIDATION_ERROR", message, [{ field, message }]);

export const badState = (message: string): never => fail(409, "INVALID_STATE_TRANSITION", message);

export function requireUser(ctx: Ctx): UserRecord {
  if (!ctx.user) fail(401, "NOT_AUTHENTICATED", "Please sign in to continue.");
  return ctx.user as UserRecord;
}

export function can(ctx: Ctx, permission: Permission) {
  return ctx.permissions.has(permission);
}

export function requirePerm(ctx: Ctx, ...anyOf: Permission[]) {
  requireUser(ctx);
  if (!anyOf.some((p) => ctx.permissions.has(p))) {
    fail(403, "FORBIDDEN", "You do not have permission to do this.");
  }
}

export const canSeeCost = (ctx: Ctx) => ctx.permissions.has("costs.view");

/** Branch scope (BR-SEC-001). Consolidated users see all assigned branches. */
export function allowedBranchIds(ctx: Ctx): string[] {
  const user = requireUser(ctx);
  return user.branchIds.length ? user.branchIds : ctx.db.branches.map((b) => b.id);
}

export function assertBranch(ctx: Ctx, branchId: string | null) {
  if (branchId && !allowedBranchIds(ctx).includes(branchId)) notFound();
}

/** Resolves the branch filter from the query, applying user scope. */
export function branchFilter(ctx: Ctx): (branchId: string | null) => boolean {
  const allowed = new Set(allowedBranchIds(ctx));
  const requested = ctx.query.branchId ? String(ctx.query.branchId) : null;
  if (requested && requested !== "all") {
    if (!allowed.has(requested)) notFound();
    return (id) => id === requested;
  }
  return (id) => id === null || allowed.has(id);
}

export function list<T>(items: T[]): ListResponse<T> {
  return { items, total: items.length, nextCursor: null };
}

export function getBranch(db: MockDb, id: string): Branch {
  return db.branches.find((b) => b.id === id) ?? (notFound("Branch") as never);
}

function phnomPenhDate(date: Date) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Phnom_Penh",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

/** Server-derived business date honouring the branch's day cut-off (BR-SAL-008). */
export function businessDate(db: MockDb, branchId: string | null, at: Date) {
  const branch = db.branches.find((b) => b.id === branchId);
  const [h, m] = (branch?.dayCutoff ?? "00:00").split(":").map(Number);
  return phnomPenhDate(new Date(at.getTime() - (h * 60 + m) * 60_000));
}

export function nextDocNo(ctx: Ctx, type: DocumentType, branchCode?: string | null) {
  const seq = ctx.db.sequences.find((s) => s.docType === type);
  if (!seq) return fail(500, "CONFIG_ERROR", `Numbering is not configured for ${type}.`);
  const year = ctx.now.getFullYear();
  const scope = `${type}:${seq.includeBranch ? branchCode ?? "HQ" : ""}:${seq.includeYear ? year : ""}`;
  const value = ctx.db.sequenceCounters[scope] ?? seq.nextValue;
  ctx.db.sequenceCounters[scope] = value + 1;
  return [seq.prefix, seq.includeBranch ? branchCode ?? "HQ" : null, seq.includeYear ? year : null, String(value).padStart(seq.padding, "0")]
    .filter(Boolean)
    .join("-");
}

export function audit(
  ctx: Ctx,
  action: string,
  module: string,
  entity: string,
  entityId: string,
  options: { before?: unknown; after?: unknown; branchId?: string | null; flagged?: boolean; userName?: string } = {},
) {
  const entry: AuditLog = {
    id: uid("aud"),
    at: ctx.now.toISOString(),
    userId: ctx.user?.id ?? null,
    userName: options.userName ?? ctx.user?.fullName ?? "System",
    action,
    module,
    entity,
    entityId,
    branchId: options.branchId ?? null,
    before: options.before === undefined ? null : JSON.stringify(options.before),
    after: options.after === undefined ? null : JSON.stringify(options.after),
    flagged: options.flagged ?? false,
  };
  ctx.db.auditLogs.unshift(entry);
}

export function notify(
  ctx: Ctx,
  kind: NotificationKind,
  title: string,
  message: string,
  options: { link?: string; permission?: Permission; branchId?: string | null } = {},
) {
  const entry: AppNotification = {
    id: uid("ntf"),
    kind,
    title,
    message,
    link: options.link ?? null,
    read: false,
    createdAt: ctx.now.toISOString(),
    audiencePermission: options.permission ?? null,
    branchId: options.branchId ?? null,
  };
  ctx.db.notifications.unshift(entry);
}

export function currentRate(db: MockDb, from: Currency = "USD", to: Currency = "KHR"): number {
  const rate = [...db.exchangeRates]
    .filter((r) => r.from === from && r.to === to)
    .sort((a, b) => b.effectiveAt.localeCompare(a.effectiveAt))[0];
  if (!rate) return fail(422, "VALIDATION_ERROR", "Exchange rate not set for KHR.");
  return rate.rate;
}

/** SoD check for document approvals performed by the signed-in user (BR-SEC-002). */
export function assertNotSelfApproval(ctx: Ctx, initiatorId: string, label: string) {
  const user = requireUser(ctx);
  if (user.id !== initiatorId) return false;
  if (!ctx.db.settings.reducedSodMode) {
    fail(403, "SOD_VIOLATION", `You cannot approve your own ${label}.`);
  }
  return true;
}

export function consumeApproval(ctx: Ctx, token: string | undefined, action: string, requesterId: string) {
  if (!token) return null;
  const record = ctx.db.approvalTokens.find((t) => t.token === token);
  if (!record || record.used || record.expiresAt < ctx.now.getTime() || record.action !== action) {
    return fail(403, "APPROVAL_REQUIRED", "This approval has expired. Please request it again.", [{ message: "expired", action }]);
  }
  if (record.requesterId !== requesterId) fail(403, "SOD_VIOLATION", "This approval belongs to a different request.");
  record.used = true;
  return record;
}

export const requireApproval = (action: string, message: string): never =>
  fail(403, "APPROVAL_REQUIRED", message, [{ message, action }]);

export function requiredString(value: unknown, field: string, label: string): string {
  if (typeof value !== "string" || !value.trim()) return validation(field, `${label} is required.`);
  return value.trim();
}

export function positive(value: unknown, field: string, label: string): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return validation(field, `${label} must be greater than zero.`);
  return n;
}

export function inDateRange(date: string | null | undefined, query: ListParams) {
  if (!date) return false;
  const d = date.slice(0, 10);
  if (query.dateFrom && d < String(query.dateFrom)) return false;
  if (query.dateTo && d > String(query.dateTo)) return false;
  return true;
}
