/**
 * Centralised API configuration. "mock" runs the in-browser mock server;
 * "live" sends the same requests to the FastAPI backend at NEXT_PUBLIC_API_URL.
 */
export const apiConfig = {
  baseUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1",
  mode: process.env.NEXT_PUBLIC_API_MODE === "live" ? "live" : "mock",
  mockLatencyMs: Number(process.env.NEXT_PUBLIC_MOCK_LATENCY_MS ?? 60),
  requestTimeoutMs: 15000,
} as const;

export const isMockMode = apiConfig.mode === "mock";
