"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { isMockMode } from "@/lib/api/config";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Saved branch and terminal ids from mock mode ("br-tk", "term-tk1") mean nothing to the real
 * API, so in live mode anything that is not a UUID falls back to the defaults.
 */
function liveSafe(saved: Partial<UiState>): Partial<UiState> {
  if (isMockMode) return saved;
  const out = { ...saved };
  if (out.branchId !== undefined && out.branchId !== "all" && !UUID.test(out.branchId)) out.branchId = "all";
  if (out.terminalId && !UUID.test(out.terminalId)) out.terminalId = null;
  return out;
}

interface UiState {
  sidebarCollapsed: boolean;
  /** "all" means consolidated across the user's permitted branches. */
  branchId: string;
  language: "en" | "km";
  terminalId: string | null;
  toggleSidebar: () => void;
  setBranch: (id: string) => void;
  setLanguage: (language: "en" | "km") => void;
  setTerminal: (id: string | null) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      branchId: "all",
      language: "en",
      terminalId: null,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setBranch: (branchId) => set({ branchId }),
      setLanguage: (language) => set({ language }),
      setTerminal: (terminalId) => set({ terminalId }),
    }),
    {
      name: "pims.ui",
      storage: createJSONStorage(() => localStorage),
      skipHydration: true,
      merge: (saved, current) => ({ ...current, ...liveSafe((saved ?? {}) as Partial<UiState>) }),
    },
  ),
);
