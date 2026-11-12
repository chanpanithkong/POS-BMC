import { ApiError } from "@/lib/api/errors";
import { apiConfig } from "@/lib/api/config";
import type { ApiRequest } from "@/lib/api/client";
import type { Permission, RoleLimits } from "@/types";
import { fail, notify, type Ctx } from "./core";
import { loadPersisted, peekDb, persistNow, persistSoon, setDb, type MockDb, type UserRecord } from "./db";
import { evaluateStockAlerts } from "./domain/inventory";
import { effective, pendingFailureWrites } from "./handlers/auth";
import { routes } from "./registry";
import { buildSeed } from "./seed";
import "./handlers/organization";
import "./handlers/catalog";
import "./handlers/sales";
import "./handlers/inventory";
import "./handlers/purchasing";
import "./handlers/customers";
import "./handlers/reports";

/** Server-side field filtering for cost visibility (BR-SEC-003). */
const COST_KEYS = new Set(["avgCost", "lastPurchaseCost", "unitCost", "costTotal", "totalCost", "valueImpact", "totalValue", "valueVariance", "grossProfit", "cost"]);
const SECRET_KEYS = new Set(["demoPassword", "demoPin", "failedAttempts"]);

function serialize(value: unknown, hideCost: boolean): unknown {
  if (Array.isArray(value)) return value.map((v) => serialize(v, hideCost));
  if (typeof value !== "object" || value === null) return value;
  const out: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(value)) {
    if (SECRET_KEYS.has(key) || (hideCost && COST_KEYS.has(key))) continue;
    out[key] = serialize(raw, hideCost);
  }
  return out;
}

function ensureDb(): MockDb {
  const existing = peekDb();
  if (existing) return existing;
  const db = loadPersisted() ?? buildSeed();
  setDb(db);
  persistSoon();
  return db;
}

function resolveUser(db: MockDb, token: string | null): UserRecord | null {
  if (!token) return null;
  const session = db.sessions.find((s) => `mock.${s.id}` === token && !s.revoked);
  if (!session) return null;
  session.lastSeenAt = new Date().toISOString();
  const user = db.users.find((u) => u.id === session.userId);
  return user?.status === "ACTIVE" ? user : null;
}

const EMPTY_LIMITS: RoleLimits = { discountPct: 0, overrideAmount: 0, refundAmount: 0, adjustmentValue: 0, poApprovalLimit: 0 };

const APPROVER_PERMISSION: Record<string, Permission> = {
  DISCOUNT: "pos.discount",
  PRICE_OVERRIDE: "pos.override",
  CANCEL_SALE: "pos.cancel",
  VOID_SALE: "sales.void",
  REFUND: "returns.approve",
  SESSION_VARIANCE: "cash.session.approve",
  CASH_MOVEMENT: "cash.session.approve",
};

function delay(ms: number) {
  return ms > 0 ? new Promise((resolve) => setTimeout(resolve, ms)) : Promise.resolve();
}

/** Serialises writes so concurrent requests cannot interleave (a stand-in for row locks). */
let queue: Promise<unknown> = Promise.resolve();

function execute(request: ApiRequest, token: string | null) {
  const db = ensureDb();
  const path = request.path.split("?")[0];
  const route = routes.find((r) => r.method === request.method && r.pattern.test(path));
  const correlationId = crypto.randomUUID();
  if (!route) throw new ApiError(404, "NOT_FOUND", `No mock handler for ${request.method} ${path}`, [], correlationId);

  const match = path.match(route.pattern) as RegExpMatchArray;
  const params = Object.fromEntries(route.keys.map((key, i) => [key, decodeURIComponent(match[i + 1])]));
  const user = resolveUser(db, token);
  if (!route.isPublic && !user) throw new ApiError(401, "SESSION_EXPIRED", "Your session has expired. Please sign in again.", [], correlationId);
  const rights = user ? effective(db, user) : { permissions: new Set<Permission>(), limits: EMPTY_LIMITS };

  const makeCtx = (target: MockDb): Ctx => ({
    db: target,
    user: user ? target.users.find((u) => u.id === user.id) ?? null : null,
    permissions: rights.permissions,
    limits: rights.limits,
    params,
    query: { ...request.query, __token: token ?? undefined },
    body: request.body,
    terminalId: request.terminalId ?? null,
    now: new Date(),
    touchedProducts: new Set(),
  });

  const mutating = request.method !== "GET";
  const idempotencyId = request.idempotencyKey ? `${request.terminalId ?? "web"}:${request.idempotencyKey}` : null;
  const bodyHash = JSON.stringify(request.body ?? null);
  if (idempotencyId) {
    const prior = db.idempotency[idempotencyId];
    if (prior) {
      if (prior.bodyHash !== bodyHash) throw new ApiError(409, "IDEMPOTENCY_KEY_REUSED", "This request key was already used with different data.", [], correlationId);
      return prior.response;
    }
  }

  // One command = one transaction: any failure restores the snapshot (NFR-REL-001).
  const snapshot = mutating ? structuredClone(db) : null;
  const ctx = makeCtx(db);
  const hideCost = !ctx.permissions.has("costs.view");
  try {
    const result = route.handler(ctx);
    if (mutating) {
      evaluateStockAlerts(ctx, ctx.touchedProducts);
      persistSoon();
    }
    const response = result === undefined ? undefined : serialize(structuredClone(result), hideCost);
    if (idempotencyId) {
      db.idempotency[idempotencyId] = { bodyHash, response, at: Date.now() };
      const keys = Object.keys(db.idempotency);
      if (keys.length > 300) delete db.idempotency[keys[0]];
    }
    return response;
  } catch (error) {
    if (snapshot) setDb(snapshot);
    const recovery = snapshot ? makeCtx(snapshot) : null;
    if (recovery) {
      pendingFailureWrites.forEach((write) => write(recovery));
      pendingFailureWrites.clear();
      if (error instanceof ApiError && error.code === "APPROVAL_REQUIRED") {
        const action = String(error.details[0]?.action ?? "");
        notify(recovery, action === "REFUND" ? "REFUND_APPROVAL" : "APPROVAL", "Approval requested", `${user?.fullName ?? "A user"}: ${error.message}`, {
          permission: APPROVER_PERMISSION[action],
          link: action === "REFUND" ? "/sales/returns" : null as never,
        });
      }
      persistSoon();
    }
    if (error instanceof ApiError) {
      throw new ApiError(error.status, error.code, error.message, error.details, correlationId);
    }
    console.error("Mock server error", error);
    throw new ApiError(500, "INTERNAL_ERROR", "Something went wrong on the server.", [], correlationId);
  }
}

export async function handleMockRequest(request: ApiRequest, token: string | null): Promise<unknown> {
  const run = queue.then(async () => {
    await delay(request.path.includes("/sales/") ? 0 : apiConfig.mockLatencyMs);
    return execute(request, token);
  });
  queue = run.catch(() => undefined);
  return run;
}

/** Discards the local demo data and rebuilds the seed. */
export function resetMockData() {
  const db = buildSeed();
  setDb(db);
  persistNow();
}

export function assertMockMode() {
  if (apiConfig.mode !== "mock") fail(400, "NOT_MOCK", "Demo data can only be reset in mock mode.");
}
