"use client";

import { type Column, DataTable } from "@/components/shared/data-table";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { useApiQuery } from "@/hooks/use-api";
import { formatDate, formatNumber, formatUsd } from "@/lib/format";
import { inventoryApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { ExpiringBatchRow } from "@/types";

const stateOf = (d: number) => (d < 0 ? "EXPIRED" : d <= 30 ? "EXPIRING" : "OK");

export default function ExpiringPage() {
  const can = useCan();
  const query = useApiQuery(["batches"], inventoryApi.batches);
  const columns: Column<ExpiringBatchRow>[] = [
    { id: "product", header: "Product", value: (b) => b.productName, className: "max-w-56 truncate" },
    { id: "batch", header: "Batch", value: (b) => b.batchNo, cell: (b) => <span className="font-mono text-xs">{b.batchNo}</span> },
    { id: "wh", header: "Warehouse", value: (b) => b.warehouseName, hideBelow: "md" },
    { id: "loc", header: "Location", value: (b) => b.locationName, hideBelow: "lg" },
    { id: "expiry", header: "Expiry", value: (b) => b.expiryDate, cell: (b) => formatDate(b.expiryDate) },
    { id: "days", header: "Days left", value: (b) => b.daysToExpiry, align: "right" },
    { id: "qty", header: "Qty", value: (b) => b.quantity, cell: (b) => formatNumber(b.quantity), align: "right" },
    ...(can("costs.view") ? [{ id: "value", header: "Value", value: (b: ExpiringBatchRow) => b.value ?? 0, cell: (b: ExpiringBatchRow) => formatUsd(b.value), align: "right" as const, hideBelow: "md" as const }] : []),
    { id: "state", header: "Status", value: (b) => stateOf(b.daysToExpiry), cell: (b) => <StatusBadge status={b.daysToExpiry < 0 ? "EXPIRED" : b.daysToExpiry <= 30 ? "LOW" : "IN_STOCK"} /> },
  ];
  return (
    <RequirePermission anyOf={["inventory.view"]}>
      <PageHeader title="Batches and expiry" description="Sales use the earliest-expiring batch first. Expired batches cannot be sold." />
      <DataTable data={query.data} columns={columns} getRowId={(b) => b.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="batches" searchPlaceholder="Product or batch" emptyTitle="No tracked batches"
        filters={[{ id: "state", label: "States", options: [{ value: "EXPIRED", label: "Expired" }, { value: "EXPIRING", label: "Expiring in 30 days" }, { value: "OK", label: "Later" }], value: (b) => stateOf(b.daysToExpiry) }]} />
    </RequirePermission>
  );
}
