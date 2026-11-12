"use client";

import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { isStocked, LineItems, NumberCell, ProductPicker, useProducts } from "@/components/shared/line-items";
import { DetailSheet, Fields, PageHeader, RequirePermission, SectionTitle, StatusBadge, Timeline } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useParamDialog } from "@/hooks/use-param-dialog";
import { useBranchParam, useLocations, useWarehouseOptions } from "@/hooks/use-lookups";
import { getErrorMessage } from "@/lib/api/errors";
import { formatDateTime, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { adjustmentsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import { ADJUSTMENT_REASONS, type AdjustmentReason, type StockAdjustment } from "@/types";

interface DraftLine {
  productId: string;
  name: string;
  locationId: string;
  quantity: number;
  reason: AdjustmentReason | "";
  notes: string;
}

export default function AdjustmentsPage() {
  const can = useCan();
  const showCost = can("costs.view");
  const branchId = useBranchParam();
  const { confirm, prompt } = useDialogs();
  const query = useApiQuery(["adjustments", branchId], () => adjustmentsApi.list({ branchId }));
  const warehouses = useWarehouseOptions();
  const locations = useLocations();
  const products = useProducts(isStocked);
  const [open, setOpen] = useParamDialog("new", can("inventory.adjust"));
  const [warehouseId, setWarehouseId] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const detail = query.data?.find((a) => a.id === detailId) ?? null;

  const warehouseLocations = useMemo(() => locations.filter((l) => l.warehouseId === warehouseId && l.type !== "IN_TRANSIT"), [locations, warehouseId]);
  const create = useApiMutation((input: unknown) => adjustmentsApi.create(input), { success: "Adjustment saved as draft", silentError: true });
  const act = useApiMutation(({ id, verb, body }: { id: string; verb: string; body?: unknown }) => adjustmentsApi.action(id, verb, body), { success: (a) => `${a.adjustmentNo}: ${titleCase(a.status)}` });

  const save = async () => {
    setError(null);
    if (!warehouseId) return setError("Select a warehouse.");
    if (!lines.length) return setError("Add at least one line.");
    if (lines.some((l) => !l.reason)) return setError("Reason required");
    if (lines.some((l) => !l.quantity || !l.locationId)) return setError("Each line needs a location and a non-zero quantity.");
    try {
      await create.run({ warehouseId, notes, lines });
      setOpen(false);
      setLines([]);
      setNotes("");
    } catch (e) {
      setError(getErrorMessage(e));
    }
  };

  const post = async (a: StockAdjustment) => {
    const value = showCost ? ` Value impact ${formatUsd(a.totalValue)}.` : "";
    const quantity = a.lines.reduce((s, l) => s + l.quantity, 0);
    if (await confirm({ title: `Post ${a.adjustmentNo}?`, description: `Net quantity change ${formatNumber(quantity)}.${value} Stock changes immediately and can only be undone by a reversal.`, confirmLabel: "Post adjustment" })) void act.fire({ id: a.id, verb: "post" });
  };
  const reject = async (a: StockAdjustment) => {
    const reason = await prompt({ title: `Reject ${a.adjustmentNo}?`, label: "Reason", confirmLabel: "Reject" });
    if (reason) void act.fire({ id: a.id, verb: "reject", body: { reason } });
  };

  const columns: Column<StockAdjustment>[] = [
    { id: "no", header: "Number", value: (a) => a.adjustmentNo, cell: (a) => <span className="font-mono text-xs">{a.adjustmentNo}</span> },
    { id: "wh", header: "Warehouse", value: (a) => a.warehouseName },
    { id: "lines", header: "Lines", value: (a) => a.lines.length, align: "right", hideBelow: "md" },
    ...(showCost ? [{ id: "value", header: "Value", value: (a: StockAdjustment) => a.totalValue ?? 0, cell: (a: StockAdjustment) => formatUsd(a.totalValue), align: "right" as const }] : []),
    { id: "by", header: "Requested by", value: (a) => a.createdBy, hideBelow: "lg" },
    { id: "at", header: "Created", value: (a) => a.createdAt, cell: (a) => formatDateTime(a.createdAt), hideBelow: "md" },
    { id: "status", header: "Status", value: (a) => a.status, cell: (a) => <StatusBadge status={a.status} /> },
  ];

  const footer = detail ? (
    <>
      {detail.status === "DRAFT" && can("inventory.adjust") ? <Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "submit" })}>Submit</Button> : null}
      {detail.status === "SUBMITTED" && can("inventory.adjust.approve") ? <><Button size="sm" variant="outline" onClick={() => void reject(detail)}>Reject</Button><Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "approve" })}>Approve</Button></> : null}
      {detail.status === "APPROVED" && can("inventory.adjust", "inventory.adjust.approve") ? <Button size="sm" onClick={() => void post(detail)}>Post</Button> : null}
    </>
  ) : undefined;

  return (
    <RequirePermission anyOf={["inventory.view"]}>
      <PageHeader title="Stock adjustments" description="Draft, submit, approve, then post. Requesters cannot approve their own adjustments above threshold." />
      <DataTable data={query.data} columns={columns} getRowId={(a) => a.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="adjustments" onRowClick={(a) => setDetailId(a.id)} searchPlaceholder="Number, warehouse or requester" dateFilter={{ label: "Created", value: (a) => a.createdAt }}
        filters={[{ id: "status", label: "Statuses", options: ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "POSTED"].map((value) => ({ value, label: titleCase(value) })), value: (a) => a.status }]}
        toolbar={can("inventory.adjust") ? <Button size="sm" onClick={() => { setError(null); setOpen(true); }}><Plus />New adjustment</Button> : undefined}
        emptyTitle="No adjustments yet"
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader><DialogTitle>New stock adjustment</DialogTitle><DialogDescription>Use a negative quantity to remove stock. Saving a draft does not change stock.</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1"><Label>Warehouse *</Label><Select value={warehouseId} onValueChange={(v) => { setWarehouseId(v); setLines([]); }}><SelectTrigger className="w-full" aria-label="Warehouse"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{warehouses.map((w) => <SelectItem key={w.value} value={w.value}>{w.label}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1"><Label htmlFor="adj-notes">Notes</Label><Input id="adj-notes" value={notes} onChange={(e) => setNotes(e.target.value)} /></div>
          </div>
          <LineItems<DraftLine> lines={lines} onChange={setLines}
            picker={warehouseId ? <ProductPicker products={products} onPick={(p) => setLines((l) => [...l, { productId: p.id, name: p.nameEn, locationId: warehouseLocations.find((x) => x.type === "SELLABLE")?.id ?? "", quantity: 0, reason: "", notes: "" }])} /> : <p className="text-sm text-muted-foreground">Select a warehouse first.</p>}
            columns={[
              { header: "Product", cell: (l) => <span className="block max-w-52 truncate text-sm">{l.name}</span> },
              { header: "Location", cell: (l, u) => <Select value={l.locationId} onValueChange={(v) => u({ locationId: v })}><SelectTrigger size="sm" className="w-32" aria-label="Location"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{warehouseLocations.map((x) => <SelectItem key={x.id} value={x.id}>{x.name}</SelectItem>)}</SelectContent></Select> },
              { header: "Qty +/-", cell: (l, u) => <NumberCell min={-1000000} label="Quantity" value={l.quantity} onChange={(quantity) => u({ quantity })} /> },
              { header: "Reason", cell: (l, u) => <Select value={l.reason} onValueChange={(v) => u({ reason: v as AdjustmentReason })}><SelectTrigger size="sm" className="w-36" aria-label="Reason"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{ADJUSTMENT_REASONS.map((r) => <SelectItem key={r} value={r}>{titleCase(r)}</SelectItem>)}</SelectContent></Select> },
              { header: "Notes", cell: (l, u) => <Input aria-label="Line notes" className="h-8 w-32" value={l.notes} onChange={(e) => u({ notes: e.target.value })} /> },
            ]}
          />
          {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={create.isPending} onClick={() => void save().then(() => { if (!error) toast.dismiss(); })}>Save draft</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetailId(null)} title={detail?.adjustmentNo} description={detail?.warehouseName} footer={footer} wide>
        {detail ? (
          <>
            <Fields columns={3} items={[["Status", <StatusBadge key="s" status={detail.status} />], ["Requested by", detail.createdBy], ["Approved by", detail.approvedBy], ["Created", formatDateTime(detail.createdAt)], ["Posted", formatDateTime(detail.postedAt)], ...(showCost ? [["Value impact", formatUsd(detail.totalValue)] as [string, string]] : [])]} />
            {detail.notes ? <p className="text-sm text-muted-foreground">{detail.notes}</p> : null}
            <SectionTitle>Lines</SectionTitle>
            <div className="overflow-x-auto rounded-md border"><Table><TableHeader><TableRow><TableHead className="h-8">Product</TableHead><TableHead className="h-8">Location</TableHead><TableHead className="h-8">Reason</TableHead><TableHead className="h-8 text-right">Qty</TableHead>{showCost ? <TableHead className="h-8 text-right">Value</TableHead> : null}</TableRow></TableHeader><TableBody>{detail.lines.map((l) => <TableRow key={l.id}><TableCell className="py-1.5">{l.productName}</TableCell><TableCell className="py-1.5">{l.locationName}</TableCell><TableCell className="py-1.5">{titleCase(l.reason)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.quantity)}</TableCell>{showCost ? <TableCell className="tabular py-1.5 text-right">{formatUsd(l.valueImpact)}</TableCell> : null}</TableRow>)}</TableBody></Table></div>
            <SectionTitle>Timeline</SectionTitle>
            <Timeline events={detail.timeline} />
          </>
        ) : null}
      </DetailSheet>
    </RequirePermission>
  );
}
