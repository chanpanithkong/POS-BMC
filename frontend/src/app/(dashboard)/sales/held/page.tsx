"use client";

import { Ban, Store } from "lucide-react";
import Link from "next/link";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { PageHeader, RequirePermission } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchParam } from "@/hooks/use-lookups";
import { formatDateTime, formatUsd } from "@/lib/format";
import { salesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Sale } from "@/types";

export default function HeldSalesPage() {
  const can = useCan();
  const branchId = useBranchParam();
  const { prompt } = useDialogs();
  const query = useApiQuery(["sales", "held", branchId], () => salesApi.held({ branchId }));
  const cancel = useApiMutation(({ id, reason }: { id: string; reason: string }, token?: string) => salesApi.cancel(id, reason, token), { success: "Held sale cancelled" });
  const columns: Column<Sale>[] = [
    { id: "label", header: "Label", value: (s) => s.holdLabel },
    { id: "branch", header: "Branch", value: (s) => s.branchName, hideBelow: "md" },
    { id: "by", header: "Held by", value: (s) => s.cashierName, hideBelow: "md" },
    { id: "items", header: "Items", value: (s) => s.lines.length, align: "right" },
    { id: "total", header: "Total", value: (s) => s.grandTotal, cell: (s) => formatUsd(s.grandTotal), align: "right" },
    { id: "at", header: "Held at", value: (s) => s.createdAt, cell: (s) => formatDateTime(s.createdAt), hideBelow: "lg" },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (s) => can("pos.sell", "pos.hold") ? <Button variant="ghost" size="sm" onClick={async () => { const reason = await prompt({ title: "Cancel this held sale?", label: "Reason", confirmLabel: "Cancel sale" }); if (reason) void cancel.fire({ id: s.id, reason }); }}><Ban />Cancel</Button> : null },
  ];
  return (
    <RequirePermission anyOf={["sales.view"]}>
      <PageHeader title="Held sales" description="Held sales do not reduce or reserve stock. Resume them from the POS, where they re-price." actions={can("pos.sell", "pos.hold") ? <Button asChild size="sm"><Link href="/pos"><Store />Open POS</Link></Button> : undefined} />
      <DataTable data={query.data} columns={columns} getRowId={(s) => s.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} searchPlaceholder="Label or cashier" emptyTitle="No held sales" exportName="held-sales" />
    </RequirePermission>
  );
}
