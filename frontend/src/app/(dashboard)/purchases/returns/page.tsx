"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { LineItems, NumberCell } from "@/components/shared/line-items";
import { DetailSheet, Fields, PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useLocations } from "@/hooks/use-lookups";
import { getErrorMessage } from "@/lib/api/errors";
import { formatDateTime, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { goodsReceiptsApi, purchaseReturnsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { PurchaseReturn } from "@/types";

interface Line { productId: string; name: string; locationId: string; quantityBase: number }

export default function PurchaseReturnsPage() {
  const can = useCan();
  const { prompt, confirm } = useDialogs();
  const query = useApiQuery(["purchase-returns"], purchaseReturnsApi.list);
  const receipts = useApiQuery(["goods-receipts"], () => goodsReceiptsApi.list());
  const locations = useLocations();
  const [open, setOpen] = useState(false);
  const [receiptId, setReceiptId] = useState("");
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const detail = query.data?.find((r) => r.id === detailId) ?? null;
  const posted = (receipts.data ?? []).filter((g) => g.status === "POSTED");
  const receipt = posted.find((g) => g.id === receiptId);
  const receiptLocations = locations.filter((l) => l.warehouseId === receipt?.warehouseId && l.type !== "IN_TRANSIT");

  const create = useApiMutation((input: unknown) => purchaseReturnsApi.create(input), { success: "Purchase return created", silentError: true });
  const act = useApiMutation(({ id, verb, body }: { id: string; verb: string; body?: unknown }) => purchaseReturnsApi.action(id, verb, body), { success: (r) => `${r.returnNo}: ${titleCase(r.status)}` });

  const choose = (id: string) => {
    setReceiptId(id);
    const g = posted.find((x) => x.id === id);
    const damaged = locations.find((l) => l.warehouseId === g?.warehouseId && l.type === "DAMAGED");
    setLines((g?.lines ?? []).map((l) => ({ productId: l.productId, name: l.productName, locationId: damaged?.id ?? "", quantityBase: 0 })));
  };

  const save = async () => {
    setError(null);
    const chosen = lines.filter((l) => l.quantityBase > 0);
    if (!receiptId) return setError("Select a goods receipt.");
    if (!reason.trim()) return setError("A reason is required.");
    if (!chosen.length) return setError("Enter a quantity on at least one line.");
    try {
      await create.run({ goodsReceiptId: receiptId, reason, lines: chosen });
      setOpen(false);
      setReceiptId("");
      setReason("");
      setLines([]);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  };

  const columns: Column<PurchaseReturn>[] = [
    { id: "no", header: "Return", value: (r) => r.returnNo, cell: (r) => <span className="font-mono text-xs">{r.returnNo}</span> },
    { id: "supplier", header: "Supplier", value: (r) => r.supplierName, className: "max-w-52 truncate" },
    { id: "grn", header: "Receipt", value: (r) => r.goodsReceiptNo, hideBelow: "md" },
    { id: "reason", header: "Reason", value: (r) => r.reason, hideBelow: "lg" },
    { id: "total", header: "Total", value: (r) => r.total, cell: (r) => formatUsd(r.total), align: "right" },
    { id: "credit", header: "Credit note", value: (r) => r.creditNoteRef, hideBelow: "lg" },
    { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
  ];

  const footer = detail ? (
    <>
      {detail.status === "DRAFT" && can("purchasing.approve") ? <Button size="sm" onClick={() => void act.fire({ id: detail.id, verb: "approve" })}>Approve</Button> : null}
      {detail.status === "APPROVED" && can("purchasing.create", "receiving.post") ? <Button size="sm" onClick={async () => { if (await confirm({ title: `Dispatch ${detail.returnNo}?`, description: "Stock leaves the selected locations now.", confirmLabel: "Dispatch" })) void act.fire({ id: detail.id, verb: "dispatch" }); }}>Dispatch</Button> : null}
      {detail.status === "DISPATCHED" && can("purchasing.create", "expenses.approve") ? <Button size="sm" onClick={async () => { const creditNoteRef = await prompt({ title: "Record supplier credit note", label: "Credit note reference", confirmLabel: "Record" }); if (creditNoteRef) void act.fire({ id: detail.id, verb: "credit", body: { creditNoteRef } }); }}>Record credit note</Button> : null}
    </>
  ) : undefined;

  return (
    <RequirePermission anyOf={["purchasing.view"]}>
      <PageHeader title="Purchase returns" description="Return goods to suppliers against a posted receipt" />
      <DataTable data={query.data} columns={columns} getRowId={(r) => r.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="purchase-returns" onRowClick={(r) => setDetailId(r.id)} searchPlaceholder="Return or supplier"
        toolbar={can("purchasing.create") ? <Button size="sm" onClick={() => { setError(null); setOpen(true); }}><Plus />New return</Button> : undefined} emptyTitle="No purchase returns yet" />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>New purchase return</DialogTitle><DialogDescription>Stock leaves only when the approved return is dispatched.</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1"><Label>Goods receipt *</Label><Select value={receiptId} onValueChange={choose}><SelectTrigger className="w-full" aria-label="Goods receipt"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{posted.map((g) => <SelectItem key={g.id} value={g.id}>{g.receiptNo} · {g.supplierName}</SelectItem>)}</SelectContent></Select></div>
            <div className="space-y-1"><Label htmlFor="pr-reason">Reason *</Label><Input id="pr-reason" value={reason} onChange={(e) => setReason(e.target.value)} /></div>
          </div>
          <LineItems<Line> lines={lines} onChange={setLines} removable={false} emptyText="Select a goods receipt." columns={[{ header: "Product", cell: (l) => <span className="block max-w-56 truncate text-sm">{l.name}</span> }, { header: "From location", cell: (l, u) => <Select value={l.locationId} onValueChange={(v) => u({ locationId: v })}><SelectTrigger size="sm" className="w-36" aria-label="Location"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{receiptLocations.map((x) => <SelectItem key={x.id} value={x.id}>{x.name}</SelectItem>)}</SelectContent></Select> }, { header: "Base qty", align: "right", cell: (l, u) => <NumberCell label="Quantity" value={l.quantityBase} onChange={(quantityBase) => u({ quantityBase })} /> }]} />
          {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <DialogFooter><Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button><Button disabled={create.isPending} onClick={() => void save()}>Create return</Button></DialogFooter>
        </DialogContent>
      </Dialog>
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetailId(null)} title={detail?.returnNo} description={detail?.supplierName} footer={footer}>
        {detail ? (
          <>
            <Fields items={[["Status", <StatusBadge key="s" status={detail.status} />], ["Receipt", detail.goodsReceiptNo], ["Reason", detail.reason], ["Credit note", detail.creditNoteRef], ["Created by", detail.createdBy], ["Approved by", detail.approvedBy], ["Created", formatDateTime(detail.createdAt)], ["Total", formatUsd(detail.total)]]} />
            <ul className="divide-y rounded-md border text-sm">{detail.lines.map((l) => <li key={l.id} className="flex justify-between gap-2 p-2"><span className="min-w-0 truncate">{l.productName}</span><span className="tabular shrink-0">{formatNumber(l.quantityBase)} · {formatUsd(l.total)}</span></li>)}</ul>
          </>
        ) : null}
      </DetailSheet>
    </RequirePermission>
  );
}
