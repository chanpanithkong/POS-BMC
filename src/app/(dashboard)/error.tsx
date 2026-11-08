"use client";

import { ErrorState } from "@/components/shared/states";

export default function DashboardError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="rounded-lg border bg-card">
      <ErrorState error={error} onRetry={retry} />
    </div>
  );
}
