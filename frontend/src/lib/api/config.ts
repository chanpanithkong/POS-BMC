/**
 * Centralised API configuration. "live" (the default) sends requests to the FastAPI backend at
 * NEXT_PUBLIC_API_URL; "mock" runs the in-browser mock server with sample data.
 *
 * The mock runs only when NEXT_PUBLIC_API_MODE is explicitly "mock", so a missing or unreadable
 * .env.local (it is git-ignored, so a fresh clone has none) never silently turns a real
 * installation into the demo. Both values are inlined at build time: restart `npm run dev`, or
 * run `npm run build` again, after changing them.
 */
const requestedMode = (process.env.NEXT_PUBLIC_API_MODE ?? "").trim().toLowerCase();

export const apiConfig = {
  baseUrl: (process.env.NEXT_PUBLIC_API_URL ?? "").trim() || "http://localhost:8000/api/v1",
  mode: requestedMode === "mock" ? "mock" : "live",
  mockLatencyMs: Number(process.env.NEXT_PUBLIC_MOCK_LATENCY_MS ?? 60),
  requestTimeoutMs: 15000,
} as const;

export const isMockMode = apiConfig.mode === "mock";
