"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

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
    { name: "pims.ui", storage: createJSONStorage(() => localStorage), skipHydration: true },
  ),
);
