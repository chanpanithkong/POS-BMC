"use client";

import { Plus, Printer } from "lucide-react";
import { useRef, useState } from "react";
import { z } from "zod";
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
import { useWarehouseOptions } from "@/hooks/use-lookups";
import { getErrorMessage } from "@/lib/api/errors";
import { printElement } from "@/lib/export";
import { formatDateTime, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { transfersApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { StockTransfer, TransferLine } from "@/types";

const headerSchema = z.object({ sourceWarehouseId: z.string().min(1, "Select a source."), destinationWarehouseId: z.string().min(1, "Select a destination."), reason: z.string().min(1, "A reason is required.") });

interface ReceiveLine { lineId: string; name: string; outstanding: number; received: number; short: number; damaged: number; excess: number }
interface DispatchLine { lineId: string; name: string; requested: number; quantity: number }

export default function TransfersPage() {
  const can = useCan();
  const { confirm } = useDialogs();
  const query = useApiQuery(["transfers"], transfersApi.list);
  const warehouses = useWarehouseOptions();
  const products = useProducts(isStocked);
  const [open, setOpen] = useParamDialog("new", can("inventory.transfer"));
  const [header, setHeader] = useState({ sourceWarehouseId: "", destinationWarehouseId: "", reason: "" });
  const [lines, setLines] = useState<{ productId: string; name: string; quantity: number }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [dispatching, setDispatching] = useState<DispatchLine[] | null>(null);
  const [receiving, setReceiving] = useState<ReceiveLine[] | null>(null);
  const noteRef = useRef<HTMLDivElement>(null);
  const detail = query.data?.find((t) => t.id === detailId) ?? null;

  const create = useApiMutation((input: unknown) => transfersApi.create(input), { success: "Transfer requested", silentError: true });
  const act = useApiMutation(({ id, verb, body }: { id: string; verb: string; body?: unknown }) => transfersApi.action(id, verb, body), { success: (t) => `${t.transferNo}: ${titleCase(t.status)}` });

  const save = async () => {
    setError(null);
    const parsed = headerSchema.safeParse(header);
    if (!parsed.success) return setError(parsed.error.issues[0].message);
    if (header.sourceWarehouseId === header.destinationWarehouseId) return setError("Source and destination must be different.");
    if (!lines.length || lines.some((l) => !(l.quantity > 0))) return setError("Add at least one line with a quantity.");
    try {
      await create.run({ ...header, lines });
      setOpen(false);
      setLines([]);
      setHeader({ sourceWarehouseId: "", destinationWarehouseId: "", reason: "" });
    } catch (e) {
      setError(getErrorMessage(e));
    }
  };

  const outstanding = (l: TransferLine) => l.quantityDispatched - l.quantityReceived - l.quantityShort - l.quantityDamaged;
  const columns: Column<StockTransfer>[] = [
    { id: "no", header: "Number", value: (t) => t.transferNo, cell: (t) => <span className="font-mono text-xs">{t.transferNo}</span> },
    { id: "source", header: "Source", value: (t) => t.sourceWarehouseName },
    { id: "dest", header: "Destination", value: (t) => t.destinationWarehouseName },
    { id: "lines", header: "Lines", value: (t) => t.lines.length, align: "right", hideBelow: "md" },
    { id: "by", header: "Requested by", value: (t) => t.createdBy, hideBelow: "lg" },
    { id: "at", header: "Created", value: (t) => t.createdAt, cell: (t) => formatDateTime(t.createdAt), hideBelow: "md" },
    { id: "status", header: "Status", value: (t) => t.status, cell: (t) => <StatusBadge status={t.status} /> },
  ];

  const footer = detail ? (
    <>
      <Button size="sm" variant="outline" onClick={() => printElement(noteRef.current, "report")}><Printer />Print transfer note</Button>
      {(detail.status === "REQUESTED" || detail.status === "APPROVED") && can("inventory.transfer") ? <Button size="sm" variant="outline" onClick={async () => { if (await confirm({ title: `Cancel ${detail.transferNo}?`, confirmLabel: "Cancel transfer", destructive: true })) void act.fire({ id: detail.id, verb: "cancel" }); }}>Cancel</Button> : null}
      {detail.status === "REQUESTED" && can("inventory.transfer.approve") ? <Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "approve" })}>Approve</Button> : null}
      {detail.status === "APPROVED" && can("inventory.transfer") ? <Button size="sm" onClick={() => setDispatching(detail.lines.map((l) => ({ lineId: l.id, name: l.productName, requested: l.quantityRequested, quantity: l.quantityRequested })))}>Dispatch</Button> : null}
      {(detail.status === "DISPATCHED" || detail.status === "PARTIALLY_RECEIVED") && can("inventory.transfer") ? <Button size="sm" onClick={() => setReceiving(detail.lines.map((l) => ({ lineId: l.id, name: l.productName, outstanding: outstanding(l), received: outstanding(l), short: 0, damaged: 0, excess: 0 })))}>Receive</Button> : null}
      {detail.status === "RECEIVED" && can("inventory.transfer.approve") ? <Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "close" })}>Close and reconcile</Button> : null}
    </>
  ) : undefined;

  return (
    <RequirePermission anyOf={["inventory.view"]}>
      <PageHeader title="Stock transfers" description="Request, approve, dispatch, receive and reconcile between warehouses" />
      <DataTable data={query.data} columns={columns} getRowId={(t) => t.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="transfers" onRowClick={(t) => setDetailId(t.id)} dateFilter={{ label: "Created", value: (t) => t.createdAt }} searchPlaceholder="Number or warehouse"
        filters={[{ id: "status", label: "Statuses", options: ["REQUESTED", "APPROVED", "DISPATCHED", "PARTIALLY_RECEIVED", "RECEIVED", "CLOSED", "CANCELLED"].map((value) => ({ value, label: titleCase(value) })), value: (t) => t.status }]}
        toolbar={can("inventory.transfer") ? <Button size="sm" onClick={() => { setError(null); setOpen(true); }}><Plus />New transfer</Button> : undefined} emptyTitle="No transfers yet"
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>New transfer request</DialogTitle><DialogDescription>Stock leaves the source at dispatch and reaches the destination at receipt.</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1"><Label>Source *</Label><Select value={header.sourceWarehouseId} onValueChange={(v) => setHeader((h) => ({ ...h, sourceWarehouseId: v }))}><SelectTrigger className="w-full" aria-label="Source"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{warehouses.map((w) => <SelectItem key={w.value} value={w.value}>{w.label}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1"><Label>Destination *</Label><Select value={header.destinationWarehouseId} onValueChange={(v) => setHeader((h) => ({ ...h, destinationWarehouseId: v }))}><SelectTrigger className="w-full" aria-label="Destination"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{warehouses.map((w) => <SelectItem key={w.value} value={w.value}>{w.label}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1 sm:col-span-2"><Label htmlFor="trf-reason">Reason *</Label><Input id="trf-reason" value={header.reason} onChange={(e) => setHeader((h) => ({ ...h, reason: e.target.value }))} /></div>
          </div>
          <LineItems lines={lines} onChange={setLines} picker={<ProductPicker products={products} onPick={(p) => setLines((l) => [...l, { productId: p.id, name: p.nameEn, quantity: 1 }])} />} columns={[{ header: "Product", cell: (l) => <span className="block max-w-72 truncate text-sm">{l.name}</span> }, { header: "Quantity", align: "right", cell: (l, u) => <NumberCell label="Quantity" value={l.quantity} onChange={(quantity) => u({ quantity })} /> }]} />
          {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={create.isPending} onClick={() => void save()}>Submit request</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={dispatching !== null} onOpenChange={(o) => !o && setDispatching(null)}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader><DialogTitle>Dispatch {detail?.transferNo}</DialogTitle><DialogDescription>Moves stock from {detail?.sourceWarehouseName} to in transit. Destination stock does not change yet.</DialogDescription></DialogHeader>
          <LineItems lines={dispatching ?? []} onChange={setDispatching} removable={false} columns={[{ header: "Product", cell: (l) => <span className="block max-w-64 truncate text-sm">{l.name}</span> }, { header: "Requested", align: "right", cell: (l) => formatNumber(l.requested) }, { header: "Dispatch", align: "right", cell: (l, u) => <NumberCell label="Dispatch quantity" value={l.quantity} onChange={(quantity) => u({ quantity })} /> }]} />
          <DialogFooter><Button disabled={act.isPending} onClick={() => detail && void act.run({ id: detail.id, verb: "dispatch", body: { lines: dispatching?.map((l) => ({ lineId: l.lineId, quantity: l.quantity })) } }).then(() => setDispatching(null)).catch(() => undefined)}>Post dispatch</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog open={receiving !== null} onOpenChange={(o) => !o && setReceiving(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader><DialogTitle>Receive {detail?.transferNo}</DialogTitle><DialogDescription>Leave remaining quantity for a later partial receipt. Short and excess post at close.</DialogDescription></DialogHeader>
          <LineItems lines={receiving ?? []} onChange={setReceiving} removable={false} columns={[{ header: "Product", cell: (l) => <span className="block max-w-48 truncate text-sm">{l.name}</span> }, { header: "Outstanding", align: "right", cell: (l) => formatNumber(l.outstanding) }, ...(["received", "short", "damaged", "excess"] as const).map((key) => ({ header: titleCase(key), align: "right" as const, cell: (l: ReceiveLine, u: (p: Partial<ReceiveLine>) => void) => <NumberCell label={key} value={l[key]} onChange={(value) => u({ [key]: value })} /> }))]} />
          <DialogFooter><Button disabled={act.isPending} onClick={() => detail && void act.run({ id: detail.id, verb: "receive", body: { lines: receiving } }).then(() => setReceiving(null)).catch(() => undefined)}>Post receipt</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetailId(null)} title={detail?.transferNo} description={detail ? `${detail.sourceWarehouseName} to ${detail.destinationWarehouseName}` : undefined} footer={footer} wide>
        {detail ? (
          <div ref={noteRef} className="space-y-4">
            <h2 className="hidden text-base font-semibold print:block">Transfer note {detail.transferNo}</h2>
            <Fields columns={3} items={[["Status", <StatusBadge key="s" status={detail.status} />], ["Requested by", detail.createdBy], ["Approved by", detail.approvedBy], ["Source", detail.sourceWarehouseName], ["Destination", detail.destinationWarehouseName], ["Reason", detail.reason], ...(can("costs.view") ? [["In-transit value", formatUsd(detail.value)] as [string, string]] : [])]} />
            <SectionTitle>Lines</SectionTitle>
            <div className="overflow-x-auto rounded-md border"><Table><TableHeader><TableRow><TableHead className="h-8">Product</TableHead>{["Requested", "Dispatched", "Received", "Short", "Damaged", "Excess"].map((h) => <TableHead key={h} className="h-8 text-right">{h}</TableHead>)}</TableRow></TableHeader><TableBody>{detail.lines.map((l) => <TableRow key={l.id}><TableCell className="py-1.5">{l.productName}</TableCell>{[l.quantityRequested, l.quantityDispatched, l.quantityReceived, l.quantityShort, l.quantityDamaged, l.quantityExcess].map((v, i) => <TableCell key={i} className="tabular py-1.5 text-right">{formatNumber(v)}</TableCell>)}</TableRow>)}</TableBody></Table></div>
            <SectionTitle>Timeline</SectionTitle>
            <Timeline events={detail.timeline} />
          </div>
        ) : null}
      </DetailSheet>
    </RequirePermission>
  );
}
