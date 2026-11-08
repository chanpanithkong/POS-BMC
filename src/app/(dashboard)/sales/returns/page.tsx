"use client";

import { Calculator, Plus, Printer, Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { LineItems, NumberCell, ProductPicker, useProducts } from "@/components/shared/line-items";
import { PageHeader, RequirePermission, SectionTitle, StatusBadge } from "@/components/shared/page";
import { ReturnReceiptDialog } from "@/components/shared/receipt";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { getErrorMessage } from "@/lib/api/errors";
import { formatDateTime, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { returnsApi, salesApi, settingsApi, terminalsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";
import type { CreateReturnInput, PaymentMethodCode, ReturnCondition, ReturnQuote, Sale, SalesReturn } from "@/types";

interface ReturnLine { saleLineId: string; name: string; remaining: number; unit: string; quantity: number; condition: ReturnCondition; reason: string; allowFraction: boolean }
interface ExchangeLine { productId: string; name: string; quantity: number; price: number }

const CONDITIONS: ReturnCondition[] = ["RESALABLE", "DAMAGED", "EXPIRED", "NON_RETURNABLE"];
const METHODS: PaymentMethodCode[] = ["CASH", "CARD", "QR", "BANK_TRANSFER", "STORE_CREDIT"];
const ELECTRONIC: PaymentMethodCode[] = ["CARD", "QR", "BANK_TRANSFER"];

export default function ReturnsPage() {
  const can = useCan();
  const params = useSearchParams();
  const { confirm, prompt } = useDialogs();
  const query = useApiQuery(["returns"], returnsApi.list);
  const settings = useApiQuery(["settings"], settingsApi.get);
  const terminals = useApiQuery(["terminals"], () => terminalsApi.list());
  const products = useProducts((p) => p.status === "ACTIVE");
  const terminalId = useUiStore((s) => s.terminalId);
  const setTerminal = useUiStore((s) => s.setTerminal);
  const receiptParam = params.get("receipt");
  const [open, setOpen] = useState(Boolean(receiptParam) || params.get("new") === "1");
  const [search, setSearch] = useState(receiptParam ?? "");
  const [seenReceipt, setSeenReceipt] = useState(receiptParam);
  if (receiptParam !== seenReceipt) {
    setSeenReceipt(receiptParam);
    if (receiptParam) {
      setOpen(true);
      setSearch(receiptParam);
    }
  }
  const [sale, setSale] = useState<Sale | null>(null);
  const [lines, setLines] = useState<ReturnLine[]>([]);
  const [method, setMethod] = useState<PaymentMethodCode>("CASH");
  const [reference, setReference] = useState("");
  const [exchange, setExchange] = useState<ExchangeLine[]>([]);
  const [settlement, setSettlement] = useState<PaymentMethodCode>("CASH");
  const [settlementRef, setSettlementRef] = useState("");
  const [quote, setQuote] = useState<ReturnQuote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [printed, setPrinted] = useState<SalesReturn | null>(null);

  const reset = () => {
    setSale(null);
    setLines([]);
    setQuote(null);
    setError(null);
    setExchange([]);
    setReference("");
    setSettlementRef("");
    setMethod("CASH");
  };

  const findSale = async (receipt: string) => {
    try {
      const all = await salesApi.list();
      setError(null);
      const hit = all.find((s) => s.receiptNo?.toLowerCase() === receipt.trim().toLowerCase());
      if (!hit) return setError("No finalized sale found with that receipt number.");
      if (hit.status !== "FINALIZED") return setError(`This sale is ${titleCase(hit.status)} and cannot be returned.`);
      setSale(hit);
      setLines(hit.lines.map((l) => ({ saleLineId: l.id, name: l.nameEn, remaining: Math.round((l.quantity - l.returnedQuantity) * 1000) / 1000, unit: l.unitCode, quantity: 0, condition: "RESALABLE", reason: "", allowFraction: l.allowFraction })));
      setMethod(hit.payments.find((p) => p.status === "COMPLETED" || p.status === "PARTIALLY_REFUNDED")?.method ?? "CASH");
      setQuote(null);
    } catch (e) {
      setError(getErrorMessage(e));
    }
  };

  useEffect(() => {
    // Loads the sale when arriving from sales history or the POS; state changes after the request resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (receiptParam) void findSale(receiptParam);
  }, [receiptParam]);

  const payload = (): CreateReturnInput => ({
    lines: lines.filter((l) => l.quantity > 0).map(({ saleLineId, quantity, condition, reason }) => ({ saleLineId, quantity, condition, reason })),
    refundMethod: method, reference: reference || undefined,
    replacementLines: exchange.length ? exchange.map((l) => ({ productId: l.productId, quantity: l.quantity })) : undefined,
    settlementMethod: exchange.length ? settlement : undefined, settlementReference: settlementRef || undefined,
  });

  const calculate = async () => {
    if (!sale) return;
    setError(null);
    if (!lines.some((l) => l.quantity > 0)) return setError("Enter a quantity on at least one line.");
    try {
      setQuote(await salesApi.quoteReturn(sale.id, payload()));
    } catch (e) {
      setQuote(null);
      setError(getErrorMessage(e));
    }
  };

  const complete = useApiMutation((_: undefined, token?: string) => salesApi.createReturn(sale?.id ?? "", { ...payload(), approvalToken: token }), {
    success: "Return completed", silentError: true, approvalAmount: quote?.refundTotal ?? 0,
    onSuccess: (r) => { setOpen(false); reset(); setSearch(""); setPrinted(r); },
  });

  const submit = async () => {
    if (lines.some((l) => l.quantity > 0 && !l.reason.trim())) return setError("Enter a reason for each returned line.");
    if (!quote) return;
    const label = quote.difference > 0 ? `Customer pays ${formatUsd(quote.difference)} difference.` : exchange.length ? `Refund ${formatUsd(-quote.difference)} difference.` : `Refund ${formatUsd(quote.refundTotal)} by ${titleCase(method)}.`;
    if (!(await confirm({ title: "Complete this return?", description: `${label} Stock moves according to each line's condition.`, confirmLabel: "Complete return" }))) return;
    setError(null);
    await complete.run(undefined).catch((e: unknown) => setError(getErrorMessage(e)));
  };

  const confirmRefund = useApiMutation(({ id, reference: ref }: { id: string; reference: string }) => returnsApi.confirmRefund(id, ref), { success: "Refund confirmed" });
  const columns = useMemo<Column<SalesReturn>[]>(() => [
    { id: "no", header: "Return", value: (r) => r.returnNo, cell: (r) => <span className="font-mono text-xs">{r.returnNo}</span> },
    { id: "receipt", header: "Original receipt", value: (r) => r.originalReceiptNo, cell: (r) => <span className="font-mono text-xs">{r.originalReceiptNo}</span>, hideBelow: "lg" },
    { id: "type", header: "Type", value: (r) => titleCase(r.type), hideBelow: "md" },
    { id: "method", header: "Method", value: (r) => titleCase(r.refundMethod), hideBelow: "md" },
    { id: "total", header: "Refund", value: (r) => r.refundTotal, cell: (r) => formatUsd(r.refundTotal), align: "right" },
    { id: "by", header: "Processed by", value: (r) => r.createdBy, hideBelow: "xl" },
    { id: "approver", header: "Approved by", value: (r) => r.approvedBy, hideBelow: "xl" },
    { id: "at", header: "Date", value: (r) => r.createdAt, cell: (r) => formatDateTime(r.createdAt), hideBelow: "sm" },
    { id: "status", header: "Refund", value: (r) => r.refundStatus, cell: (r) => <StatusBadge status={r.refundStatus} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (r) => (
      <div className="flex justify-end gap-1">
        {r.refundStatus === "PENDING" ? <Button variant="ghost" size="sm" onClick={async () => { const ref = await prompt({ title: "Confirm electronic refund", label: "Provider or bank reference", confirmLabel: "Confirm" }); if (ref) void confirmRefund.fire({ id: r.id, reference: ref }); }}>Confirm</Button> : null}
        <Button variant="ghost" size="icon-sm" aria-label="Print return receipt" onClick={() => setPrinted(r)}><Printer /></Button>
      </div>
    ) },
    // `prompt` and the mutation are stable in effect; columns only depend on row shape.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], []);

  const needsTerminal = !terminalId;

  return (
    <RequirePermission anyOf={["returns.create", "sales.view"]}>
      <PageHeader title="Returns and refunds" description="Linked to the original sale. Only resalable returns go back into sellable stock." />
      <DataTable data={query.data} columns={columns} getRowId={(r) => r.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="returns" searchPlaceholder="Return or receipt number" dateFilter={{ label: "Date", value: (r) => r.createdAt }} emptyTitle="No returns yet"
        filters={[{ id: "status", label: "Refund states", options: [{ value: "COMPLETED", label: "Completed" }, { value: "PENDING", label: "Pending" }], value: (r) => r.refundStatus }, { id: "type", label: "Types", options: [{ value: "RETURN", label: "Return" }, { value: "EXCHANGE", label: "Exchange" }], value: (r) => r.type }]}
        toolbar={can("returns.create") ? <Button size="sm" onClick={() => { reset(); setSearch(""); setOpen(true); }}><Plus />New return</Button> : undefined} />
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader><DialogTitle>New return or exchange</DialogTitle><DialogDescription>Scan or type the receipt number from the original sale.</DialogDescription></DialogHeader>
          <form onSubmit={(e) => { e.preventDefault(); void findSale(search); }} className="flex gap-2">
            <Input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="R-TK01-2026-000123" aria-label="Receipt number" className="h-12 font-mono" />
            <Button type="submit" variant="outline" className="h-12"><Search />Find</Button>
          </form>
          {needsTerminal ? (
            <div className="space-y-1 rounded-md border border-warning/40 p-2.5"><Label>Terminal processing this return</Label><Select onValueChange={setTerminal}><SelectTrigger className="w-full" aria-label="Terminal"><SelectValue placeholder="Select a terminal" /></SelectTrigger><SelectContent>{terminals.data?.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}</SelectContent></Select></div>
          ) : null}
          {sale ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">Sold {formatDateTime(sale.finalizedAt)} at {sale.branchName} · {sale.customerName ?? "Walk-in"} · {formatUsd(sale.grandTotal)}. Return window {settings.data?.returnWindowDays} days by default.</p>
              <LineItems<ReturnLine> lines={lines} onChange={(l) => { setLines(l); setQuote(null); }} removable={false} columns={[
                { header: "Item", cell: (l) => <span className="block max-w-52 truncate text-sm">{l.name}</span> },
                { header: "Returnable", align: "right", cell: (l) => `${formatNumber(l.remaining)} ${l.unit}` },
                { header: "Return qty", align: "right", cell: (l, u) => <NumberCell label="Return quantity" value={l.quantity} onChange={(quantity) => u({ quantity })} /> },
                { header: "Condition", cell: (l, u) => <Select value={l.condition} onValueChange={(v) => u({ condition: v as ReturnCondition })}><SelectTrigger size="sm" className="w-36" aria-label="Condition"><SelectValue /></SelectTrigger><SelectContent>{CONDITIONS.map((c) => <SelectItem key={c} value={c}>{titleCase(c)}</SelectItem>)}</SelectContent></Select> },
                { header: "Reason", cell: (l, u) => <Input aria-label="Reason" className="h-8 w-36" value={l.reason} onChange={(e) => u({ reason: e.target.value })} /> },
              ]} />
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1"><Label>Refund method</Label><Select value={method} onValueChange={(v) => { setMethod(v as PaymentMethodCode); setQuote(null); }}><SelectTrigger className="w-full" aria-label="Refund method"><SelectValue /></SelectTrigger><SelectContent>{METHODS.filter((m) => m !== "STORE_CREDIT" || (settings.data?.storeCreditEnabled && sale.customerId)).map((m) => <SelectItem key={m} value={m}>{titleCase(m)}</SelectItem>)}</SelectContent></Select></div>
                {ELECTRONIC.includes(method) ? <div className="space-y-1"><Label htmlFor="ret-ref">Refund reference</Label><Input id="ret-ref" placeholder="Blank leaves the refund pending" value={reference} onChange={(e) => setReference(e.target.value)} /></div> : null}
              </div>
              <SectionTitle>Exchange items (optional)</SectionTitle>
              <LineItems<ExchangeLine> lines={exchange} onChange={(l) => { setExchange(l); setQuote(null); }} picker={<ProductPicker products={products} onPick={(p) => { setExchange((l) => [...l, { productId: p.id, name: p.nameEn, quantity: 1, price: p.retailPrice }]); setQuote(null); }} placeholder="Add replacement items" />} emptyText="Leave empty for a plain refund." columns={[{ header: "Item", cell: (l) => <span className="block max-w-72 truncate text-sm">{l.name}</span> }, { header: "Qty", align: "right", cell: (l, u) => <NumberCell label="Quantity" value={l.quantity} onChange={(quantity) => u({ quantity })} /> }, { header: "Price", align: "right", cell: (l) => formatUsd(l.price) }]} />
              {exchange.length ? <div className="grid gap-3 sm:grid-cols-2"><div className="space-y-1"><Label>Customer pays difference by</Label><Select value={settlement} onValueChange={(v) => setSettlement(v as PaymentMethodCode)}><SelectTrigger className="w-full" aria-label="Settlement method"><SelectValue /></SelectTrigger><SelectContent>{METHODS.filter((m) => m !== "STORE_CREDIT" && m !== "QR").map((m) => <SelectItem key={m} value={m}>{titleCase(m)}</SelectItem>)}</SelectContent></Select></div>{settlement !== "CASH" ? <div className="space-y-1"><Label htmlFor="ex-ref">Reference</Label><Input id="ex-ref" value={settlementRef} onChange={(e) => setSettlementRef(e.target.value)} /></div> : null}</div> : null}
              {quote ? (
                <div className="rounded-md border p-3 text-sm">
                  <div className="tabular grid grid-cols-3 gap-2"><div><p className="text-xs text-muted-foreground">Net</p>{formatUsd(quote.netTotal)}</div><div><p className="text-xs text-muted-foreground">Tax</p>{formatUsd(quote.taxTotal)}</div><div><p className="text-xs text-muted-foreground">Refund total</p><p className="text-lg font-semibold">{formatUsd(quote.refundTotal)}</p></div></div>
                  {exchange.length ? <p className="tabular mt-2">Replacement {formatUsd(quote.replacementTotal)} · Difference {formatUsd(quote.difference)}</p> : null}
                  {quote.approvalReasons.length ? <p className="mt-2 text-warning">Approval needed: {quote.approvalReasons.join("; ")}</p> : null}
                </div>
              ) : null}
            </div>
          ) : null}
          {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
          <DialogFooter>
            <Button variant="outline" disabled={!sale} onClick={() => void calculate()}><Calculator />Calculate</Button>
            <Button disabled={!quote || complete.isPending || needsTerminal} onClick={() => void submit()}>Complete return</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ReturnReceiptDialog record={printed} onClose={() => setPrinted(null)} />
    </RequirePermission>
  );
}
