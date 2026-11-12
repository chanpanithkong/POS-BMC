"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { type ReactNode, useEffect, useState } from "react";
import { DialogsProvider } from "@/components/shared/dialogs-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { authBridge } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { authApi } from "@/services";
import { useAuthStore } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";

export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 10_000,
            refetchOnWindowFocus: false,
            retry: (count, error) => !(error instanceof ApiError && error.status < 500 && error.status !== 0) && count < 1,
          },
        },
      }),
  );

  useEffect(() => {
    void useUiStore.persist.rehydrate();
    authBridge.setTerminal(useUiStore.getState().terminalId);
    const unsubscribe = useUiStore.subscribe((state) => authBridge.setTerminal(state.terminalId));
    authBridge.onUnauthorized(() => useAuthStore.getState().expire());
    authBridge.onRefresh(async () => {
      const auth = await authApi.refresh();
      useAuthStore.getState().applyAuth(auth);
      return auth.accessToken;
    });
    void useAuthStore.getState().hydrate();
    return unsubscribe;
  }, []);

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        <TooltipProvider delayDuration={200}>
          <DialogsProvider>{children}</DialogsProvider>
          <Toaster richColors position="top-right" closeButton />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
