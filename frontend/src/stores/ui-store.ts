"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { isMockMode } from "@/lib/api/config";
import { type Accent, DEFAULT_ACCENT, DEFAULT_FONT_SIZE, type FontSize, isAccent, isFontSize } from "@/lib/appearance";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Saved branch and terminal ids from mock mode ("br-tk", "term-tk1") mean nothing to the real
 * API, so in live mode anything that is not a UUID falls back to the defaults.
 */
function liveSafe(saved: Partial<UiState>): Partial<UiState> {
  const out = { ...saved };
  if (out.accent !== undefined && !isAccent(out.accent)) delete out.accent;
  if (out.fontSize !== undefined && !isFontSize(out.fontSize)) delete out.fontSize;
  if (isMockMode) return out;
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
  accent: Accent;
  fontSize: FontSize;
  toggleSidebar: () => void;
  setBranch: (id: string) => void;
  setLanguage: (language: "en" | "km") => void;
  setTerminal: (id: string | null) => void;
  setAccent: (accent: Accent) => void;
  setFontSize: (fontSize: FontSize) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      branchId: "all",
      language: "en",
      terminalId: null,
      accent: DEFAULT_ACCENT,
      fontSize: DEFAULT_FONT_SIZE,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setBranch: (branchId) => set({ branchId }),
      setLanguage: (language) => set({ language }),
      setTerminal: (terminalId) => set({ terminalId }),
      setAccent: (accent) => set({ accent }),
      setFontSize: (fontSize) => set({ fontSize }),
    }),
    {
      name: "pims.ui",
      storage: createJSONStorage(() => localStorage),
      skipHydration: true,
      merge: (saved, current) => ({ ...current, ...liveSafe((saved ?? {}) as Partial<UiState>) }),
    },
  ),
);
