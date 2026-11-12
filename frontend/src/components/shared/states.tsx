"use client";

import { AlertTriangle, Inbox, Lock, RotateCw } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, getErrorMessage } from "@/lib/api/errors";

export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-3" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div className="space-y-4" role="status" aria-label="Loading">
      <Skeleton className="h-8 w-56" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div>
      <Skeleton className="h-72" />
    </div>
  );
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <Inbox className="size-8 text-muted-foreground/60" aria-hidden />
      <p className="font-medium">{title}</p>
      {description ? <p className="max-w-sm text-sm text-muted-foreground">{description}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center" role="alert">
      <AlertTriangle className="size-8 text-destructive" aria-hidden />
      <p className="font-medium">This could not be loaded</p>
      <p className="max-w-sm text-sm text-muted-foreground">{getErrorMessage(error)}</p>
      {error instanceof ApiError && error.correlationId ? <p className="font-mono text-xs text-muted-foreground">Ref: {error.correlationId.slice(0, 8)}</p> : null}
      {onRetry ? <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}><RotateCw />Try again</Button> : null}
    </div>
  );
}

export function Forbidden({ message = "Your role does not include access to this page." }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border bg-card px-6 py-20 text-center">
      <Lock className="size-8 text-muted-foreground/60" aria-hidden />
      <p className="font-medium">You do not have access</p>
      <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
