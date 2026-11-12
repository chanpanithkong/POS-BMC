"use client";

import { Check, Plus, ScanBarcode } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { useProducts } from "@/components/shared/line-items";
import { DetailSheet, Fields, PageHeader, RequirePermission, SectionTitle, StatusBadge, Timeline } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useCategoryOptions, useLocations, useWarehouseOptions } from "@/hooks/use-lookups";
import { formatDateTime, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { countsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { StockCount, StockCountLine } from "@/types";

const schema = z.object({
  warehouseId: z.string().min(1, "Select a warehouse."), scope: z.enum(["FULL", "CYCLE_CATEGORY", "CYCLE_LOCATION", "CYCLE_RANDOM"]), categoryId: z.string(), locationId: z.string(),
  sampleSize: z.number({ error: "Enter a number." }).int().min(1), freeze: z.boolean(), blind: z.boolean(),
}).refine((v) => v.scope !== "CYCLE_CATEGORY" || v.categoryId, { path: ["categoryId"], message: "Select a category." }).refine((v) => v.scope !== "CYCLE_LOCATION" || v.locationId, { path: ["locationId"], message: "Select a location." });
type V = z.infer<typeof schema>;

export default function StocktakesPage() {
  const can = useCan();
  const showCost = can("costs.view");
  const { confirm } = useDialogs();
  const query = useApiQuery(["counts"], countsApi.list);
  const warehouses = useWarehouseOptions();
  const categories = useCategoryOptions();
  const locations = useLocations();
  const products = useProducts();
  const [open, setOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [scan, setScan] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const detail = query.data?.find((c) => c.id === detailId) ?? null;

  const create = useApiMutation((v: V) => countsApi.create(v), { success: "Stock count created", silentError: true, onSuccess: (c) => setDetailId(c.id) });
  const setLines = useApiMutation(({ id, lines }: { id: string; lines: { lineId: string; countedQty?: number | null; reason?: string }[] }) => countsApi.setLines(id, lines));
  const act = useApiMutation(({ id, verb, body }: { id: string; verb: string; body?: unknown }) => countsApi.action(id, verb, body), { success: (c) => `${c.countNo}: ${titleCase(c.status)}`, onSuccess: () => setSelected([]) });

  const editable = detail?.status === "OPEN" || detail?.status === "COUNTING";
  const reviewing = detail?.status === "REVIEW";
  const counted = detail?.lines.filter((l) => l.countedQty !== null).length ?? 0;

  const commit = (line: StockCountLine, value: string) => {
    if (value === "" || !detail) return;
    void setLines.fire({ id: detail.id, lines: [{ lineId: line.id, countedQty: Number(value) }] });
    setDraft((d) => { const next = { ...d }; delete next[line.id]; return next; });
  };

  const onScan = () => {
    if (!detail) return;
    const product = products.find((p) => p.barcodes.some((b) => b.barcode === scan.trim()) || p.sku === scan.trim());
    const line = detail.lines.find((l) => l.productId === product?.id);
    if (!line) {
      toast.error("That item is not part of this count.");
    } else {
      void setLines.fire({ id: detail.id, lines: [{ lineId: line.id, countedQty: (line.countedQty ?? 0) + 1 }] });
    }
    setScan("");
  };

  const columns: Column<StockCount>[] = [
    { id: "no", header: "Number", value: (c) => c.countNo, cell: (c) => <span className="font-mono text-xs">{c.countNo}</span> },
    { id: "wh", header: "Warehouse", value: (c) => c.warehouseName },
    { id: "scope", header: "Scope", value: (c) => c.scopeLabel, hideBelow: "md" },
    { id: "progress", header: "Counted", value: (c) => c.lines.filter((l) => l.countedQty !== null).length, cell: (c) => `${c.lines.filter((l) => l.countedQty !== null).length} / ${c.lines.length}`, align: "right" },
    { id: "by", header: "Created by", value: (c) => c.createdBy, hideBelow: "lg" },
    { id: "at", header: "Created", value: (c) => c.createdAt, cell: (c) => formatDateTime(c.createdAt), hideBelow: "md" },
    { id: "status", header: "Status", value: (c) => c.status, cell: (c) => <StatusBadge status={c.status} /> },
  ];

  const footer = detail ? (
    <>
      {detail.status !== "POSTED" && detail.status !== "CANCELLED" && can("inventory.count") ? <Button size="sm" variant="outline" onClick={async () => { if (await confirm({ title: `Cancel ${detail.countNo}?`, description: "No stock will change.", confirmLabel: "Cancel count", destructive: true })) void act.fire({ id: detail.id, verb: "cancel" }); }}>Cancel count</Button> : null}
      {detail.status === "COUNTING" && can("inventory.count") ? <Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "submit" })}>Submit</Button> : null}
      {reviewing && selected.length && can("inventory.count") ? <Button size="sm" variant="outline" onClick={() => void act.fire({ id: detail.id, verb: "recount", body: { lineIds: selected } })}>Recount {selected.length}</Button> : null}
      {reviewing && can("inventory.count.approve") ? <Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "approve" })}>Approve</Button> : null}
      {detail.status === "APPROVED" && can("inventory.count.approve") ? <Button size="sm" onClick={async () => { const n = detail.lines.filter((l) => l.variance).length; if (await confirm({ title: `Post ${detail.countNo}?`, description: `${n} variance line${n === 1 ? "" : "s"} will post as deltas, so sales after counting are preserved.`, confirmLabel: "Post variances" })) void act.fire({ id: detail.id, verb: "post" }); }}>Post</Button> : null}
    </>
  ) : undefined;

  return (
    <RequirePermission anyOf={["inventory.view"]}>
      <PageHeader title="Stocktaking" description="Variances post as deltas, so counting can continue during trading" />
      <DataTable data={query.data} columns={columns} getRowId={(c) => c.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="stock-counts" onRowClick={(c) => setDetailId(c.id)} searchPlaceholder="Number or warehouse"
        filters={[{ id: "status", label: "Statuses", options: ["OPEN", "COUNTING", "REVIEW", "APPROVED", "POSTED", "CANCELLED"].map((value) => ({ value, label: titleCase(value) })), value: (c) => c.status }]}
        toolbar={can("inventory.count") ? <Button size="sm" onClick={() => setOpen(true)}><Plus />Start count</Button> : undefined} emptyTitle="No stock counts yet" emptyDescription="Start a full stocktake or a cycle count."
      />
      <FormDialog<V> open={open} onOpenChange={setOpen} title="Start stock count" schema={schema} submitLabel="Create count" onSubmit={(v) => create.run(v)}
        defaultValues={{ warehouseId: "", scope: "CYCLE_CATEGORY", categoryId: "", locationId: "", sampleSize: 10, freeze: false, blind: false }}
        fields={[
          { name: "warehouseId", label: "Warehouse", type: "select", required: true, options: warehouses },
          { name: "scope", label: "Scope", type: "select", options: [{ value: "FULL", label: "Full stocktake" }, { value: "CYCLE_CATEGORY", label: "Cycle: category" }, { value: "CYCLE_LOCATION", label: "Cycle: location" }, { value: "CYCLE_RANDOM", label: "Cycle: random sample" }] },
          { name: "categoryId", label: "Category", type: "select", options: categories, visible: (v) => v.scope === "CYCLE_CATEGORY" },
          { name: "locationId", label: "Location", type: "select", options: locations.filter((l) => l.type !== "IN_TRANSIT").map((l) => ({ value: l.id, label: `${l.warehouseId.replace("wh-", "").toUpperCase()} / ${l.name}` })), visible: (v) => v.scope === "CYCLE_LOCATION" },
          { name: "sampleSize", label: "Sample size", type: "number", visible: (v) => v.scope === "CYCLE_RANDOM" },
          { name: "blind", label: "Blind count (hide system quantity)", type: "switch" },
          { name: "freeze", label: "Freeze warehouse (blocks sales and movements)", type: "switch" },
        ]}
      />
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetailId(null)} title={detail?.countNo} description={detail ? `${detail.warehouseName} · ${detail.scopeLabel}` : undefined} footer={footer} wide>
        {detail ? (
          <>
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-muted-foreground"><span>{counted} of {detail.lines.length} lines counted</span><StatusBadge status={detail.status} /></div>
              <Progress value={(counted / Math.max(1, detail.lines.length)) * 100} aria-label="Count progress" />
            </div>
            {detail.freeze ? <p className="rounded-md bg-warning/10 p-2 text-sm text-warning">This warehouse is frozen until the count is posted or cancelled.</p> : null}
            {editable ? (
              <div className="relative">
                <ScanBarcode className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
                <Input value={scan} onChange={(e) => setScan(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onScan(); } }} placeholder="Scan to count: each scan adds 1" aria-label="Scan to count" className="h-12 pl-8" />
              </div>
            ) : null}
            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader><TableRow>{reviewing ? <TableHead className="h-8 w-8" /> : null}<TableHead className="h-8">Location</TableHead><TableHead className="h-8">Product</TableHead><TableHead className="h-8 text-right">{detail.blind && editable ? "System" : "Snapshot"}</TableHead><TableHead className="h-8 text-right">Counted</TableHead><TableHead className="h-8 text-right">Variance</TableHead>{showCost ? <TableHead className="h-8 text-right">Value</TableHead> : null}<TableHead className="h-8">Reason</TableHead></TableRow></TableHeader>
                <TableBody>
                  {detail.lines.slice(0, 200).map((l) => (
                    <TableRow key={l.id} className={l.recountRequired ? "bg-warning/10" : undefined}>
                      {reviewing ? <TableCell className="py-1"><Checkbox aria-label={`Recount ${l.productName}`} checked={selected.includes(l.id)} onCheckedChange={(c) => setSelected((s) => (c ? [...s, l.id] : s.filter((x) => x !== l.id)))} /></TableCell> : null}
                      <TableCell className="py-1 whitespace-nowrap">{l.locationName}</TableCell>
                      <TableCell className="max-w-44 truncate py-1">{l.productName}</TableCell>
                      <TableCell className="tabular py-1 text-right">{l.snapshotQty === null ? "—" : formatNumber(l.snapshotQty)}</TableCell>
                      <TableCell className="py-1 text-right">
                        {editable ? <div className="flex justify-end gap-1"><Input type="number" min={0} step="any" aria-label={`Counted ${l.productName}`} className="tabular h-9 w-20 text-right" value={draft[l.id] ?? (l.countedQty ?? "")} onChange={(e) => setDraft((d) => ({ ...d, [l.id]: e.target.value }))} onBlur={(e) => { if (draft[l.id] !== undefined) commit(l, e.target.value); }} /><span className="grid w-4 place-items-center">{l.countedQty !== null ? <Check className="size-3.5 text-success" aria-label="Counted" /> : null}</span></div> : <span className="tabular">{l.countedQty === null ? "—" : formatNumber(l.countedQty)}</span>}
                      </TableCell>
                      <TableCell className="tabular py-1 text-right">{l.variance === null ? "—" : formatNumber(l.variance)}</TableCell>
                      {showCost ? <TableCell className="tabular py-1 text-right">{l.valueVariance === null || l.valueVariance === undefined ? "—" : formatUsd(l.valueVariance)}</TableCell> : null}
                      <TableCell className="py-1">{reviewing ? <Input aria-label={`Reason ${l.productName}`} className="h-8 w-32" defaultValue={l.reason} onBlur={(e) => { if (e.target.value !== l.reason) void setLines.fire({ id: detail.id, lines: [{ lineId: l.id, reason: e.target.value }] }); }} /> : l.reason}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {detail.lines.length > 200 ? <p className="text-xs text-muted-foreground">Showing the first 200 of {detail.lines.length} lines. Use scanning or the import wizard for the rest.</p> : null}
            <Fields columns={3} items={[["Created by", detail.createdBy], ["Approved by", detail.approvedBy], ["Posted", formatDateTime(detail.postedAt)]]} />
            <SectionTitle>Timeline</SectionTitle>
            <Timeline events={detail.timeline} />
          </>
        ) : null}
      </DetailSheet>
    </RequirePermission>
  );
}
