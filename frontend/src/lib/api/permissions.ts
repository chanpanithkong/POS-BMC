import type { Permission, Role, SessionUser } from "@/types";
import { isMockMode } from "./config";
import { FRONTEND_TO_BACKEND } from "./permission-map";

/**
 * The backend names permissions `module.resource.action` (SRS 4.2); screens use the shorter
 * keys in `PERMISSIONS`. These helpers translate at the API boundary so no screen needs to
 * know the backend codes. The mock server already speaks the short keys, so mock mode passes
 * values through unchanged.
 */
const KEYS = Object.keys(FRONTEND_TO_BACKEND) as Permission[];
const KNOWN_CODES = new Set(Object.values(FRONTEND_TO_BACKEND));

export function toUiPermissions(codes: readonly string[]): Permission[] {
  if (isMockMode) return codes as Permission[];
  const held = new Set(codes);
  return KEYS.filter((key) => held.has(FRONTEND_TO_BACKEND[key]));
}

/**
 * Maps chosen keys back to backend codes. Codes the screens cannot show (for example
 * payments.payment.view) are kept from `original`, so saving a role never drops them.
 */
export function toBackendPermissions(keys: readonly Permission[], original: readonly string[] = []): string[] {
  if (isMockMode) return [...keys];
  const kept = original.filter((code) => !KNOWN_CODES.has(code));
  return [...new Set([...keys.map((key) => FRONTEND_TO_BACKEND[key]), ...kept])];
}

export function uiUser<T extends SessionUser>(user: T): T {
  return { ...user, permissions: toUiPermissions(user.permissions) };
}

/** Backend codes of each role as last loaded, used when saving edits. */
const roleCodes = new Map<string, string[]>();

export function uiRole(role: Role): Role {
  if (isMockMode) return role;
  roleCodes.set(role.id, role.permissions as string[]);
  return { ...role, permissions: toUiPermissions(role.permissions) };
}

/**
 * Shapes a role create/update for the backend: permission keys become codes, the read-only
 * `system` flag is dropped, and a new role gets a unique code derived from its name (the
 * screen sends the placeholder "CUSTOM").
 */
export function backendRoleInput<T extends { permissions?: Permission[]; system?: boolean; code?: string; name?: string }>(id: string | null, input: T): T {
  if (isMockMode) return input;
  const { system: _system, ...rest } = input;
  void _system;
  const out: Record<string, unknown> = { ...rest };
  if (input.permissions) out.permissions = toBackendPermissions(input.permissions, id ? roleCodes.get(id) ?? [] : []);
  if (!id && (!input.code || input.code === "CUSTOM") && input.name) {
    const base = input.name.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 24) || "ROLE";
    out.code = `${base}_${Math.random().toString(36).slice(2, 6).toUpperCase()}`.replace(/^(.)$/, "$1_X");
  }
  return out as T;
}
