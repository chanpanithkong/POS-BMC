"use client";

import { useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "sonner";
import { ApiError, getErrorMessage } from "@/lib/api/errors";
import { useDialogs } from "@/components/shared/dialogs-provider";
import type { ApprovalAction } from "@/types";

/** Reusable read hook. Screens stay the same when the transport moves to the real API. */
export function useApiQuery<T>(key: QueryKey, fetcher: () => Promise<T>, options: { enabled?: boolean; refetchInterval?: number } = {}) {
  return useQuery({ queryKey: key, queryFn: fetcher, ...options });
}

interface MutationOptions<TResult> {
  success?: string | ((result: TResult) => string);
  onSuccess?: (result: TResult) => void;
  /** Percentage or amount shown to and bound by the approver. */
  approvalAmount?: number;
  silentError?: boolean;
}

/**
 * Write hook with standard toasts, cache refresh and supervisor-approval retry.
 * Writes affect several modules (a sale changes stock, alerts and reports), so all queries refresh.
 */
export function useApiMutation<TVars, TResult>(mutate: (vars: TVars, approvalToken?: string) => Promise<TResult>, options: MutationOptions<TResult> = {}) {
  const client = useQueryClient();
  const { approve } = useDialogs();
  const [isPending, setPending] = useState(false);

  const run = useCallback(
    async (vars: TVars): Promise<TResult | undefined> => {
      setPending(true);
      try {
        let result: TResult;
        try {
          result = await mutate(vars);
        } catch (error) {
          if (!(error instanceof ApiError) || !error.isApprovalRequired) throw error;
          const token = await approve({
            action: String(error.details[0]?.action ?? "") as ApprovalAction,
            message: error.message,
            amount: options.approvalAmount ?? 0,
          });
          if (!token) return undefined;
          result = await mutate(vars, token);
        }
        await client.invalidateQueries();
        if (options.success) toast.success(typeof options.success === "function" ? options.success(result) : options.success);
        options.onSuccess?.(result);
        return result;
      } catch (error) {
        if (!options.silentError) toast.error(getErrorMessage(error), { description: error instanceof ApiError ? error.code : undefined });
        throw error;
      } finally {
        setPending(false);
      }
    },
    [approve, client, mutate, options],
  );

  /** Variant for button handlers: errors have already been shown as a toast. */
  const fire = useCallback((vars: TVars) => run(vars).catch(() => undefined), [run]);

  return { run, fire, isPending };
}
