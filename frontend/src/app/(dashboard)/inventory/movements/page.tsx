"use client";

import { Undo2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { DetailSheet, Fields, PageHeader, RequirePermission } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchParam, useWarehouseOptions } from "@/hooks/use-lookups";
import { formatDateTime, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { inventoryApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import { MOVEMENT_TYPES, type StockMovement } from "@/types";

export default function MovementsPage() {
  const can = useCan();
  const showCost = can("costs.view");
  const branchId = useBranchParam();
  const params = useSearchParams();
  const { prompt } = useDialogs();
  const warehouses = useWarehouseOptions();
  const query = useApiQuery(["movements", branchId], () => inventoryApi.movements({ branchId }));
  const [detail, setDetail] = useState<StockMovement | null>(null);
  const reverse = useApiMutation(({ id, reason }: { id: number; reason: string }) => inventoryApi.reverse(id, reason), { success: "Reversal posted", onSuccess: () => setDetail(null) });

  const columns: Column<StockMovement>[] = [
    { id: "at", header: "Date", value: (m) => m.postedAt, cell: (m) => <span className="whitespace-nowrap">{formatDateTime(m.postedAt)}</span> },
    { id: "type", header: "Type", value: (m) => titleCase(m.type) },
    { id: "product", header: "Product", value: (m) => m.productName, className: "max-w-48 truncate" },
    { id: "from", header: "From", value: (m) => m.fromLocationName, hideBelow: "lg" },
    { id: "to", header: "To", value: (m) => m.toLocationName, hideBelow: "lg" },
    { id: "entered", header: "Entered", value: (m) => m.quantityEntered, cell: (m) => `${formatNumber(m.quantityEntered)} ${m.unitCode}`, align: "right", hideBelow: "md" },
    { id: "qty", header: "Base qty", value: (m) => m.quantityBase, cell: (m) => formatNumber(m.quantityBase), align: "right" },
    { id: "running", header: "Balance", value: (m) => m.runningBalance, cell: (m) => (m.runningBalance == null ? "—" : formatNumber(m.runningBalance)), align: "right", hideBelow: "md" },
    ...(showCost ? [{ id: "cost", header: "Cost", value: (m: StockMovement) => m.totalCost ?? 0, cell: (m: StockMovement) => formatUsd(m.totalCost), align: "right" as const, hideBelow: "xl" as const }] : []),
    { id: "ref", header: "Reference", value: (m) => m.sourceNo, hideBelow: "md" },
    { id: "user", header: "User", value: (m) => m.userName, hideBelow: "xl" },
  ];

  const askReverse = async () => {
    if (!detail) return;
    const reason = await prompt({ title: "Reverse this movement?", description: "Posted movements are never edited. A compensating movement will be posted.", label: "Reason", confirmLabel: "Post reversal" });
    if (reason) void reverse.fire({ id: detail.id, reason });
  };

  return (
    <RequirePermission anyOf={["inventory.view"]}>
      <PageHeader title="Stock movements" description="Append-only ledger of every stock change" />
      <DataTable
        data={query.data} columns={columns} getRowId={(m) => String(m.id)} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="stock-movements" onRowClick={setDetail} searchPlaceholder="Product, SKU, reference or user" initialSearch={params.get("q") ?? ""}
        searchText={(m) => `${m.sku} ${m.reasonCode ?? ""}`}
        filters={[{ id: "type", label: "Types", options: MOVEMENT_TYPES.map((value) => ({ value, label: titleCase(value) })), value: (m) => m.type }, { id: "warehouse", label: "Warehouses", options: warehouses, value: (m) => m.warehouseId }]}
        dateFilter={{ label: "Date", value: (m) => m.businessDate }}
      />
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetail(null)} title={detail ? `${titleCase(detail.type)} #${detail.id}` : ""} description={detail?.productName} footer={detail && can("inventory.reverse") && !detail.reversedByMovementId && detail.type !== "REVERSAL" ? <Button variant="outline" size="sm" disabled={reverse.isPending} onClick={() => void askReverse()}><Undo2 />Reverse</Button> : undefined}>
        {detail ? <Fields items={[["Posted", formatDateTime(detail.postedAt)], ["Business date", detail.businessDate], ["Product", detail.productName], ["SKU", detail.sku], ["From", detail.fromLocationName], ["To", detail.toLocationName], ["Entered", `${formatNumber(detail.quantityEntered)} ${detail.unitCode}`], ["Base quantity", formatNumber(detail.quantityBase)], ...(showCost ? [["Unit cost", formatUsd(detail.unitCost)], ["Total cost", formatUsd(detail.totalCost)]] as [string, string][] : []), ["Source document", detail.sourceNo], ["Source type", detail.sourceType], ["Reason", detail.reasonCode], ["Approved by", detail.approvedBy], ["User", detail.userName], ["Reversed by", detail.reversedByMovementId ? `#${detail.reversedByMovementId}` : null]]} /> : null}
      </DetailSheet>
    </RequirePermission>
  );
}
