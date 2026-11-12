"use client";

import { create } from "zustand";
import type { CashSession, Sale } from "@/types";

/** Terminal-local working state. Totals on `sale` always come from the server response. */
interface PosState {
  sale: Sale | null;
  session: CashSession | null;
  selectedLineId: string | null;
  completed: Sale | null;
  setSale: (sale: Sale | null) => void;
  setSession: (session: CashSession | null) => void;
  selectLine: (id: string | null) => void;
  setCompleted: (sale: Sale | null) => void;
}

export const usePosStore = create<PosState>((set) => ({
  sale: null,
  session: null,
  selectedLineId: null,
  completed: null,
  setSale: (sale) =>
    set((state) => ({
      sale,
      selectedLineId:
        sale && sale.lines.some((l) => l.id === state.selectedLineId)
          ? state.selectedLineId
          : (sale?.lines[sale.lines.length - 1]?.id ?? null),
    })),
  setSession: (session) => set({ session }),
  selectLine: (selectedLineId) => set({ selectedLineId }),
  setCompleted: (completed) => set({ completed }),
}));
