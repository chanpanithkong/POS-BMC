"use client";

import { create } from "zustand";
import { authBridge } from "@/lib/api/client";
import { isMockMode } from "@/lib/api/config";
import { authApi } from "@/services";
import type { AuthResponse, Permission, SessionUser } from "@/types";

/**
 * Frontend session state only. Hiding a screen here is a usability measure, not
 * security: every permission must be enforced by the backend (FR-AUTH-009). In
 * mock mode the token survives refresh through sessionStorage; with the real API
 * the access token stays in memory and is renewed from the HttpOnly refresh cookie.
 */
const TOKEN_KEY = "pims.mock-token";

interface AuthState {
  status: "loading" | "authenticated" | "anonymous";
  user: SessionUser | null;
  hydrate: () => Promise<void>;
  applyAuth: (auth: AuthResponse) => void;
  setUser: (user: SessionUser) => void;
  logout: () => Promise<void>;
  expire: () => void;
}

function storeToken(token: string | null) {
  authBridge.setToken(token);
  if (!isMockMode) return; // live API: the access token stays in memory; the refresh cookie restores the session
  try {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // Private browsing: the session simply will not survive a refresh.
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  status: "loading",
  user: null,
  hydrate: async () => {
    if (get().status === "authenticated") return;
    if (!isMockMode) {
      try {
        const auth = await authApi.refresh();
        storeToken(auth.accessToken);
        set({ status: "authenticated", user: auth.user });
      } catch {
        storeToken(null);
        set({ status: "anonymous", user: null });
      }
      return;
    }
    let token: string | null = null;
    try {
      token = window.sessionStorage.getItem(TOKEN_KEY);
    } catch {
      token = null;
    }
    if (!token) {
      set({ status: "anonymous", user: null });
      return;
    }
    authBridge.setToken(token);
    try {
      set({ status: "authenticated", user: await authApi.me() });
    } catch {
      storeToken(null);
      set({ status: "anonymous", user: null });
    }
  },
  applyAuth: (auth) => {
    storeToken(auth.accessToken);
    set({ status: "authenticated", user: auth.user });
  },
  setUser: (user) => set({ user }),
  logout: async () => {
    try {
      await authApi.logout();
    } finally {
      storeToken(null);
      set({ status: "anonymous", user: null });
    }
  },
  expire: () => {
    storeToken(null);
    set({ status: "anonymous", user: null });
  },
}));

export function usePermission(permission: Permission) {
  return useAuthStore((s) => s.user?.permissions.includes(permission) ?? false);
}

export function useCan() {
  const permissions = useAuthStore((s) => s.user?.permissions);
  return (...anyOf: Permission[]) => anyOf.some((p) => permissions?.includes(p));
}
