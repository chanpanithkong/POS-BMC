import type { ApprovalGrant, AuthResponse, Permission, Role, RoleLimits, SessionUser, UserSession } from "@/types";
import {
  allowedBranchIds, audit, fail, list, notFound, requirePerm, requireUser, requiredString, uid, validation, type Ctx,
} from "../core";
import type { MockDb, UserRecord } from "../db";
import { DELETE, GET, PATCH, POST, assertUniqueCode, crud } from "../registry";
import { SOD_CONFLICTS } from "@/constants/roles";

const LOCK_ATTEMPTS = 5;
const LOCK_WINDOW_MS = 15 * 60_000;

export function publicUser(user: UserRecord) {
  const { demoPassword: _p, demoPin: _q, failedAttempts: _f, ...rest } = user;
  void _p; void _q; void _f;
  return rest;
}

export function effective(db: MockDb, user: UserRecord): { permissions: Set<Permission>; limits: RoleLimits; roles: Role[] } {
  const roles = db.roles.filter((r) => user.roleIds.includes(r.id));
  const permissions = new Set(roles.flatMap((r) => r.permissions));
  const limits: RoleLimits = { discountPct: 0, overrideAmount: 0, refundAmount: 0, adjustmentValue: 0, poApprovalLimit: 0 };
  for (const role of roles) {
    (Object.keys(limits) as (keyof RoleLimits)[]).forEach((k) => (limits[k] = Math.max(limits[k], role.limits[k])));
  }
  return { permissions, limits, roles };
}

function sessionUser(db: MockDb, user: UserRecord): SessionUser {
  const { permissions, limits, roles } = effective(db, user);
  return {
    ...publicUser(user),
    roles: roles.map((r) => ({ id: r.id, code: r.code, name: r.name })),
    permissions: [...permissions],
    limits,
    homePath: roles.some((r) => r.code === "CASHIER" || r.code === "SALES") ? "/pos" : "/dashboard",
  };
}

function openUserSession(ctx: Ctx, user: UserRecord, device: string): AuthResponse {
  const session: UserSession = {
    id: uid("ses"),
    userId: user.id,
    userName: user.fullName,
    device,
    createdAt: ctx.now.toISOString(),
    lastSeenAt: ctx.now.toISOString(),
    revoked: false,
  };
  ctx.db.sessions.unshift(session);
  user.lastLoginAt = ctx.now.toISOString();
  user.failedAttempts = [];
  return { accessToken: `mock.${session.id}`, expiresIn: 900, user: sessionUser(ctx.db, user) };
}

function assertNotLocked(ctx: Ctx, user: UserRecord) {
  if (user.lockedUntil && user.lockedUntil > ctx.now.toISOString()) {
    const until = new Date(user.lockedUntil).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    fail(401, "ACCOUNT_LOCKED", `Account locked until ${until}.`);
  }
}

function recordFailure(ctx: Ctx, user: UserRecord) {
  const cutoff = ctx.now.getTime() - LOCK_WINDOW_MS;
  user.failedAttempts = [...user.failedAttempts.filter((t) => new Date(t).getTime() > cutoff), ctx.now.toISOString()];
  audit(ctx, "LOGIN_FAILED", "AUTH", "user", user.id, { userName: user.fullName });
  if (user.failedAttempts.length >= LOCK_ATTEMPTS) {
    user.lockedUntil = new Date(ctx.now.getTime() + LOCK_WINDOW_MS).toISOString();
    audit(ctx, "ACCOUNT_LOCKED", "AUTH", "user", user.id, { userName: user.fullName, flagged: true });
  }
}

/** Failures here persist even though the request errors, so they are written by the router's rollback hook. */
export const pendingFailureWrites = new Map<string, (ctx: Ctx) => void>();

POST("/auth/login", (ctx) => {
  const { username, password } = ctx.body as { username: string; password: string };
  const user = ctx.db.users.find((u) => u.username === username?.trim() || u.email === username?.trim());
  if (!user) return fail(401, "NOT_AUTHENTICATED", "Incorrect sign-in details");
  assertNotLocked(ctx, user);
  if (user.status !== "ACTIVE") return fail(401, "NOT_AUTHENTICATED", "Incorrect sign-in details");
  if (user.demoPassword !== password) {
    pendingFailureWrites.set("login", (c) => {
      const target = c.db.users.find((u) => u.id === user.id);
      if (target) recordFailure(c, target);
    });
    return fail(401, "NOT_AUTHENTICATED", "Incorrect sign-in details");
  }
  const result = openUserSession(ctx, user, "Web browser");
  ctx.user = user;
  audit(ctx, "LOGIN", "AUTH", "user", user.id, { userName: user.fullName });
  return result;
}, true);

POST("/auth/pin", (ctx) => {
  const { pin, terminalId } = ctx.body as { pin: string; terminalId: string };
  const terminal = ctx.db.terminals.find((t) => t.id === (terminalId ?? ctx.terminalId) && t.status === "ACTIVE");
  if (!terminal) return fail(401, "TERMINAL_NOT_REGISTERED", "This device is not registered as a POS terminal.");
  const user = ctx.db.users.find((u) => u.demoPin === pin && u.status === "ACTIVE" && (!u.branchIds.length || u.branchIds.includes(terminal.branchId)));
  if (!user) return fail(401, "NOT_AUTHENTICATED", "Incorrect PIN");
  assertNotLocked(ctx, user);
  const result = openUserSession(ctx, user, `Terminal ${terminal.name}`);
  ctx.user = user;
  audit(ctx, "PIN_LOGIN", "AUTH", "user", user.id, { userName: user.fullName, branchId: terminal.branchId });
  return result;
}, true);

POST("/auth/logout", (ctx) => {
  const user = requireUser(ctx);
  audit(ctx, "LOGOUT", "AUTH", "user", user.id);
  const token = String(ctx.query.__token ?? "");
  const session = ctx.db.sessions.find((s) => `mock.${s.id}` === token);
  if (session) session.revoked = true;
  return undefined;
});

POST("/auth/forgot-password", (ctx) => {
  requiredString((ctx.body as { email: string }).email, "email", "Email");
  return { message: "If that account exists, a single-use reset link valid for 30 minutes will be emailed." };
}, true);

POST("/auth/change-password", (ctx) => {
  const user = requireUser(ctx);
  const { currentPassword, newPassword } = ctx.body as { currentPassword: string; newPassword: string };
  if (user.demoPassword !== currentPassword) return validation("currentPassword", "Current password is incorrect.");
  if (!newPassword || newPassword.length < 12) return validation("newPassword", "Password must be at least 12 characters.");
  user.demoPassword = newPassword;
  audit(ctx, "PASSWORD_CHANGED", "AUTH", "user", user.id);
  return { ok: true };
});

GET("/auth/me", (ctx) => sessionUser(ctx.db, requireUser(ctx)));

PATCH("/auth/me", (ctx) => {
  const user = requireUser(ctx);
  const { fullName, phone, language } = ctx.body as Partial<UserRecord>;
  if (fullName !== undefined) user.fullName = requiredString(fullName, "fullName", "Name");
  if (phone !== undefined) user.phone = phone;
  if (language !== undefined) user.language = language;
  audit(ctx, "PROFILE_UPDATED", "AUTH", "user", user.id);
  return sessionUser(ctx.db, user);
});

GET("/auth/sessions", (ctx) => {
  const user = requireUser(ctx);
  const all = ctx.permissions.has("users.manage");
  return list(ctx.db.sessions.filter((s) => !s.revoked && (all || s.userId === user.id)).slice(0, 100));
});

DELETE("/auth/sessions/:id", (ctx) => {
  const user = requireUser(ctx);
  const session = ctx.db.sessions.find((s) => s.id === ctx.params.id);
  if (!session) return notFound("Session");
  if (session.userId !== user.id) requirePerm(ctx, "users.manage");
  session.revoked = true;
  audit(ctx, "SESSION_REVOKED", "AUTH", "session", session.id);
  return undefined;
});

/** Supervisor PIN approval (BR-POS-004): single use, bound to action, 2-minute expiry. */
POST("/approvals/verify", (ctx) => {
  const requester = requireUser(ctx);
  const { pin, action, amount = 0 } = ctx.body as { pin: string; action: string; amount?: number };
  const required: Record<string, Permission> = {
    DISCOUNT: "pos.discount",
    PRICE_OVERRIDE: "pos.override",
    CANCEL_SALE: "pos.cancel",
    VOID_SALE: "sales.void",
    REFUND: "returns.approve",
    SESSION_VARIANCE: "cash.session.approve",
    CASH_MOVEMENT: "cash.session.approve",
  };
  const permission = required[action];
  if (!permission) return validation("action", "Unknown approval action.");
  const scope = allowedBranchIds(ctx);
  const approver = ctx.db.users.find(
    (u) => u.demoPin === pin && u.status === "ACTIVE" && (!u.branchIds.length || u.branchIds.some((b) => scope.includes(b))),
  );
  if (!approver) return fail(401, "NOT_AUTHENTICATED", "Incorrect supervisor PIN");
  const rights = effective(ctx.db, approver);
  if (!rights.permissions.has(permission)) return fail(403, "FORBIDDEN", `${approver.fullName} cannot approve this action.`);
  if (approver.id === requester.id && !ctx.db.settings.reducedSodMode) {
    return fail(403, "SOD_VIOLATION", "Approval must come from a different user.");
  }
  if (action === "DISCOUNT" && amount > rights.limits.discountPct) {
    return fail(403, "LIMIT_EXCEEDED", `${approver.fullName} can approve discounts up to ${rights.limits.discountPct}%.`);
  }
  if (action === "REFUND" && amount > rights.limits.refundAmount) {
    return fail(403, "LIMIT_EXCEEDED", `${approver.fullName} can approve refunds up to ${rights.limits.refundAmount} USD.`);
  }
  const grant: ApprovalGrant = {
    token: uid("apr"),
    approverId: approver.id,
    approverName: approver.fullName,
    expiresAt: new Date(ctx.now.getTime() + 2 * 60_000).toISOString(),
  };
  ctx.db.approvalTokens.push({ token: grant.token, action, approverId: approver.id, approverName: approver.fullName, requesterId: requester.id, expiresAt: ctx.now.getTime() + 120_000, used: false, amount });
  ctx.db.approvalTokens = ctx.db.approvalTokens.slice(-50);
  audit(ctx, "APPROVAL_GRANTED", "APPROVALS", action, grant.token, { after: { approver: approver.fullName, requester: requester.fullName, amount }, flagged: approver.id === requester.id });
  return grant;
});

// Users
GET("/users", (ctx) => {
  requirePerm(ctx, "users.view", "users.manage");
  return list(ctx.db.users.map(publicUser));
});

function validateUser(ctx: Ctx, input: Partial<UserRecord>, existing: UserRecord | null) {
  if (input.username !== undefined && ctx.db.users.some((u) => u.username === input.username && u.id !== existing?.id)) validation("username", "Username already exists.");
  if (input.email !== undefined && ctx.db.users.some((u) => u.email === input.email && u.id !== existing?.id)) validation("email", "Email already exists.");
}

POST("/users", (ctx) => {
  requirePerm(ctx, "users.manage");
  const input = ctx.body as Partial<UserRecord> & { pin?: string };
  validateUser(ctx, input, null);
  const user: UserRecord = {
    id: uid("usr"),
    username: requiredString(input.username, "username", "Username"),
    email: requiredString(input.email, "email", "Email"),
    fullName: requiredString(input.fullName, "fullName", "Name"),
    phone: input.phone ?? "",
    language: input.language ?? "en",
    status: "ACTIVE",
    roleIds: input.roleIds ?? [],
    branchIds: input.branchIds ?? [],
    warehouseIds: input.warehouseIds ?? [],
    terminalIds: input.terminalIds ?? [],
    employeeId: input.employeeId ?? null,
    hasPin: false,
    mfaEnabled: false,
    lastLoginAt: null,
    lockedUntil: null,
    createdAt: ctx.now.toISOString(),
    demoPassword: "demo-password",
    demoPin: null,
    failedAttempts: [],
  };
  ctx.db.users.unshift(user);
  audit(ctx, "USER_CREATED", "AUTH", "user", user.id, { after: publicUser(user) });
  return publicUser(user);
});

PATCH("/users/:id", (ctx) => {
  requirePerm(ctx, "users.manage");
  const user = ctx.db.users.find((u) => u.id === ctx.params.id);
  if (!user) return notFound("User");
  const input = ctx.body as Partial<UserRecord>;
  validateUser(ctx, input, user);
  const me = requireUser(ctx);
  const rolesChanged = input.roleIds && JSON.stringify(input.roleIds) !== JSON.stringify(user.roleIds);
  if (user.id === me.id && rolesChanged) {
    audit(ctx, "SELF_PERMISSION_ATTEMPT", "AUTH", "user", user.id, { flagged: true });
    return fail(403, "FORBIDDEN", "You cannot change your own permissions.");
  }
  const before = publicUser(user);
  const allowed: (keyof UserRecord)[] = ["fullName", "email", "phone", "language", "roleIds", "branchIds", "warehouseIds", "terminalIds", "employeeId", "username"];
  for (const key of allowed) if (input[key] !== undefined) Object.assign(user, { [key]: input[key] });
  audit(ctx, rolesChanged ? "PERMISSIONS_CHANGED" : "USER_UPDATED", "AUTH", "user", user.id, { before, after: publicUser(user) });
  return publicUser(user);
});

POST("/users/:id/status", (ctx) => {
  requirePerm(ctx, "users.manage");
  const user = ctx.db.users.find((u) => u.id === ctx.params.id);
  if (!user) return notFound("User");
  const me = requireUser(ctx);
  if (user.id === me.id) return fail(403, "FORBIDDEN", "You cannot deactivate your own account.");
  const { status } = ctx.body as { status: "ACTIVE" | "INACTIVE" };
  user.status = status;
  if (status === "INACTIVE") ctx.db.sessions.filter((s) => s.userId === user.id).forEach((s) => (s.revoked = true));
  audit(ctx, status === "ACTIVE" ? "USER_ACTIVATED" : "USER_DEACTIVATED", "AUTH", "user", user.id);
  return publicUser(user);
});

POST("/users/:id/unlock", (ctx) => {
  requirePerm(ctx, "users.manage");
  const user = ctx.db.users.find((u) => u.id === ctx.params.id);
  if (!user) return notFound("User");
  user.lockedUntil = null;
  user.failedAttempts = [];
  audit(ctx, "USER_UNLOCKED", "AUTH", "user", user.id);
  return publicUser(user);
});

POST("/users/:id/pin", (ctx) => {
  const me = requireUser(ctx);
  if (ctx.params.id !== me.id) requirePerm(ctx, "users.manage");
  const user = ctx.db.users.find((u) => u.id === ctx.params.id);
  if (!user) return notFound("User");
  const { pin } = ctx.body as { pin: string };
  if (!/^\d{4,6}$/.test(pin ?? "")) return validation("pin", "PIN must be 4 to 6 digits.");
  if ("0123456789".includes(pin) || "9876543210".includes(pin)) return validation("pin", "PIN must not be sequential.");
  const clash = ctx.db.users.some((u) => u.id !== user.id && u.demoPin === pin && u.branchIds.some((b) => user.branchIds.includes(b)));
  if (clash) return validation("pin", "PIN is already used at this branch.");
  user.demoPin = pin;
  user.hasPin = true;
  audit(ctx, "PIN_RESET", "AUTH", "user", user.id);
  return publicUser(user);
});

function validateRole(ctx: Ctx, input: Partial<Role>) {
  if (input.name !== undefined && !input.name.trim()) validation("name", "Role name is required.");
  const conflicts = SOD_CONFLICTS.filter((c) => input.permissions?.includes(c.a) && input.permissions?.includes(c.b));
  if (conflicts.length && !ctx.db.settings.reducedSodMode) {
    audit(ctx, "SOD_CONFLICT_ACCEPTED", "AUTH", "role", input.name ?? "", { after: conflicts.map((c) => c.label), flagged: true });
  }
}

crud<Role>("/roles", "roles", {
  view: ["users.view", "users.manage", "roles.manage"],
  manage: ["roles.manage"],
  prefix: "role",
  module: "AUTH",
  validate: validateRole,
  beforeDelete: (ctx, role) => {
    if (role.system) fail(409, "ROLE_IN_USE", "Default roles cannot be deleted.");
    if (ctx.db.users.some((u) => u.roleIds.includes(role.id))) fail(409, "ROLE_IN_USE", "This role is assigned to users.");
  },
});

crud("/employees", "employees", {
  view: ["users.view", "users.manage"],
  manage: ["users.manage"],
  prefix: "emp",
  module: "AUTH",
  validate: (ctx, input: Partial<{ code: string; id: string }>, existing) => assertUniqueCode(ctx.db.employees, input.code, existing as never, "Employee code"),
});

GET("/audit-logs", (ctx) => {
  requirePerm(ctx, "audit.view");
  return list(ctx.db.auditLogs.slice(0, 2000));
});

GET("/permissions/me/activity", (ctx) => {
  const user = requireUser(ctx);
  return list(ctx.db.auditLogs.filter((a) => a.userId === user.id).slice(0, 50));
});
