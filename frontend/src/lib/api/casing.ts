/**
 * The FastAPI contract uses snake_case JSON and decimal strings for money and
 * quantities (SRS 13.1). The UI uses camelCase and numbers for display only;
 * authoritative values are always computed by the server. These helpers run at
 * the HTTP boundary so no screen needs to know about the wire format.
 */
const DECIMAL_KEY =
  /(amount|price|cost|total|balance|qty|quantity|rate|value|tendered|variance|rounding|subtotal|onhand|reserved|available|factor|base)$/i;

function toCamel(key: string) {
  return key.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
}

function toSnake(key: string) {
  return key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function fromWire(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(fromWire);
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const [rawKey, raw] of Object.entries(value)) {
    const key = toCamel(rawKey);
    out[key] =
      typeof raw === "string" && DECIMAL_KEY.test(key) && /^-?\d+(\.\d+)?$/.test(raw)
        ? Number(raw)
        : fromWire(raw);
  }
  return out;
}

export function toWire(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(toWire);
  if (!isPlainObject(value)) return value;
  const out: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(value)) {
    out[toSnake(key)] =
      typeof raw === "number" && DECIMAL_KEY.test(key) ? String(raw) : toWire(raw);
  }
  return out;
}
