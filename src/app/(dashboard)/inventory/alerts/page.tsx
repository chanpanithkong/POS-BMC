"use client";

import { BellRing, Check, Clock, ShoppingCart, UserPlus } from "lucide-react";
import Link from "next/link";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchParam, useWarehouseOptions } from "@/hooks/use-lookups";
import { formatDateTime, formatNumber, titleCase } from "@/lib/format";
import { alertsApi, inventoryApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { InventoryAlert, ReorderSuggestion } from "@/types";

export default function AlertsPage() {
  const can = useCan();
  const manage = can("alerts.manage");
  const branchId = useBranchParam();
  const { prompt } = useDialogs();
  const alerts = useApiQuery(["alerts"], alertsApi.list);
  const suggestions = useApiQuery(["reorder", branchId], () => inventoryApi.reorderSuggestions({ branchId }));
  const warehouses = useWarehouseOptions();
  const act = useApiMutation(({ id, input }: { id: string; input: Parameters<typeof alertsApi.act>[1] }) => alertsApi.act(id, input), { success: "Alert updated" });
  const evaluate = useApiMutation(() => alertsApi.evaluate(), { success: (r) => `Checks complete: ${r.raised} new expiry or slow-moving alert${r.raised === 1 ? "" : "s"}` });

  const alertColumns: Column<InventoryAlert>[] = [
    { id: "type", header: "Type", value: (a) => titleCase(a.type) },
    { id: "message", header: "Detail", value: (a) => a.message, className: "max-w-96 truncate" },
    { id: "wh", header: "Warehouse", value: (a) => a.warehouseName, hideBelow: "lg" },
    { id: "assigned", header: "Assigned", value: (a) => a.assignedTo, hideBelow: "xl" },
    { id: "at", header: "Raised", value: (a) => a.createdAt, cell: (a) => formatDateTime(a.createdAt), hideBelow: "md" },
    { id: "status", header: "Status", value: (a) => a.status, cell: (a) => <StatusBadge status={a.status} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (a) => manage && a.status !== "RESOLVED" ? (
      <div className="flex justify-end gap-0.5">
        {a.status === "OPEN" ? <Button variant="ghost" size="icon-sm" aria-label="Acknowledge" title="Acknowledge" onClick={() => void act.fire({ id: a.id, input: { action: "ACKNOWLEDGE" } })}><Check /></Button> : null}
        <Button variant="ghost" size="icon-sm" aria-label="Assign" title="Assign" onClick={async () => { const assignedTo = await prompt({ title: "Assign alert", label: "Assign to", confirmLabel: "Assign" }); if (assignedTo) void act.fire({ id: a.id, input: { action: "ASSIGN", assignedTo } }); }}><UserPlus /></Button>
        <Button variant="ghost" size="icon-sm" aria-label="Snooze one day" title="Snooze one day" onClick={() => void act.fire({ id: a.id, input: { action: "SNOOZE", days: 1 } })}><Clock /></Button>
        <Button variant="ghost" size="sm" onClick={async () => { const note = await prompt({ title: "Resolve alert", label: "Note", confirmLabel: "Resolve" }); if (note) void act.fire({ id: a.id, input: { action: "RESOLVE", note } }); }}>Resolve</Button>
      </div>
    ) : null },
  ];

  const suggestionColumns: Column<ReorderSuggestion>[] = [
    { id: "product", header: "Product", value: (r) => r.productName, className: "max-w-56 truncate" },
    { id: "wh", header: "Warehouse", value: (r) => r.warehouseName, hideBelow: "md" },
    { id: "available", header: "Available", value: (r) => r.available, cell: (r) => formatNumber(r.available), align: "right" },
    { id: "onOrder", header: "On order", value: (r) => r.onOrder, cell: (r) => formatNumber(r.onOrder), align: "right", hideBelow: "md" },
    { id: "qty", header: "Suggested", value: (r) => r.suggestedQty, cell: (r) => `${formatNumber(r.suggestedQty)} ${r.purchaseUnitCode}`, align: "right" },
    { id: "supplier", header: "Preferred supplier", value: (r) => r.supplierName, hideBelow: "lg" },
    { id: "lead", header: "Lead days", value: (r) => r.leadTimeDays, align: "right", hideBelow: "xl" },
  ];

  return (
    <RequirePermission anyOf={["alerts.view"]}>
      <PageHeader title="Inventory alerts" description="Raised once per product and warehouse, and resolved automatically when the condition clears" actions={<Button variant="outline" size="sm" disabled={evaluate.isPending} onClick={() => void evaluate.fire(undefined)}><BellRing />Run checks</Button>} />
      <Tabs defaultValue="alerts">
        <TabsList><TabsTrigger value="alerts">Alerts</TabsTrigger><TabsTrigger value="reorder">Reorder suggestions</TabsTrigger></TabsList>
        <TabsContent value="alerts">
          <DataTable data={alerts.data} columns={alertColumns} getRowId={(a) => a.id} isLoading={alerts.isLoading} error={alerts.error} onRetry={() => void alerts.refetch()} exportName="alerts" searchPlaceholder="Product or message" emptyTitle="No alerts"
            filters={[{ id: "status", label: "Statuses", options: ["OPEN", "ACKNOWLEDGED", "SNOOZED", "RESOLVED"].map((value) => ({ value, label: titleCase(value) })), value: (a) => a.status }, { id: "type", label: "Types", options: ["LOW_STOCK", "OUT_OF_STOCK", "OVERSTOCK", "NEGATIVE_STOCK", "EXPIRING", "EXPIRED", "SLOW_MOVING", "UNUSUAL_ADJUSTMENT"].map((value) => ({ value, label: titleCase(value) })), value: (a) => a.type }]} />
        </TabsContent>
        <TabsContent value="reorder">
          <DataTable data={suggestions.data} columns={suggestionColumns} getRowId={(r) => `${r.productId}-${r.warehouseId}`} isLoading={suggestions.isLoading} error={suggestions.error} exportName="reorder-suggestions" emptyTitle="Nothing to reorder" filters={[{ id: "wh", label: "Warehouses", options: warehouses, value: (r) => r.warehouseId }]}
            toolbar={can("purchasing.create") ? <Button asChild size="sm"><Link href="/purchases?new=1&suggest=1"><ShoppingCart />Create PO</Link></Button> : undefined} />
        </TabsContent>
      </Tabs>
    </RequirePermission>
  );
}
