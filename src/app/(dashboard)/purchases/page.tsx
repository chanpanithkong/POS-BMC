"use client";

import { Plus, Printer, Sparkles } from "lucide-react";
import { useMemo, useRef, useState } from "react";
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
import { useBranchParam, useSupplierOptions, useUnits, useWarehouseOptions } from "@/hooks/use-lookups";
import { getErrorMessage } from "@/lib/api/errors";
import { printElement } from "@/lib/export";
import { formatDate, formatDateTime, formatNumber, formatUsd, titleCase, todayIso, addDaysIso } from "@/lib/format";
import { inventoryApi, purchaseOrdersApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { ProductListItem, PurchaseOrder } from "@/types";

interface DraftLine { productId: string; name: string; unitId: string; quantity: number; unitCost: number; units: string[] }

export default function PurchaseOrdersPage() {
  const can = useCan();
  const showCost = can("costs.view");
  const branchId = useBranchParam();
  const { confirm, prompt } = useDialogs();
  const query = useApiQuery(["purchase-orders", branchId], () => purchaseOrdersApi.list({ branchId }));
  const suppliers = useSupplierOptions();
  const warehouses = useWarehouseOptions();
  const products = useProducts(isStocked);
  const units = useUnits();
  const [open, setOpen] = useParamDialog("new", can("purchasing.create"));
  const [header, setHeader] = useState({ supplierId: "", warehouseId: "", expectedDate: addDaysIso(todayIso(), 7), notes: "" });
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const docRef = useRef<HTMLDivElement>(null);
  const detail = query.data?.find((p) => p.id === detailId) ?? null;

  const unitCode = (id: string) => units.find((u) => u.id === id)?.code ?? "";
  const toLine = (p: ProductListItem, supplierId: string, quantity = 1): DraftLine => {
    const link = p.suppliers.find((s) => s.supplierId === supplierId) ?? p.suppliers.find((s) => s.preferred);
    return { productId: p.id, name: p.nameEn, unitId: link?.purchaseUnitId ?? p.baseUnitId, quantity, unitCost: link?.cost ?? p.lastPurchaseCost ?? 0, units: [p.baseUnitId, ...p.conversions.map((c) => c.unitId)] };
  };

  const fillSuggestions = async () => {
    if (!header.supplierId || !header.warehouseId) return setError("Select a supplier and warehouse first.");
    const rows = await inventoryApi.reorderSuggestions({ warehouseId: header.warehouseId });
    const matched = rows.filter((r) => r.supplierId === header.supplierId && r.warehouseId === header.warehouseId);
    if (!matched.length) return toast.info("No reorder suggestions for this supplier and warehouse.");
    setLines(matched.flatMap((r) => { const p = products.find((x) => x.id === r.productId); return p ? [{ ...toLine(p, header.supplierId, r.suggestedQty), unitId: r.purchaseUnitId }] : []; }));
    setError(null);
  };

  const create = useApiMutation((input: unknown) => (editing ? purchaseOrdersApi.update(editing, input as object) : purchaseOrdersApi.create(input)), { success: "Purchase order saved", silentError: true });
  const act = useApiMutation(({ id, verb, body }: { id: string; verb: string; body?: unknown }) => purchaseOrdersApi.action(id, verb, body), { success: (p) => `${p.poNo}: ${titleCase(p.status)}` });
  const remove = useApiMutation((id: string) => purchaseOrdersApi.remove(id), { success: "Draft deleted", onSuccess: () => setDetailId(null) });

  const save = async () => {
    setError(null);
    if (!header.supplierId || !header.warehouseId) return setError("Select a supplier and warehouse.");
    if (!lines.length || lines.some((l) => !(l.quantity > 0))) return setError("Add at least one line with a quantity.");
    try {
      await create.run({ ...header, lines: lines.map(({ productId, unitId, quantity, unitCost }) => ({ productId, unitId, quantity, unitCost })) });
      setOpen(false);
      setLines([]);
      setEditing(null);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  };

  const startEdit = (po: PurchaseOrder) => {
    setEditing(po.id);
    setHeader({ supplierId: po.supplierId, warehouseId: po.warehouseId, expectedDate: po.expectedDate, notes: po.notes });
    setLines(po.lines.map((l) => { const p = products.find((x) => x.id === l.productId); return { productId: l.productId, name: l.productName, unitId: l.unitId, quantity: l.quantity, unitCost: l.unitCost, units: p ? [p.baseUnitId, ...p.conversions.map((c) => c.unitId)] : [l.unitId] }; }));
    setError(null);
    setDetailId(null);
    setOpen(true);
  };

  const total = useMemo(() => lines.reduce((s, l) => s + l.quantity * l.unitCost, 0), [lines]);
  const open_ = ["APPROVED", "SENT", "PARTIALLY_RECEIVED"];

  const columns: Column<PurchaseOrder>[] = [
    { id: "no", header: "PO number", value: (p) => p.poNo, cell: (p) => <span className="font-mono text-xs">{p.poNo}</span> },
    { id: "supplier", header: "Supplier", value: (p) => p.supplierName, className: "max-w-56 truncate" },
    { id: "wh", header: "Warehouse", value: (p) => p.warehouseName, hideBelow: "lg" },
    { id: "expected", header: "Expected", value: (p) => p.expectedDate, cell: (p) => formatDate(p.expectedDate), hideBelow: "md" },
    ...(showCost ? [{ id: "total", header: "Total", value: (p: PurchaseOrder) => p.total, cell: (p: PurchaseOrder) => formatUsd(p.total), align: "right" as const }] : []),
    { id: "status", header: "Status", value: (p) => p.status, cell: (p) => <StatusBadge status={p.status} /> },
  ];

  const askReason = async (po: PurchaseOrder, verb: "reject" | "cancel") => {
    const partly = po.lines.some((l) => l.receivedBase > 0);
    const reason = await prompt({ title: verb === "reject" ? `Reject ${po.poNo}?` : `${partly ? "Cancel remaining quantity on" : "Cancel"} ${po.poNo}?`, description: verb === "cancel" && partly ? "Received stock stays. Only unreceived quantities are cancelled." : undefined, label: "Reason", confirmLabel: verb === "reject" ? "Reject" : "Cancel order" });
    if (reason) void act.fire({ id: po.id, verb, body: { reason } });
  };

  const footer = detail ? (
    <>
      <Button size="sm" variant="outline" onClick={() => printElement(docRef.current, "report")}><Printer />Print / PDF</Button>
      {detail.status === "DRAFT" && can("purchasing.create") ? <Button size="sm" variant="outline" onClick={async () => { if (await confirm({ title: `Delete draft ${detail.poNo}?`, confirmLabel: "Delete", destructive: true })) void remove.fire(detail.id); }}>Delete</Button> : null}
      {["DRAFT", "APPROVED"].includes(detail.status) && can("purchasing.create") ? <Button size="sm" variant="outline" onClick={() => startEdit(detail)}>Edit</Button> : null}
      {[...open_, "PENDING_APPROVAL", "DRAFT"].includes(detail.status) && detail.status !== "DRAFT" && can("purchasing.create", "purchasing.approve") ? <Button size="sm" variant="outline" onClick={() => void askReason(detail, "cancel")}>Cancel remaining</Button> : null}
      {detail.status === "DRAFT" && can("purchasing.create") ? <Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "submit" })}>Submit</Button> : null}
      {detail.status === "PENDING_APPROVAL" && can("purchasing.approve") ? <><Button size="sm" variant="outline" onClick={() => void askReason(detail, "reject")}>Reject</Button><Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "approve" })}>Approve</Button></> : null}
      {detail.status === "APPROVED" && can("purchasing.create", "purchasing.approve") ? <Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "send" })}>Mark sent</Button> : null}
    </>
  ) : undefined;

  return (
    <RequirePermission anyOf={["purchasing.view"]}>
      <PageHeader title="Purchase orders" description="The creator cannot approve. Editing after approval returns the order for approval." />
      <DataTable data={query.data} columns={columns} getRowId={(p) => p.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="purchase-orders" onRowClick={(p) => setDetailId(p.id)} searchPlaceholder="PO number or supplier" dateFilter={{ label: "Created", value: (p) => p.createdAt }}
        filters={[{ id: "status", label: "Statuses", options: ["DRAFT", "PENDING_APPROVAL", "APPROVED", "SENT", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED", "SHORT_CLOSED"].map((value) => ({ value, label: titleCase(value) })), value: (p) => p.status }, { id: "supplier", label: "Suppliers", options: suppliers, value: (p) => p.supplierId }]}
        toolbar={can("purchasing.create") ? <Button size="sm" onClick={() => { setEditing(null); setLines([]); setError(null); setOpen(true); }}><Plus />New order</Button> : undefined} emptyTitle="No purchase orders yet"
      />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader><DialogTitle>{editing ? "Edit purchase order" : "New purchase order"}</DialogTitle><DialogDescription>Ordering does not change on-hand stock. Stock increases when goods are received.</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1 lg:col-span-2"><Label>Supplier *</Label><Select value={header.supplierId} disabled={Boolean(editing)} onValueChange={(v) => setHeader((h) => ({ ...h, supplierId: v }))}><SelectTrigger className="w-full" aria-label="Supplier"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{suppliers.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1"><Label>Warehouse *</Label><Select value={header.warehouseId} disabled={Boolean(editing)} onValueChange={(v) => setHeader((h) => ({ ...h, warehouseId: v }))}><SelectTrigger className="w-full" aria-label="Warehouse"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{warehouses.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1"><Label htmlFor="po-date">Expected date</Label><Input id="po-date" type="date" value={header.expectedDate} onChange={(e) => setHeader((h) => ({ ...h, expectedDate: e.target.value }))} /></div>
          </div>
          <LineItems<DraftLine> lines={lines} onChange={setLines}
            picker={<div className="flex flex-col gap-2 sm:flex-row"><div className="flex-1"><ProductPicker products={products} onPick={(p) => setLines((l) => [...l, toLine(p, header.supplierId)])} /></div><Button type="button" variant="outline" onClick={() => void fillSuggestions()}><Sparkles />Reorder suggestions</Button></div>}
            columns={[
              { header: "Product", cell: (l) => <span className="block max-w-60 truncate text-sm">{l.name}</span> },
              { header: "Unit", cell: (l, u) => <Select value={l.unitId} onValueChange={(v) => u({ unitId: v })}><SelectTrigger size="sm" className="w-20" aria-label="Unit"><SelectValue /></SelectTrigger><SelectContent>{l.units.map((id) => <SelectItem key={id} value={id}>{unitCode(id)}</SelectItem>)}</SelectContent></Select> },
              { header: "Quantity", align: "right", cell: (l, u) => <NumberCell label="Quantity" value={l.quantity} onChange={(quantity) => u({ quantity })} /> },
              { header: "Unit cost", align: "right", cell: (l, u) => <NumberCell label="Unit cost" value={l.unitCost} onChange={(unitCost) => u({ unitCost })} /> },
              { header: "Line total", align: "right", cell: (l) => <span className="tabular">{formatUsd(l.quantity * l.unitCost)}</span> },
            ]}
          />
          <p className="tabular text-right text-sm font-semibold">Total {formatUsd(total)}</p>
          {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={create.isPending} onClick={() => void save()}>Save</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetailId(null)} title={detail?.poNo} description={detail?.supplierName} footer={footer} wide>
        {detail ? (
          <div ref={docRef} className="space-y-4">
            <h2 className="hidden text-base font-semibold print:block">Purchase order {detail.poNo}</h2>
            <Fields columns={3} items={[["Status", <StatusBadge key="s" status={detail.status} />], ["Supplier", detail.supplierName], ["Warehouse", detail.warehouseName], ["Expected", formatDate(detail.expectedDate)], ["Created by", detail.createdBy], ["Approved by", detail.approvedBy], ...(showCost ? [["Total", formatUsd(detail.total)] as [string, string]] : [])]} />
            <SectionTitle>Lines</SectionTitle>
            <div className="overflow-x-auto rounded-md border"><Table><TableHeader><TableRow><TableHead className="h-8">Product</TableHead><TableHead className="h-8">Supplier SKU</TableHead><TableHead className="h-8">Unit</TableHead><TableHead className="h-8 text-right">Qty</TableHead><TableHead className="h-8 text-right">Base qty</TableHead>{showCost ? <><TableHead className="h-8 text-right">Unit cost</TableHead><TableHead className="h-8 text-right">Total</TableHead></> : null}<TableHead className="h-8 text-right">Received</TableHead></TableRow></TableHeader><TableBody>{detail.lines.map((l) => <TableRow key={l.id}><TableCell className="py-1.5">{l.productName}</TableCell><TableCell className="py-1.5 font-mono text-xs">{l.supplierSku}</TableCell><TableCell className="py-1.5">{l.unitCode}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.quantity)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.quantityBase)}</TableCell>{showCost ? <><TableCell className="tabular py-1.5 text-right">{formatUsd(l.unitCost)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatUsd(l.lineTotal)}</TableCell></> : null}<TableCell className="tabular py-1.5 text-right">{formatNumber(l.receivedBase)}</TableCell></TableRow>)}</TableBody></Table></div>
            <SectionTitle>Timeline</SectionTitle>
            <Timeline events={detail.timeline} />
            <p className="text-xs text-muted-foreground">Created {formatDateTime(detail.createdAt)}. Email delivery to suppliers arrives with the backend.</p>
          </div>
        ) : null}
      </DetailSheet>
    </RequirePermission>
  );
}
