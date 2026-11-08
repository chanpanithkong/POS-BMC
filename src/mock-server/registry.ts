import type { Permission } from "@/types";
import { audit, fail, list, requirePerm, uid, type Ctx } from "./core";
import type { MockDb } from "./db";

export type Handler = (ctx: Ctx) => unknown;
type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

export interface Route {
  method: Method;
  pattern: RegExp;
  keys: string[];
  handler: Handler;
  isPublic: boolean;
}

export const routes: Route[] = [];

function register(method: Method, path: string, handler: Handler, isPublic = false) {
  const keys: string[] = [];
  const pattern = new RegExp(
    `^${path.replace(/:([a-zA-Z]+)/g, (_, key: string) => {
      keys.push(key);
      return "([^/]+)";
    })}$`,
  );
  routes.push({ method, pattern, keys, handler, isPublic });
}

export const GET = (path: string, handler: Handler, isPublic = false) => register("GET", path, handler, isPublic);
export const POST = (path: string, handler: Handler, isPublic = false) => register("POST", path, handler, isPublic);
export const PATCH = (path: string, handler: Handler) => register("PATCH", path, handler);
export const DELETE = (path: string, handler: Handler) => register("DELETE", path, handler);

type Collection<T> = { [K in keyof MockDb]: MockDb[K] extends T[] ? K : never }[keyof MockDb];

interface CrudOptions<T> {
  view: Permission[];
  manage: Permission[];
  prefix: string;
  module: string;
  validate?: (ctx: Ctx, input: Partial<T>, existing: T | null) => void;
  /** Throw to block deletion, for example when a record is in use. */
  beforeDelete?: (ctx: Ctx, row: T) => void;
  decorate?: (ctx: Ctx, row: T) => T;
}

/** Standard list/create/update/delete routes for simple master data. */
export function crud<T extends { id: string }>(path: string, key: Collection<T>, options: CrudOptions<T>) {
  const rows = (ctx: Ctx) => ctx.db[key] as unknown as T[];
  GET(path, (ctx) => {
    requirePerm(ctx, ...options.view);
    return list(options.decorate ? rows(ctx).map((r) => options.decorate!(ctx, r)) : rows(ctx));
  });
  POST(path, (ctx) => {
    requirePerm(ctx, ...options.manage);
    const input = ctx.body as Partial<T>;
    options.validate?.(ctx, input, null);
    const row = { ...input, id: uid(options.prefix) } as T;
    rows(ctx).unshift(row);
    audit(ctx, "CREATE", options.module, String(key), row.id, { after: row });
    return row;
  });
  PATCH(`${path}/:id`, (ctx) => {
    requirePerm(ctx, ...options.manage);
    const row = rows(ctx).find((r) => r.id === ctx.params.id);
    if (!row) return fail(404, "NOT_FOUND", "Record not found.");
    const input = ctx.body as Partial<T>;
    options.validate?.(ctx, input, row);
    const before = { ...row };
    Object.assign(row, input, { id: row.id });
    audit(ctx, "UPDATE", options.module, String(key), row.id, { before, after: row });
    return row;
  });
  DELETE(`${path}/:id`, (ctx) => {
    requirePerm(ctx, ...options.manage);
    const collection = rows(ctx);
    const index = collection.findIndex((r) => r.id === ctx.params.id);
    if (index < 0) return fail(404, "NOT_FOUND", "Record not found.");
    options.beforeDelete?.(ctx, collection[index]);
    audit(ctx, "DELETE", options.module, String(key), ctx.params.id, { before: collection[index] });
    collection.splice(index, 1);
    return undefined;
  });
}

export function assertUniqueCode<T extends { id: string; code: string }>(rows: T[], code: string | undefined, existing: T | null, label = "Code") {
  if (code === undefined) return;
  if (!code.trim()) fail(422, "VALIDATION_ERROR", `${label} is required.`, [{ field: "code", message: `${label} is required.` }]);
  if (rows.some((r) => r.code.toLowerCase() === code.trim().toLowerCase() && r.id !== existing?.id)) {
    fail(409, "DUPLICATE_CODE", `${label} "${code}" already exists.`, [{ field: "code", message: `${label} already exists.` }]);
  }
}
