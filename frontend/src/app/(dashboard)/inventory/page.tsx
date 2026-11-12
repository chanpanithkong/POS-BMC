"use client";

import { ArrowLeftRight, Boxes, CircleAlert, History, MoveRight, PackageX, ScanSearch, ShoppingCart, SlidersHorizontal, TrendingDown, Wallet } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { type Column, DataTable } from "@/components/shared/data-table";
import { FormDialog } from "@/components/shared/form-dialog";
import { DetailSheet, Fields, PageHeader, RequirePermission, SectionTitle, StatCard, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchParam, useCategoryOptions, useLocations, useWarehouseOptions } from "@/hooks/use-lookups";
import { formatNumber, formatUsd, titleCase } from "@/lib/format";
import { inventoryApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import { LOCATION_TYPES, type StockOverviewRow } from "@/types";

const relocateSchema = z.object({ fromLocationId: z.string().min(1, "Select a location."), toLocationId: z.string().min(1, "Select a location."), quantity: z.number({ error: "Enter a quantity." }).positive("Quantity must be greater than zero."), reason: z.string() });
type RelocateForm = z.infer<typeof relocateSchema>;

export default function InventoryPage() {
  const can = useCan();
  const showCost = can("costs.view");
  const branchId = useBranchParam();
  const [warehouseId, setWarehouseId] = useState("all");
  const [locationType, setLocationType] = useState("all");
  const warehouses = useWarehouseOptions();
  const categories = useCategoryOptions();
  const query = useApiQuery(["inventory", branchId, warehouseId, locationType], () => inventoryApi.balances({ branchId, warehouseId: warehouseId === "all" ? undefined : warehouseId, locationType: locationType === "all" ? undefined : locationType }));
  const [detail, setDetail] = useState<StockOverviewRow | null>(null);
  const [relocating, setRelocating] = useState(false);
  const allLocations = useLocations();
  const relocate = useApiMutation((v: RelocateForm) => inventoryApi.relocate({ ...v, productId: detail?.productId ?? "" }), { success: "Stock moved", silentError: true, onSuccess: () => setDetail(null) });
  const reconcile = useApiMutation(() => inventoryApi.reconcile(), {
    onSuccess: (r) => (r.differences.length ? toast.error(`${r.differences.length} balances differ from the movement ledger.`) : toast.success(`Reconciled ${r.balancesChecked} balances: no differences.`)),
  });

  const rows = query.data;
  const stats = useMemo(() => {
    const list = rows ?? [];
    return { items: list.filter((r) => r.onHand !== 0).length, value: list.reduce((s, r) => s + (r.value ?? 0), 0), low: list.filter((r) => r.status === "LOW").length, out: list.filter((r) => r.status === "OUT").length };
  }, [rows]);

  const num = (key: "onHand" | "reserved" | "available" | "onOrder" | "inTransit" | "reorderLevel") => (r: StockOverviewRow) => formatNumber(r[key]);
  const columns = useMemo<Column<StockOverviewRow>[]>(() => [
    { id: "sku", header: "SKU", value: (r) => r.sku, cell: (r) => <span className="font-mono text-xs">{r.sku}</span>, hideBelow: "md" },
    { id: "product", header: "Product", value: (r) => r.productName, className: "max-w-56 truncate" },
    { id: "unit", header: "Unit", value: (r) => r.unitCode, hideBelow: "lg" },
    { id: "onHand", header: "On hand", value: (r) => r.onHand, cell: num("onHand"), align: "right" },
    { id: "reserved", header: "Reserved", value: (r) => r.reserved, cell: num("reserved"), align: "right", hideBelow: "xl" },
    { id: "available", header: "Available", value: (r) => r.available, cell: num("available"), align: "right" },
    { id: "onOrder", header: "On order", value: (r) => r.onOrder, cell: num("onOrder"), align: "right", hideBelow: "lg" },
    { id: "inTransit", header: "In transit", value: (r) => r.inTransit, cell: num("inTransit"), align: "right", hideBelow: "lg" },
    { id: "reorder", header: "Reorder", value: (r) => r.reorderLevel, cell: num("reorderLevel"), align: "right", hideBelow: "xl" },
    ...(showCost ? [{ id: "value", header: "Value", value: (r: StockOverviewRow) => r.value ?? 0, cell: (r: StockOverviewRow) => formatUsd(r.value), align: "right" as const, hideBelow: "md" as const }] : []),
    { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
  ], [showCost]);

  return (
    <RequirePermission anyOf={["inventory.view"]}>
      <PageHeader title="Inventory" description="Available stock counts sellable locations only" actions={
        <>
          <Select value={warehouseId} onValueChange={setWarehouseId}><SelectTrigger size="sm" className="w-48" aria-label="Warehouse"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All warehouses</SelectItem>{warehouses.map((w) => <SelectItem key={w.value} value={w.value}>{w.label}</SelectItem>)}</SelectContent></Select>
          <Select value={locationType} onValueChange={setLocationType}><SelectTrigger size="sm" className="w-40" aria-label="Location type"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All locations</SelectItem>{LOCATION_TYPES.filter((t) => t !== "IN_TRANSIT").map((t) => <SelectItem key={t} value={t}>{titleCase(t)}</SelectItem>)}</SelectContent></Select>
          <Button variant="outline" size="sm" disabled={reconcile.isPending} onClick={() => void reconcile.fire(undefined)}><ScanSearch />Reconcile</Button>
        </>
      } />
      <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Products in stock" value={formatNumber(stats.items)} icon={Boxes} />
        {showCost ? <StatCard label="Inventory value" value={formatUsd(stats.value)} icon={Wallet} /> : null}
        <StatCard label="Low stock" value={formatNumber(stats.low)} icon={TrendingDown} tone={stats.low ? "warning" : "default"} />
        <StatCard label="Out of stock" value={formatNumber(stats.out)} icon={PackageX} tone={stats.out ? "danger" : "default"} />
      </div>
      <DataTable
        data={rows} columns={columns} getRowId={(r) => r.productId} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="inventory" onRowClick={setDetail} searchPlaceholder="Product or SKU" emptyTitle="No stock records"
        filters={[
          { id: "category", label: "Categories", options: categories, value: (r) => r.categoryId },
          { id: "status", label: "Statuses", options: [["IN_STOCK", "In stock"], ["LOW", "Low stock"], ["OUT", "Out of stock"], ["NEGATIVE", "Negative"], ["OVER", "Overstock"]].map(([value, label]) => ({ value, label })), value: (r) => r.status },
        ]}
      />
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetail(null)} title={detail?.productName} description={detail?.sku} footer={detail ? (
        <>
          <Button asChild variant="outline" size="sm"><Link href={`/inventory/movements?q=${detail.sku}`}><History />Movements</Link></Button>
          {can("inventory.transfer") ? <Button variant="outline" size="sm" onClick={() => setRelocating(true)}><MoveRight />Relocate</Button> : null}
          {can("inventory.adjust") ? <Button asChild variant="outline" size="sm"><Link href="/inventory/adjustments?new=1"><SlidersHorizontal />Adjust</Link></Button> : null}
          {can("inventory.transfer") ? <Button asChild variant="outline" size="sm"><Link href="/inventory/transfers?new=1"><ArrowLeftRight />Transfer</Link></Button> : null}
          {can("purchasing.create") ? <Button asChild size="sm"><Link href="/purchases?new=1"><ShoppingCart />Create PO</Link></Button> : null}
        </>
      ) : undefined}>
        {detail ? (
          <>
            <Fields columns={3} items={[["On hand", formatNumber(detail.onHand)], ["Reserved", formatNumber(detail.reserved)], ["Available", formatNumber(detail.available)], ["On order", formatNumber(detail.onOrder)], ["In transit", formatNumber(detail.inTransit)], ...(showCost ? [["Value", formatUsd(detail.value)] as [string, string]] : [])]} />
            <SectionTitle>By location</SectionTitle>
            {detail.byLocation.length ? (
              <div className="overflow-x-auto rounded-md border">
                <Table>
                  <TableHeader><TableRow><TableHead className="h-8">Warehouse</TableHead><TableHead className="h-8">Location</TableHead><TableHead className="h-8">Type</TableHead><TableHead className="h-8 text-right">On hand</TableHead></TableRow></TableHeader>
                  <TableBody>{detail.byLocation.map((l) => <TableRow key={l.locationId}><TableCell className="py-1.5">{l.warehouseName}</TableCell><TableCell className="py-1.5">{l.locationName}</TableCell><TableCell className="py-1.5">{titleCase(l.locationType)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.onHand)}</TableCell></TableRow>)}</TableBody>
                </Table>
              </div>
            ) : <p className="flex items-center gap-1.5 text-sm text-muted-foreground"><CircleAlert className="size-4" />No stock at any location.</p>}
          </>
        ) : null}
      </DetailSheet>
      <FormDialog<RelocateForm>
        open={relocating}
        onOpenChange={setRelocating}
        title={`Relocate ${detail?.productName ?? ""}`}
        description="Moves stock between locations of one warehouse. Use a transfer for another warehouse."
        schema={relocateSchema}
        defaultValues={{ fromLocationId: "", toLocationId: "", quantity: 1, reason: "" }}
        submitLabel="Move stock"
        onSubmit={(v) => relocate.run(v)}
        fields={[
          { name: "fromLocationId", label: "From", type: "select", required: true, full: true, options: (detail?.byLocation ?? []).map((l) => ({ value: l.locationId, label: `${l.warehouseName} / ${l.locationName} (${formatNumber(l.onHand)})` })) },
          { name: "toLocationId", label: "To", type: "select", required: true, full: true, options: allLocations.filter((l) => l.type !== "IN_TRANSIT").map((l) => ({ value: l.id, label: `${l.warehouseId.replace("wh-", "").toUpperCase()} / ${l.name}` })) },
          { name: "quantity", label: "Quantity (base units)", type: "number", required: true },
          { name: "reason", label: "Reason" },
        ]}
      />
    </RequirePermission>
  );
}
