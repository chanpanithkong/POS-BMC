"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef } from "react";
import { toast } from "sonner";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { ApiError, getErrorMessage } from "@/lib/api/errors";
import { newIdempotencyKey } from "@/lib/api/client";
import { salesApi } from "@/services";
import { usePosStore } from "@/stores/pos-store";
import type { AddPaymentInput, ApprovalAction, Sale, SaleOp } from "@/types";

/** POS commands. Operations run one at a time, so rapid scans never interleave (NFR-HW-001). */
export function usePosActions() {
  const client = useQueryClient();
  const { approve } = useDialogs();
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const setSale = usePosStore((s) => s.setSale);
  const finalizeKey = useRef<string | null>(null);

  const enqueue = useCallback(<T,>(task: () => Promise<T>) => {
    const next = chain.current.then(task, task);
    chain.current = next.catch(() => undefined);
    return next;
  }, []);

  const ensureSale = useCallback(async () => {
    const current = usePosStore.getState().sale;
    if (current && (current.status === "DRAFT" || current.status === "PENDING_PAYMENT")) return current;
    const created = await salesApi.create();
    setSale(created);
    finalizeKey.current = null;
    return created;
  }, [setSale]);

  const apply = useCallback(
    (buildOps: () => SaleOp[], approvalAmount = 0) =>
      enqueue(async () => {
        try {
          const sale = await ensureSale();
          const ops = buildOps();
          try {
            setSale(await salesApi.apply(sale.id, ops));
          } catch (error) {
            if (!(error instanceof ApiError) || !error.isApprovalRequired) throw error;
            const token = await approve({ action: String(error.details[0]?.action ?? "") as ApprovalAction, message: error.message, amount: approvalAmount });
            if (!token) return false;
            setSale(await salesApi.apply(sale.id, ops.map((op) => ({ ...op, approvalToken: token }))));
          }
          return true;
        } catch (error) {
          toast.error(getErrorMessage(error), { description: error instanceof ApiError ? error.code : undefined });
          return false;
        }
      }),
    [approve, enqueue, ensureSale, setSale],
  );

  const addPayment = useCallback(
    (input: AddPaymentInput) =>
      enqueue(async () => {
        const sale = usePosStore.getState().sale as Sale;
        const updated = await salesApi.addPayment(sale.id, input);
        setSale(updated);
        return updated;
      }),
    [enqueue, setSale],
  );

  const resolvePayment = useCallback(
    (paymentId: string, outcome: "COMPLETED" | "FAILED" | "CANCELLED", reference?: string, reason?: string) =>
      enqueue(async () => {
        const sale = usePosStore.getState().sale as Sale;
        const updated = await salesApi.resolvePayment(sale.id, paymentId, outcome, reference, reason);
        setSale(updated);
        return updated;
      }),
    [enqueue, setSale],
  );

  const finalize = useCallback(
    () =>
      enqueue(async () => {
        const sale = usePosStore.getState().sale as Sale;
        // One key per sale: a retry after a timeout returns the original result (BR-PAY-002).
        finalizeKey.current ??= newIdempotencyKey();
        const done = await salesApi.finalize(sale.id, finalizeKey.current);
        finalizeKey.current = null;
        usePosStore.getState().setCompleted(done);
        setSale(null);
        await client.invalidateQueries();
        return done;
      }),
    [client, enqueue, setSale],
  );

  const cancel = useCallback(
    (reason: string) =>
      enqueue(async () => {
        const sale = usePosStore.getState().sale;
        if (!sale) return false;
        try {
          try {
            await salesApi.cancel(sale.id, reason);
          } catch (error) {
            if (!(error instanceof ApiError) || !error.isApprovalRequired) throw error;
            const token = await approve({ action: "CANCEL_SALE", message: error.message });
            if (!token) return false;
            await salesApi.cancel(sale.id, reason, token);
          }
          setSale(null);
          await client.invalidateQueries({ queryKey: ["sales"] });
          return true;
        } catch (error) {
          toast.error(getErrorMessage(error));
          return false;
        }
      }),
    [approve, client, enqueue, setSale],
  );

  const resume = useCallback(
    (id: string) =>
      enqueue(async () => {
        try {
          const updated = await salesApi.apply(id, [{ type: "resume" }]);
          setSale(updated);
          if (updated.notices.length) toast.warning(updated.notices.join("; "));
          await client.invalidateQueries({ queryKey: ["sales"] });
          return true;
        } catch (error) {
          toast.error(getErrorMessage(error));
          return false;
        }
      }),
    [client, enqueue, setSale],
  );

  return { apply, addPayment, resolvePayment, finalize, cancel, resume };
}
