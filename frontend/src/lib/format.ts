const TZ = "Asia/Phnom_Penh";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });
const khr = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatUsd(value: number | null | undefined) {
  return usd.format(value ?? 0);
}

export function formatKhr(value: number | null | undefined) {
  return `៛${khr.format(value ?? 0)}`;
}

export function formatMoney(value: number | null | undefined, currency: "USD" | "KHR" = "USD") {
  return currency === "KHR" ? formatKhr(value) : formatUsd(value);
}

export function formatNumber(value: number | null | undefined) {
  return number.format(value ?? 0);
}

export function formatPercent(value: number | null | undefined) {
  return `${(value ?? 0).toFixed(1)}%`;
}

function parts(value: string | Date, options: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat("en-GB", { timeZone: TZ, ...options }).format(typeof value === "string" ? new Date(value) : value);
}

/** DD/MM/YYYY in Asia/Phnom_Penh (NFR-LOC-004). */
export function formatDate(value: string | Date | null | undefined) {
  if (!value) return "—";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-");
    return `${d}/${m}/${y}`;
  }
  return parts(value, { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function formatDateTime(value: string | Date | null | undefined) {
  if (!value) return "—";
  return parts(value, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).replace(",", "");
}

export function formatTime(value: string | Date | null | undefined) {
  if (!value) return "—";
  return parts(value, { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function todayIso() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function addDaysIso(iso: string, days: number) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function titleCase(value: string) {
  return value
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
