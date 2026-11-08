"use client";

import { FileText, Printer, RotateCcw, Undo2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { DetailSheet, Fields, PageHeader, RequirePermission, SectionTitle, StatusBadge } from "@/components/shared/page";
import { ReceiptDialog } from "@/components/shared/receipt";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchOptions, useBranchParam } from "@/hooks/use-lookups";
import { printElement } from "@/lib/export";
import { formatDateTime, formatKhr, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { returnsApi, salesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Sale } from "@/types";

export default function SalesHistoryPage() {
  const can = useCan();
  const router = useRouter();
  const params = useSearchParams();
  const branchId = useBranchParam();
  const { prompt } = useDialogs();
  const query = useApiQuery(["sales", branchId], () => salesApi.list({ branchId }));
  const returns = useApiQuery(["returns"], returnsApi.list);
  const branches = useBranchOptions();
  const [detailId, setDetailId] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<Sale | null>(null);
  const [invoice, setInvoice] = useState<Sale | null>(null);
  const invoiceRef = useRef<HTMLDivElement>(null);
  const detail = query.data?.find((s) => s.id === detailId) ?? null;
  const reprint = useApiMutation((id: string) => salesApi.reprint(id), { onSuccess: setReceipt });
  const makeInvoice = useApiMutation((id: string) => salesApi.invoice(id), { onSuccess: setInvoice });
  const voidSale = useApiMutation(({ id, reason }: { id: string; reason: string }, token?: string) => salesApi.void(id, reason, token), { success: "Sale voided and stock restored" });
  const showCost = can("costs.view");

  const columns: Column<Sale>[] = [
    { id: "receipt", header: "Receipt no.", value: (s) => s.receiptNo ?? "Not numbered", cell: (s) => <span className="font-mono text-xs whitespace-nowrap">{s.receiptNo ?? "Not numbered"}</span> },
    { id: "at", header: "Date", value: (s) => s.finalizedAt ?? s.createdAt, cell: (s) => <span className="whitespace-nowrap">{formatDateTime(s.finalizedAt ?? s.createdAt)}</span> },
    { id: "branch", header: "Branch", value: (s) => s.branchName, hideBelow: "lg" },
    { id: "terminal", header: "Terminal", value: (s) => s.terminalName, hideBelow: "xl" },
    { id: "cashier", header: "Cashier", value: (s) => s.cashierName, hideBelow: "xl" },
    { id: "customer", header: "Customer", value: (s) => s.customerName ?? "Walk-in", hideBelow: "md" },
    { id: "total", header: "Total", value: (s) => s.grandTotal, cell: (s) => formatUsd(s.grandTotal), align: "right" },
    { id: "payment", header: "Payment", value: (s) => s.paymentStatus, cell: (s) => <StatusBadge status={s.paymentStatus} />, hideBelow: "sm" },
    { id: "status", header: "Sale", value: (s) => s.status, cell: (s) => <StatusBadge status={s.status} /> },
  ];

  const askVoid = async () => {
    if (!detail) return;
    const reason = await prompt({ title: `Void ${detail.receiptNo}?`, description: "Stock returns to its location and payments are reversed. Requires approval from a different user.", label: "Reason", confirmLabel: "Continue" });
    if (reason) void voidSale.fire({ id: detail.id, reason });
  };

  const linkedReturns = returns.data?.filter((r) => detail?.returnIds.includes(r.id)) ?? [];

  return (
    <RequirePermission anyOf={["sales.view"]}>
      <PageHeader title="Sales history" description="Finalized sales are never deleted or edited. Corrections use voids and returns." />
      <DataTable data={query.data} columns={columns} getRowId={(s) => s.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="sales" onRowClick={(s) => setDetailId(s.id)} searchPlaceholder="Receipt, cashier, customer or product" initialSearch={params.get("q") ?? ""} searchText={(s) => s.lines.map((l) => `${l.nameEn} ${l.sku}`).join(" ")} dateFilter={{ label: "Date", value: (s) => s.businessDate ?? s.createdAt }} emptyTitle="No sales yet" emptyDescription="Sales appear here when they are finalized on the POS."
        filters={[
          { id: "status", label: "Statuses", options: ["FINALIZED", "VOIDED", "CANCELLED"].map((value) => ({ value, label: titleCase(value) })), value: (s) => s.status },
          { id: "payment", label: "Payment states", options: ["PAID", "PARTIALLY_REFUNDED", "REFUNDED", "UNPAID"].map((value) => ({ value, label: titleCase(value) })), value: (s) => s.paymentStatus },
          { id: "branch", label: "Branches", options: branches, value: (s) => s.branchId },
        ]}
      />
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetailId(null)} title={detail?.receiptNo ?? "Sale"} description={detail ? `${detail.branchName} · ${detail.terminalName}` : undefined} wide
        footer={detail && detail.status === "FINALIZED" ? (
          <>
            <Button size="sm" variant="outline" onClick={() => void reprint.fire(detail.id)}><Printer />Reprint (copy)</Button>
            <Button size="sm" variant="outline" onClick={() => void makeInvoice.fire(detail.id)}><FileText />Invoice</Button>
            {can("sales.void", "pos.sell") ? <Button size="sm" variant="outline" disabled={voidSale.isPending} onClick={() => void askVoid()}><Undo2 />Void</Button> : null}
            {can("returns.create") ? <Button size="sm" onClick={() => router.push(`/sales/returns?receipt=${detail.receiptNo}`)}><RotateCcw />Return</Button> : null}
          </>
        ) : undefined}>
        {detail ? (
          <>
            <Fields columns={3} items={[["Sale status", <StatusBadge key="a" status={detail.status} />], ["Payment status", <StatusBadge key="b" status={detail.paymentStatus} />], ["Business date", detail.businessDate], ["Cashier", detail.cashierName], ["Customer", detail.customerName ?? "Walk-in"], ["Reprints", detail.reprintCount], ["Total (USD)", formatUsd(detail.grandTotal)], ["Total (KHR)", formatKhr(detail.grandTotalKhr)], ["Refunded", formatUsd(detail.refundedTotal)], ...(detail.voidReason ? [["Void reason", detail.voidReason], ["Voided by", detail.voidedBy]] as [string, string | null][] : []), ...(detail.cancelReason ? [["Cancel reason", detail.cancelReason]] as [string, string][] : [])]} />
            <SectionTitle>Lines</SectionTitle>
            <div className="overflow-x-auto rounded-md border"><Table><TableHeader><TableRow><TableHead className="h-8">Product</TableHead><TableHead className="h-8 text-right">Qty</TableHead><TableHead className="h-8 text-right">Price</TableHead><TableHead className="h-8 text-right">Discount</TableHead><TableHead className="h-8 text-right">Tax</TableHead><TableHead className="h-8 text-right">Total</TableHead>{showCost ? <TableHead className="h-8 text-right">Unit cost</TableHead> : null}<TableHead className="h-8 text-right">Returned</TableHead></TableRow></TableHeader><TableBody>{detail.lines.map((l) => <TableRow key={l.id}><TableCell className="max-w-52 truncate py-1.5" title={l.priceExplanation}>{l.nameEn}</TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(l.quantity)} {l.unitCode}</TableCell><TableCell className="tabular py-1.5 text-right">{formatUsd(l.unitPrice)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatUsd(l.discountAmount + l.orderDiscountShare)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatUsd(l.taxAmount)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatUsd(l.lineTotal)}</TableCell>{showCost ? <TableCell className="tabular py-1.5 text-right">{formatUsd(l.unitCost)}</TableCell> : null}<TableCell className="tabular py-1.5 text-right">{formatNumber(l.returnedQuantity)}</TableCell></TableRow>)}</TableBody></Table></div>
            <SectionTitle>Payments</SectionTitle>
            <ul className="divide-y rounded-md border text-sm">{detail.payments.map((p) => <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 p-2"><span>{titleCase(p.method)} {p.reference ? <span className="font-mono text-xs text-muted-foreground">{p.reference}</span> : null}</span><span className="flex items-center gap-2"><StatusBadge status={p.status} /><span className="tabular">{formatUsd(p.amountApplied)}</span></span></li>)}</ul>
            {linkedReturns.length ? <><SectionTitle>Returns</SectionTitle><ul className="divide-y rounded-md border text-sm">{linkedReturns.map((r) => <li key={r.id} className="flex justify-between gap-2 p-2"><span className="font-mono text-xs">{r.returnNo}</span><span className="tabular">{formatUsd(r.refundTotal)}</span></li>)}</ul></> : null}
          </>
        ) : null}
      </DetailSheet>
      <ReceiptDialog sale={receipt} copy onClose={() => setReceipt(null)} />
      <Dialog open={invoice !== null} onOpenChange={(o) => !o && setInvoice(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>Invoice {invoice?.invoiceNo}</DialogTitle><DialogDescription>A4 invoice. Mandatory tax content must be confirmed (V-02).</DialogDescription></DialogHeader>
          <div ref={invoiceRef} className="space-y-3 text-sm">
            <h2 className="text-lg font-semibold">Invoice {invoice?.invoiceNo}</h2>
            <p>Receipt {invoice?.receiptNo} · {formatDateTime(invoice?.finalizedAt)} · {invoice?.branchName}</p>
            <p>Bill to: {invoice?.customerName ?? "Walk-in customer"}</p>
            <table className="w-full text-left"><thead><tr><th>Item</th><th>Qty</th><th>Price</th><th>Tax</th><th>Total</th></tr></thead><tbody>{invoice?.lines.map((l) => <tr key={l.id}><td>{l.nameEn}</td><td>{formatNumber(l.quantity)} {l.unitCode}</td><td>{formatUsd(l.unitPrice)}</td><td>{formatUsd(l.taxAmount)}</td><td>{formatUsd(l.lineTotal)}</td></tr>)}</tbody></table>
            <p className="tabular text-right font-semibold">Total {formatUsd(invoice?.grandTotal)} ({formatKhr(invoice?.grandTotalKhr)})</p>
          </div>
          <DialogFooter><Button onClick={() => printElement(invoiceRef.current, "report")}><Printer />Print / PDF</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </RequirePermission>
  );
}
