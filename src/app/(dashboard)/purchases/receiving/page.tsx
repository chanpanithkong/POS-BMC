"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { isStocked, LineItems, NumberCell, ProductPicker, useProducts } from "@/components/shared/line-items";
import { DetailSheet, Fields, PageHeader, RequirePermission, SectionTitle, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchParam, useSupplierOptions, useWarehouseOptions } from "@/hooks/use-lookups";
import { getErrorMessage } from "@/lib/api/errors";
import { formatDateTime, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { goodsReceiptsApi, purchaseOrdersApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { GoodsReceipt } from "@/types";

interface DraftLine { poLineId: string | null; productId: string; name: string; unitId: string; unitCode: string; factor: number; open: number; quantityReceived: number; quantityDamaged: number; quantityRejected: number; unitCost: number; batchNo: string; expiryDate: string; trackExpiry: boolean }

const EMPTY_HEADER = { poId: "", supplierId: "", warehouseId: "", deliveryNote: "", invoiceRef: "", exceptionReason: "", blind: false };

export default function ReceivingPage() {
  const can = useCan();
  const showCost = can("costs.view");
  const branchId = useBranchParam();
  const { confirm } = useDialogs();
  const query = useApiQuery(["goods-receipts", branchId], () => goodsReceiptsApi.list({ branchId }));
  const orders = useApiQuery(["purchase-orders", "open", branchId], () => purchaseOrdersApi.list({ branchId }), { enabled: can("purchasing.view") });
  const suppliers = useSupplierOptions();
  const warehouses = useWarehouseOptions();
  const products = useProducts(isStocked);
  const [open, setOpen] = useState(false);
  const [exception, setException] = useState(false);
  const [header, setHeader] = useState(EMPTY_HEADER);
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const detail = query.data?.find((g) => g.id === detailId) ?? null;
  const openOrders = (orders.data ?? []).filter((p) => ["APPROVED", "SENT", "PARTIALLY_RECEIVED"].includes(p.status));

  const create = useApiMutation((input: unknown) => goodsReceiptsApi.create(input), { success: "Receipt saved as draft", silentError: true, onSuccess: (g) => setDetailId(g.id) });
  const act = useApiMutation(({ id, verb }: { id: string; verb: string }) => goodsReceiptsApi.action(id, verb), { success: (g) => (g.status === "POSTED" ? `${g.receiptNo} posted: stock increased` : `${g.receiptNo} sent for approval`) });
  const remove = useApiMutation((id: string) => goodsReceiptsApi.remove(id), { success: "Draft deleted", onSuccess: () => setDetailId(null) });

  const pickOrder = (poId: string) => {
    const po = openOrders.find((p) => p.id === poId);
    setHeader((h) => ({ ...h, poId, supplierId: po?.supplierId ?? "", warehouseId: po?.warehouseId ?? "" }));
    setLines((po?.lines ?? []).filter((l) => l.quantityBase - l.receivedBase - l.cancelledBase > 0).map((l) => {
      const remaining = (l.quantityBase - l.receivedBase - l.cancelledBase) / l.factor;
      const product = products.find((p) => p.id === l.productId);
      return { poLineId: l.id, productId: l.productId, name: l.productName, unitId: l.unitId, unitCode: l.unitCode, factor: l.factor, open: remaining, quantityReceived: remaining, quantityDamaged: 0, quantityRejected: 0, unitCost: l.unitCost, batchNo: "", expiryDate: "", trackExpiry: Boolean(product?.trackExpiry) };
    }));
  };

  const scan = (productId: string, unitId?: string) => {
    const existing = lines.find((l) => l.productId === productId && (!unitId || l.unitId === unitId));
    if (existing) {
      setLines((all) => all.map((l) => (l === existing ? { ...l, quantityReceived: l.quantityReceived + 1 } : l)));
      return;
    }
    if (!exception) {
      toast.error("This item is not on the selected purchase order.");
      return;
    }
    const p = products.find((x) => x.id === productId);
    if (p) setLines((all) => [...all, { poLineId: null, productId: p.id, name: p.nameEn, unitId: unitId ?? p.baseUnitId, unitCode: p.unitCode, factor: 1, open: 0, quantityReceived: 1, quantityDamaged: 0, quantityRejected: 0, unitCost: p.lastPurchaseCost ?? 0, batchNo: "", expiryDate: "", trackExpiry: p.trackExpiry }]);
  };

  const save = async () => {
    setError(null);
    if (!exception && !header.poId) return setError("Select a purchase order.");
    if (exception && (!header.supplierId || !header.warehouseId || !header.exceptionReason.trim())) return setError("Supplier, warehouse and reason are required to receive without a purchase order.");
    if (!header.deliveryNote.trim()) return setError("Delivery note number is required.");
    if (!lines.length) return setError("Add at least one line.");
    try {
      await create.run({ ...header, poId: exception ? null : header.poId, lines });
      setOpen(false);
      setLines([]);
      setHeader(EMPTY_HEADER);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  };

  const columns: Column<GoodsReceipt>[] = [
    { id: "no", header: "Receipt", value: (g) => g.receiptNo, cell: (g) => <span className="font-mono text-xs">{g.receiptNo}</span> },
    { id: "po", header: "PO", value: (g) => g.poNo ?? "Without PO", cell: (g) => (g.poNo ? <span className="font-mono text-xs">{g.poNo}</span> : <span className="text-warning">Without PO</span>), hideBelow: "md" },
    { id: "supplier", header: "Supplier", value: (g) => g.supplierName, className: "max-w-52 truncate" },
    { id: "wh", header: "Warehouse", value: (g) => g.warehouseName, hideBelow: "lg" },
    ...(showCost ? [{ id: "cost", header: "Cost", value: (g: GoodsReceipt) => g.totalCost ?? 0, cell: (g: GoodsReceipt) => formatUsd(g.totalCost), align: "right" as const, hideBelow: "sm" as const }] : []),
    { id: "posted", header: "Posted", value: (g) => g.postedAt, cell: (g) => formatDateTime(g.postedAt), hideBelow: "md" },
    { id: "status", header: "Status", value: (g) => g.status, cell: (g) => <StatusBadge status={g.status} /> },
  ];

  const post = async (g: GoodsReceipt) => {
    const units = g.lines.reduce((s, l) => s + (l.quantityReceived + l.quantityDamaged) * l.factor, 0);
    if (await confirm({ title: `Post ${g.receiptNo}?`, description: `Stock increases by ${formatNumber(units)} base units, once. Posted receipts cannot be edited.`, confirmLabel: "Post receipt" })) void act.fire({ id: g.id, verb: "post" });
  };

  const footer = detail ? (
    <>
      {detail.status === "DRAFT" && can("receiving.create") ? <Button size="sm" variant="outline" onClick={async () => { if (await confirm({ title: "Delete this draft?", confirmLabel: "Delete", destructive: true })) void remove.fire(detail.id); }}>Delete</Button> : null}
      {detail.status === "DRAFT" && can("receiving.post") ? <Button size="sm" onClick={() => void post(detail)}>Post receipt</Button> : null}
      {detail.status === "PENDING_APPROVAL" && can("inventory.adjust.approve") ? <><Button size="sm" variant="outline" onClick={() => void act.fire({ id: detail.id, verb: "reject" })}>Return to draft</Button><Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "approve" })}>Approve and post</Button></> : null}
    </>
  ) : undefined;

  return (
    <RequirePermission anyOf={["receiving.create", "purchasing.view"]}>
      <PageHeader title="Goods receiving" description="Stock increases only when a receipt is posted, exactly once" />
      <DataTable data={query.data} columns={columns} getRowId={(g) => g.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="goods-receipts" onRowClick={(g) => setDetailId(g.id)} searchPlaceholder="Receipt, PO or supplier"
        filters={[{ id: "status", label: "Statuses", options: ["DRAFT", "PENDING_APPROVAL", "POSTED"].map((value) => ({ value, label: titleCase(value) })), value: (g) => g.status }]} dateFilter={{ label: "Created", value: (g) => g.createdAt }}
        toolbar={can("receiving.create") ? <Button size="sm" onClick={() => { setError(null); setHeader(EMPTY_HEADER); setLines([]); setException(false); setOpen(true); }}><Plus />Receive goods</Button> : undefined} emptyTitle="No goods receipts yet"
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-5xl">
          <DialogHeader><DialogTitle>Receive goods</DialogTitle><DialogDescription>Scan or enter quantities. Saving a draft does not change stock.</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {can("receiving.exception") ? <div className="flex items-center justify-between gap-2 rounded-md border p-2 sm:col-span-2 lg:col-span-4"><Label htmlFor="no-po">Receive without a purchase order (flagged for review)</Label><Switch id="no-po" checked={exception} onCheckedChange={(c) => { setException(c); setLines([]); setHeader(EMPTY_HEADER); }} /></div> : null}
            {exception ? (
              <>
                <div className="space-y-1"><Label>Supplier *</Label><Select value={header.supplierId} onValueChange={(v) => setHeader((h) => ({ ...h, supplierId: v }))}><SelectTrigger className="w-full" aria-label="Supplier"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{suppliers.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}</SelectContent></Select></div>
                <div className="space-y-1"><Label>Warehouse *</Label><Select value={header.warehouseId} onValueChange={(v) => setHeader((h) => ({ ...h, warehouseId: v }))}><SelectTrigger className="w-full" aria-label="Warehouse"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{warehouses.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}</SelectContent></Select></div>
                <div className="space-y-1 sm:col-span-2"><Label htmlFor="grn-reason">Reason *</Label><Input id="grn-reason" value={header.exceptionReason} onChange={(e) => setHeader((h) => ({ ...h, exceptionReason: e.target.value }))} /></div>
              </>
            ) : (
              <div className="space-y-1 sm:col-span-2"><Label>Purchase order *</Label><Select value={header.poId} onValueChange={pickOrder}><SelectTrigger className="w-full" aria-label="Purchase order"><SelectValue placeholder="Select an open order" /></SelectTrigger><SelectContent>{openOrders.map((p) => <SelectItem key={p.id} value={p.id}>{p.poNo} · {p.supplierName}</SelectItem>)}</SelectContent></Select></div>
            )}
            <div className="space-y-1"><Label htmlFor="grn-dn">Delivery note *</Label><Input id="grn-dn" value={header.deliveryNote} onChange={(e) => setHeader((h) => ({ ...h, deliveryNote: e.target.value }))} /></div>
            <div className="space-y-1"><Label htmlFor="grn-inv">Supplier invoice no.</Label><Input id="grn-inv" value={header.invoiceRef} onChange={(e) => setHeader((h) => ({ ...h, invoiceRef: e.target.value }))} /></div>
            <div className="flex items-center gap-2"><Switch id="grn-blind" checked={header.blind} onCheckedChange={(c) => setHeader((h) => ({ ...h, blind: c }))} /><Label htmlFor="grn-blind">Blind receiving</Label></div>
          </div>
          <LineItems<DraftLine> lines={lines} onChange={setLines} picker={<ProductPicker products={products} onPick={(p, unitId) => scan(p.id, unitId)} placeholder="Scan to count received items" />} emptyText={exception ? "Scan or search a product." : "Select a purchase order to load its lines."} columns={[
            { header: "Product", cell: (l) => <span className="block max-w-44 truncate text-sm">{l.name}</span> },
            ...(header.blind ? [] : [{ header: "Open", align: "right" as const, cell: (l: DraftLine) => `${formatNumber(l.open)} ${l.unitCode}` }]),
            { header: "Received", align: "right", cell: (l, u) => <NumberCell label="Received" value={l.quantityReceived} onChange={(quantityReceived) => u({ quantityReceived })} /> },
            { header: "Damaged", align: "right", cell: (l, u) => <NumberCell label="Damaged" value={l.quantityDamaged} onChange={(quantityDamaged) => u({ quantityDamaged })} /> },
            { header: "Rejected", align: "right", cell: (l, u) => <NumberCell label="Rejected" value={l.quantityRejected} onChange={(quantityRejected) => u({ quantityRejected })} /> },
            { header: "Unit cost", align: "right", cell: (l, u) => <NumberCell label="Unit cost" value={l.unitCost} onChange={(unitCost) => u({ unitCost })} /> },
            { header: "Batch", cell: (l, u) => (l.trackExpiry ? <Input aria-label="Batch" className="h-8 w-24" value={l.batchNo} onChange={(e) => u({ batchNo: e.target.value })} /> : <span className="text-muted-foreground">—</span>) },
            { header: "Expiry", cell: (l, u) => (l.trackExpiry ? <Input type="date" aria-label="Expiry" className="h-8 w-36" value={l.expiryDate} onChange={(e) => u({ expiryDate: e.target.value })} /> : <span className="text-muted-foreground">—</span>) },
          ]} />
          {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={create.isPending} onClick={() => void save()}>Save draft</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetailId(null)} title={detail?.receiptNo} description={detail?.supplierName} footer={footer} wide>
        {detail ? (
          <>
            <Fields columns={3} items={[["Status", <StatusBadge key="s" status={detail.status} />], ["PO", detail.poNo ?? "Without PO"], ["Warehouse", detail.warehouseName], ["Delivery note", detail.deliveryNote], ["Invoice ref", detail.invoiceRef], ["Created by", detail.createdBy], ["Approved by", detail.approvedBy], ["Posted by", detail.postedBy], ["Posted", formatDateTime(detail.postedAt)]]} />
            {detail.exceptionReason ? <p className="rounded-md bg-warning/10 p-2 text-sm text-warning">Received without PO: {detail.exceptionReason}</p> : null}
            {detail.discrepancies.length ? <div className="rounded-md border border-warning/40 p-2.5 text-sm"><p className="font-medium">Discrepancies</p><ul className="mt-1 list-disc pl-4 text-muted-foreground">{detail.discrepancies.map((d) => <li key={d}>{d}</li>)}</ul></div> : null}
            <SectionTitle>Lines</SectionTitle>
            <div className="overflow-x-auto rounded-md border"><Table><TableHeader><TableRow><TableHead className="h-8">Product</TableHead><TableHead className="h-8 text-right">Open</TableHead><TableHead className="h-8 text-right">Received</TableHead><TableHead className="h-8 text-right">Base qty</TableHead><TableHead className="h-8 text-right">Damaged</TableHead><TableHead className="h-8 text-right">Rejected</TableHead><TableHead className="h-8">Batch</TableHead></TableRow></TableHeader><TableBody>{detail.lines.map((l) => <TableRow key={l.id}><TableCell className="py-1.5">{l.productName}</TableCell><TableCell className="tabular py-1.5 text-right">{detail.blind && detail.status !== "POSTED" ? "—" : formatNumber(l.orderedOpen)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.quantityReceived)} {l.unitCode}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.quantityReceived * l.factor)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.quantityDamaged)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.quantityRejected)}</TableCell><TableCell className="py-1.5">{l.batchNo}</TableCell></TableRow>)}</TableBody></Table></div>
          </>
        ) : null}
      </DetailSheet>
    </RequirePermission>
  );
}
