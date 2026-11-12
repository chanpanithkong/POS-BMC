import type { ApiErrorBody, ListParams } from "@/types";
import { apiConfig } from "./config";
import { fromWire, toWire } from "./casing";
import { ApiError } from "./errors";

export interface ApiRequest {
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  path: string;
  query?: ListParams;
  body?: unknown;
  /** Attach an Idempotency-Key header. Pass a stable key to make a retry safe. */
  idempotencyKey?: string;
  terminalId?: string | null;
}

type Transport = (request: ApiRequest, token: string | null) => Promise<unknown>;

/** Holds the access token in memory only. The refresh token belongs in an HttpOnly cookie. */
let accessToken: string | null = null;
let terminalId: string | null = null;
let onUnauthorized: (() => void) | null = null;

export const authBridge = {
  setToken(token: string | null) {
    accessToken = token;
  },
  getToken() {
    return accessToken;
  },
  setTerminal(id: string | null) {
    terminalId = id;
  },
  onUnauthorized(handler: () => void) {
    onUnauthorized = handler;
  },
};

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

function buildUrl(path: string, query?: ListParams) {
  const url = new URL(`${apiConfig.baseUrl}${path}`);
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`), String(value));
    }
  });
  return url;
}

const httpTransport: Transport = async (request, token) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), apiConfig.requestTimeoutMs);
  try {
    const response = await fetch(buildUrl(request.path, request.query), {
      method: request.method,
      credentials: "include",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(request.idempotencyKey ? { "Idempotency-Key": request.idempotencyKey } : {}),
        ...(request.terminalId ? { "X-Terminal-Id": request.terminalId } : {}),
      },
      body: request.body === undefined ? undefined : JSON.stringify(toWire(request.body)),
    });
    if (response.status === 204) return undefined;
    const payload: unknown = await response.json();
    if (!response.ok) throw ApiError.fromBody(response.status, payload as ApiErrorBody);
    return fromWire(payload);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(504, "PROVIDER_TIMEOUT", "The server took too long to respond. Please retry.");
    }
    throw new ApiError(0, "NETWORK_ERROR", "Cannot reach the server. Check the connection and retry.");
  } finally {
    clearTimeout(timeout);
  }
};

const mockTransport: Transport = async (request, token) => {
  const { handleMockRequest } = await import("@/mock-server/router");
  return handleMockRequest(request, token);
};

const transport: Transport = apiConfig.mode === "live" ? httpTransport : mockTransport;

/** Single entry point for every backend call in the application. */
export async function apiRequest<T>(request: ApiRequest): Promise<T> {
  try {
    return (await transport({ ...request, terminalId: request.terminalId ?? terminalId }, accessToken)) as T;
  } catch (error) {
    if (error instanceof ApiError && error.isAuthError && !request.path.startsWith("/auth/")) {
      onUnauthorized?.();
    }
    throw error;
  }
}

export const http = {
  get: <T>(path: string, query?: ListParams) => apiRequest<T>({ method: "GET", path, query }),
  post: <T>(path: string, body?: unknown, idempotencyKey?: string) =>
    apiRequest<T>({ method: "POST", path, body, idempotencyKey }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>({ method: "PATCH", path, body }),
  delete: <T>(path: string) => apiRequest<T>({ method: "DELETE", path }),
};
