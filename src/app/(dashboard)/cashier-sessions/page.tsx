"use client";

import { ArrowDownUp, Printer } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { z } from "zod";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { NumberCell } from "@/components/shared/line-items";
import { DetailSheet, Fields, PageHeader, RequirePermission, SectionTitle, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchParam } from "@/hooks/use-lookups";
import { getErrorMessage } from "@/lib/api/errors";
import { printElement } from "@/lib/export";
import { formatDateTime, formatKhr, formatMoney, formatUsd, titleCase } from "@/lib/format";
import { cashSessionsApi, expenseCategoriesApi } from "@/services";
import { useAuthStore, useCan } from "@/stores/auth-store";
import type { CashSession, Currency, CurrencyAmounts } from "@/types";

const moveSchema = z.object({ kind: z.enum(["CASH_IN", "CASH_OUT", "PAID_OUT", "DROP"]), currency: z.enum(["USD", "KHR"]), amount: z.number({ error: "Enter an amount." }).positive("Amount must be greater than zero."), reason: z.string().min(1, "A reason is required."), witness: z.string(), expenseCategoryId: z.string() });
type MoveForm = z.infer<typeof moveSchema>;

const USD_NOTES = [100, 50, 20, 10, 5, 1];
const KHR_NOTES = [100000, 50000, 20000, 10000, 5000, 2000, 1000, 500, 100];

function AmountPair({ label, value }: { label: string; value: CurrencyAmounts | null }) {
  return <div className="rounded-md border p-2"><p className="text-xs text-muted-foreground">{label}</p>{value ? <><p className="tabular font-semibold">{formatUsd(value.USD)}</p><p className="tabular text-xs text-muted-foreground">{formatKhr(value.KHR)}</p></> : <p className="text-sm text-muted-foreground">Hidden until count</p>}</div>;
}

export default function CashierSessionsPage() {
  const can = useCan();
  const user = useAuthStore((s) => s.user);
  const branchId = useBranchParam();
  const { prompt, confirm } = useDialogs();
  const query = useApiQuery(["cash-sessions", branchId], () => cashSessionsApi.list({ branchId }));
  const expenseCategories = useApiQuery(["expense-categories"], () => expenseCategoriesApi.list(), { enabled: can("expenses.view", "cash.session.open") });
  const [detailId, setDetailId] = useState<string | null>(null);
  const detail = query.data?.find((s) => s.id === detailId) ?? null;
  const summary = useApiQuery(["cash-session-summary", detailId, detail?.status], () => cashSessionsApi.summary(detailId as string), { enabled: Boolean(detailId) });
  const [moving, setMoving] = useState(false);
  const [counting, setCounting] = useState(false);
  const [notes, setNotes] = useState<Record<string, number>>({});
  const [countError, setCountError] = useState<string | null>(null);
  const zRef = useRef<HTMLDivElement>(null);

  const totals = useMemo(() => {
    const value = (c: Currency, list: number[]) => list.reduce((s, n) => s + n * (notes[`${c}-${n}`] ?? 0), 0);
    return { USD: value("USD", USD_NOTES), KHR: value("KHR", KHR_NOTES) };
  }, [notes]);

  const move = useApiMutation((v: MoveForm, token?: string) => cashSessionsApi.addMovement(detailId as string, { ...v, witness: v.witness || undefined, expenseCategoryId: v.expenseCategoryId || undefined, approvalToken: token }), { success: "Cash movement recorded", silentError: true });
  const close = useApiMutation(() => cashSessionsApi.close(detailId as string, totals, notes), { success: (s) => (s.status === "CLOSED" ? "Session closed" : "Variance sent for manager approval"), silentError: true });
  const approve = useApiMutation(({ id, reason }: { id: string; reason: string }) => cashSessionsApi.approve(id, reason), { success: "Variance approved and session closed" });
  const force = useApiMutation(({ id, reason }: { id: string; reason: string }) => cashSessionsApi.forceClose(id, reason), { success: "Session force closed" });

  const columns: Column<CashSession>[] = [
    { id: "no", header: "Session", value: (s) => s.sessionNo, cell: (s) => <span className="font-mono text-xs">{s.sessionNo}</span> },
    { id: "terminal", header: "Terminal", value: (s) => s.terminalName, hideBelow: "md" },
    { id: "cashier", header: "Cashier", value: (s) => s.cashierName },
    { id: "opened", header: "Opened", value: (s) => s.openedAt, cell: (s) => formatDateTime(s.openedAt), hideBelow: "sm" },
    { id: "closed", header: "Closed", value: (s) => s.closedAt, cell: (s) => formatDateTime(s.closedAt), hideBelow: "lg" },
    { id: "variance", header: "Variance", value: (s) => s.variance?.USD, cell: (s) => (s.variance ? formatUsd(s.variance.USD) : "—"), align: "right" },
    { id: "status", header: "Status", value: (s) => s.status, cell: (s) => <StatusBadge status={s.status} /> },
  ];

  const submitCount = async () => {
    setCountError(null);
    if (!(await confirm({ title: "Submit this count?", description: `USD ${formatUsd(totals.USD)} and ${formatKhr(totals.KHR)}. You cannot change it after submitting.`, confirmLabel: "Submit count" }))) return;
    try {
      await close.run(undefined);
      setCounting(false);
      setNotes({});
    } catch (e) {
      setCountError(getErrorMessage(e));
    }
  };

  const isOwner = detail?.cashierId === user?.id;
  const data = summary.data;
  const footer = detail ? (
    <>
      <Button size="sm" variant="outline" onClick={() => printElement(zRef.current, "report")}><Printer />Print Z report</Button>
      {detail.status === "OPEN" && (isOwner || can("cash.session.approve")) ? <Button size="sm" variant="outline" onClick={() => setMoving(true)}><ArrowDownUp />Cash movement</Button> : null}
      {detail.status === "OPEN" && can("cash.session.approve") && !isOwner ? <Button size="sm" variant="outline" onClick={async () => { const reason = await prompt({ title: "Force close this session?", label: "Reason", confirmLabel: "Force close" }); if (reason) void force.fire({ id: detail.id, reason }); }}>Force close</Button> : null}
      {detail.status === "OPEN" && (isOwner || can("cash.session.approve")) ? <Button size="sm" onClick={() => { setCountError(null); setCounting(true); }}>Close session</Button> : null}
      {detail.status === "CLOSING" && can("cash.session.approve") ? <Button size="sm" onClick={async () => { const reason = await prompt({ title: "Approve variance", description: "Variance is beyond tolerance.", label: "Reason", confirmLabel: "Approve and close" }); if (reason) void approve.fire({ id: detail.id, reason }); }}>Approve variance</Button> : null}
    </>
  ) : undefined;

  return (
    <RequirePermission anyOf={["cash.session.view", "cash.session.view_all"]}>
      <PageHeader title="Cashier sessions" description="Each cashier is accountable for one drawer. Closing counts are blind. Open a session from the POS." />
      <DataTable data={query.data} columns={columns} getRowId={(s) => s.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="cashier-sessions" onRowClick={(s) => setDetailId(s.id)} searchPlaceholder="Session, terminal or cashier" dateFilter={{ label: "Opened", value: (s) => s.openedAt }} emptyTitle="No sessions yet"
        filters={[{ id: "status", label: "Statuses", options: ["OPEN", "CLOSING", "CLOSED", "FORCE_CLOSED"].map((value) => ({ value, label: titleCase(value) })), value: (s) => s.status }]} />
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetailId(null)} title={detail?.sessionNo} description={detail ? `${detail.terminalName} · ${detail.cashierName}` : undefined} footer={footer} wide>
        {detail ? (
          <div ref={zRef} className="space-y-4">
            <h2 className="hidden text-base font-semibold print:block">Session (Z) report {detail.sessionNo}</h2>
            <Fields columns={3} items={[["Status", <StatusBadge key="s" status={detail.status} />], ["Opened", formatDateTime(detail.openedAt)], ["Closed", formatDateTime(detail.closedAt)], ["Witness", detail.witness], ["Reviewed by", detail.reviewedBy], ["Variance reason", detail.varianceReason], ["Sales", data?.salesCount], ["Sales total", formatUsd(data?.salesTotal)], ["Pending payments", data?.pendingPayments]]} />
            <SectionTitle>Physical cash</SectionTitle>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <AmountPair label="Opening" value={detail.opening} />
              <AmountPair label="Cash sales" value={data?.cashSales ?? null} />
              <AmountPair label="Cash refunds" value={data?.cashRefunds ?? null} />
              <AmountPair label="Cash in" value={data?.movementTotals?.CASH_IN ?? null} />
              <AmountPair label="Cash out" value={data?.movementTotals?.CASH_OUT ?? null} />
              <AmountPair label="Paid out" value={data?.movementTotals?.PAID_OUT ?? null} />
              <AmountPair label="Drops" value={data?.movementTotals?.DROP ?? null} />
              <AmountPair label="Expected" value={detail.expected} />
              <AmountPair label="Counted" value={detail.counted} />
              <AmountPair label="Variance" value={detail.variance} />
            </div>
            <SectionTitle>Non-cash totals (excluded from expected cash)</SectionTitle>
            {data && Object.keys(data.nonCashTotals).length ? <ul className="divide-y rounded-md border text-sm">{Object.entries(data.nonCashTotals).map(([k, v]) => <li key={k} className="flex justify-between p-2"><span>{titleCase(k)}</span><span className="tabular">{formatUsd(v)}</span></li>)}</ul> : <p className="text-sm text-muted-foreground">None</p>}
            <SectionTitle>Cash movements</SectionTitle>
            {data?.movements.length ? <ul className="divide-y rounded-md border text-sm">{data.movements.map((m) => <li key={m.id} className="flex flex-wrap justify-between gap-2 p-2"><span>{titleCase(m.kind)} · {m.reason} <span className="text-xs text-muted-foreground">{m.by}</span></span><span className="tabular">{formatMoney(m.amount, m.currency)}</span></li>)}</ul> : <p className="text-sm text-muted-foreground">None</p>}
          </div>
        ) : null}
      </DetailSheet>
      <FormDialog<MoveForm> open={moving} onOpenChange={setMoving} title="Cash movement" schema={moveSchema} submitLabel="Record" onSubmit={(v) => move.run(v)} defaultValues={{ kind: "CASH_IN", currency: "USD", amount: 0, reason: "", witness: "", expenseCategoryId: "" }}
        fields={[{ name: "kind", label: "Type", type: "select", options: [{ value: "CASH_IN", label: "Cash in" }, { value: "CASH_OUT", label: "Cash out" }, { value: "PAID_OUT", label: "Paid-out expense" }, { value: "DROP", label: "Drop to safe" }] }, { name: "currency", label: "Currency", type: "select", options: [{ value: "USD", label: "USD" }, { value: "KHR", label: "KHR" }] }, { name: "amount", label: "Amount", type: "number", required: true }, { name: "witness", label: "Witness" }, { name: "expenseCategoryId", label: "Expense category", type: "select", allowNone: "Do not record as expense", full: true, options: (expenseCategories.data ?? []).map((c) => ({ value: c.id, label: c.name })), visible: (v) => v.kind === "PAID_OUT" }, { name: "reason", label: "Reason", full: true, required: true }]} />
      <Dialog open={counting} onOpenChange={setCounting}>
        <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle>Blind closing count</DialogTitle><DialogDescription>Count the drawer by denomination. Expected cash stays hidden until you submit.</DialogDescription></DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            {([["USD", USD_NOTES], ["KHR", KHR_NOTES]] as const).map(([currency, list]) => (
              <div key={currency} className="space-y-1.5">
                <p className="text-sm font-medium">{currency}</p>
                {list.map((n) => <div key={n} className="flex items-center justify-between gap-2"><span className="tabular text-sm">{formatMoney(n, currency)}</span><NumberCell label={`${n} ${currency} notes`} value={notes[`${currency}-${n}`] ?? 0} onChange={(v) => setNotes((x) => ({ ...x, [`${currency}-${n}`]: v }))} className="h-10" /></div>)}
                <p className="tabular border-t pt-1.5 text-right font-semibold">{formatMoney(totals[currency], currency)}</p>
              </div>
            ))}
          </div>
          {countError ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{countError}</p> : null}
          <DialogFooter><Button variant="outline" onClick={() => setCounting(false)}>Go back</Button><Button disabled={close.isPending} onClick={() => void submitCount()}>Submit count</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </RequirePermission>
  );
}
