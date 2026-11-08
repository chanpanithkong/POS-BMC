"use client";

import { Check, CreditCard, Landmark, Loader2, QrCode, Trash2, Wallet, Banknote, TicketPercent } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useApiQuery } from "@/hooks/use-api";
import { usePosActions } from "@/hooks/use-pos";
import { ApiError, getErrorMessage } from "@/lib/api/errors";
import { formatKhr, formatMoney, formatUsd, titleCase } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { paymentMethodsApi } from "@/services";
import { usePosStore } from "@/stores/pos-store";
import type { Currency, PaymentMethodCode } from "@/types";

const METHODS: { code: PaymentMethodCode; label: string; icon: typeof Banknote }[] = [
  { code: "CASH", label: "Cash", icon: Banknote },
  { code: "QR", label: "QR payment", icon: QrCode },
  { code: "CARD", label: "Card", icon: CreditCard },
  { code: "BANK_TRANSFER", label: "Bank transfer", icon: Landmark },
  { code: "STORE_CREDIT", label: "Store credit", icon: Wallet },
];

const KEYS = ["7", "8", "9", "4", "5", "6", "1", "2", "3", ".", "0", "C"];

export function PaymentDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const t = useT();
  const sale = usePosStore((s) => s.sale);
  const { addPayment, resolvePayment, finalize } = usePosActions();
  const methodsQuery = useApiQuery(["payment-methods"], () => paymentMethodsApi.list());
  const [method, setMethod] = useState<PaymentMethodCode>("CASH");
  const [currency, setCurrency] = useState<Currency>("USD");
  const [changeCurrency, setChangeCurrency] = useState<Currency>("USD");
  const [amountInput, setAmount] = useState<string | null>(null);
  const [reference, setReference] = useState("");
  const [approvalCode, setApprovalCode] = useState("");
  const [cardLast4, setCardLast4] = useState("");
  const [qrReference, setQrReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rate = sale?.exchangeRate ?? 4100;
  const balance = sale?.balance ?? 0;
  const dueKhr = Math.round((balance * rate) / 100) * 100;

  // Non-cash amounts default to the remaining balance; cash starts empty for the tendered amount.
  const amount = amountInput ?? (method !== "CASH" && balance > 0 ? balance.toFixed(2) : "");

  const selectMethod = (next: PaymentMethodCode) => {
    setMethod(next);
    if (next !== "CASH") setCurrency("USD");
    setAmount(null);
    setError(null);
  };

  const enabled = methodsQuery.data?.filter((m) => m.status === "ACTIVE").map((m) => m.code) ?? ["CASH"];
  const tendered = Number(amount) || 0;
  const tenderedBase = currency === "KHR" ? tendered / rate : tendered;
  const covers = currency === "KHR" ? tendered >= dueKhr : tendered >= balance - 0.0001;

  // Display-only preview; the server computes the stored change.
  const changePreview = useMemo(() => {
    if (method !== "CASH" || !covers || !tendered) return 0;
    const changeBase = currency === "KHR" ? (tendered - dueKhr) / rate : tendered - balance;
    if (changeBase <= 0) return 0;
    return changeCurrency === "KHR" ? Math.round((changeBase * rate) / 100) * 100 : Math.round(changeBase * 100) / 100;
  }, [balance, changeCurrency, covers, currency, dueKhr, method, rate, tendered]);

  const quickAmounts = useMemo(() => {
    if (currency === "USD") {
      const exact = Math.ceil(balance * 100) / 100;
      return [...new Set([exact, Math.ceil(balance), 5, 10, 20, 50, 100].filter((v) => v >= balance))].slice(0, 5);
    }
    const steps = [dueKhr, Math.ceil(dueKhr / 5000) * 5000, Math.ceil(dueKhr / 10000) * 10000, Math.ceil(dueKhr / 50000) * 50000, Math.ceil(dueKhr / 100000) * 100000];
    return [...new Set(steps)].slice(0, 5);
  }, [balance, currency, dueKhr]);

  const pending = sale?.payments.filter((p) => p.status === "PENDING") ?? [];
  const failed = sale?.payments.filter((p) => p.status === "FAILED") ?? [];
  const recorded = sale?.payments.filter((p) => p.status === "COMPLETED") ?? [];

  const press = (key: string) => {
    if (key === "C") setAmount("");
    else if (key === ".") setAmount(amount.includes(".") || currency === "KHR" ? amount : `${amount || "0"}.`);
    else setAmount(`${amount}${key}`);
  };

  const finish = async () => {
    await finalize();
    onOpenChange(false);
  };

  const guarded = async (task: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (e) {
      const message = getErrorMessage(e);
      setError(message);
      if (e instanceof ApiError && e.code === "INSUFFICIENT_STOCK") toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  const submit = () =>
    guarded(async () => {
      if (!tendered) {
        setError("Enter an amount.");
        return;
      }
      if (method === "CARD" && !/^\d{4}$/.test(cardLast4)) {
        setError("Enter the last four digits of the card.");
        return;
      }
      const updated = await addPayment({
        method, currency, amountTendered: tendered, changeCurrency: method === "CASH" ? changeCurrency : currency,
        reference: reference || undefined, approvalCode: approvalCode || undefined, cardLast4: cardLast4 || undefined,
      });
      setAmount(null);
      setReference("");
      setApprovalCode("");
      setCardLast4("");
      if (updated.balance <= 0.005 && !updated.payments.some((p) => p.status === "PENDING")) await finish();
    });

  if (!sale) return null;
  const needsReference = method === "CARD" || method === "BANK_TRANSFER";
  const label = method === "CASH" ? t("Amount received") : "Amount";

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("Pay")}</DialogTitle>
          <DialogDescription>Choose a method and record the amount. Add more payments to split the sale.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 md:grid-cols-[1fr_16rem]">
          <div className="min-w-0 space-y-3">
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
              {METHODS.filter((m) => enabled.includes(m.code)).map((m) => (
                <button key={m.code} type="button" onClick={() => selectMethod(m.code)} aria-pressed={method === m.code} className={cn("flex min-h-16 flex-col items-center justify-center gap-1 rounded-md border p-1.5 text-xs font-medium", method === m.code ? "border-primary bg-accent text-accent-foreground" : "hover:bg-muted")}>
                  <m.icon className="size-5" />{t(m.label)}
                </button>
              ))}
            </div>

            {method === "CASH" ? (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">Tender in</span>
                  {(["USD", "KHR"] as Currency[]).map((c) => <Button key={c} type="button" size="sm" variant={currency === c ? "default" : "outline"} onClick={() => { setCurrency(c); setChangeCurrency(c); setAmount(""); }}>{c}</Button>)}
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-muted-foreground">Change in</span>
                  {(["USD", "KHR"] as Currency[]).map((c) => <Button key={c} type="button" size="sm" variant={changeCurrency === c ? "default" : "outline"} onClick={() => setChangeCurrency(c)}>{c}</Button>)}
                </div>
              </div>
            ) : null}

            <div className="space-y-1.5">
              <Label htmlFor="pay-amount">{label} ({currency})</Label>
              <Input id="pay-amount" autoFocus inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void submit(); } }} className="tabular h-12 text-right text-2xl font-semibold" />
            </div>

            {method === "CASH" ? (
              <>
                <div className="grid grid-cols-5 gap-1.5">
                  {quickAmounts.map((v, i) => <Button key={v} type="button" variant="outline" className="h-12 px-1 text-xs" onClick={() => setAmount(String(v))}>{i === 0 ? "Exact" : formatMoney(v, currency)}</Button>)}
                </div>
                <div className="grid grid-cols-3 gap-1.5 sm:hidden lg:grid">
                  {KEYS.map((k) => <Button key={k} type="button" variant="secondary" className="h-12 text-lg" onClick={() => press(k)}>{k}</Button>)}
                </div>
              </>
            ) : null}

            {method === "CARD" ? (
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1.5"><Label htmlFor="card-ref">Terminal reference</Label><Input id="card-ref" value={reference} onChange={(e) => setReference(e.target.value)} /></div>
                <div className="space-y-1.5"><Label htmlFor="card-approval">Approval code</Label><Input id="card-approval" value={approvalCode} onChange={(e) => setApprovalCode(e.target.value)} /></div>
                <div className="space-y-1.5"><Label htmlFor="card-last4">Card last 4</Label><Input id="card-last4" inputMode="numeric" maxLength={4} value={cardLast4} onChange={(e) => setCardLast4(e.target.value.replace(/\D/g, ""))} /></div>
                <p className="col-span-2 text-xs text-muted-foreground">Enter details from the standalone terminal. Full card numbers are never stored.</p>
              </div>
            ) : null}
            {method === "BANK_TRANSFER" ? <div className="space-y-1.5"><Label htmlFor="bank-ref">Bank reference</Label><Input id="bank-ref" value={reference} onChange={(e) => setReference(e.target.value)} /></div> : null}
            {method === "QR" ? <p className="rounded-md bg-muted p-2 text-xs text-muted-foreground">The payment stays pending until you enter the verified reference from your bank app. Provider integration comes later (V-03).</p> : null}

            {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
            <Button type="button" className="h-16 w-full text-base" disabled={busy || balance <= 0 || (needsReference && !reference)} onClick={() => void submit()}>
              {busy ? <Loader2 className="animate-spin" /> : <Check />}
              {method === "QR" ? "Create QR payment" : covers || tenderedBase >= balance ? t("Complete sale") : "Add payment"}
            </Button>
          </div>

          <div className="space-y-3">
            <div className="rounded-md border p-3">
              <p className="text-xs text-muted-foreground">{t("Total")}</p>
              <p className="tabular text-2xl font-bold">{formatUsd(sale.grandTotal)}</p>
              <p className="tabular text-sm text-muted-foreground">{formatKhr(sale.grandTotalKhr)} at {rate.toLocaleString()}</p>
              <div className="mt-2 border-t pt-2">
                <p className="text-xs text-muted-foreground">{t("Balance")}</p>
                <p className="tabular text-lg font-semibold">{formatUsd(balance)}</p>
                <p className="tabular text-sm text-muted-foreground">{formatKhr(dueKhr)}</p>
              </div>
              {method === "CASH" && changePreview > 0 ? (
                <div className="mt-2 rounded-md bg-accent p-2">
                  <p className="text-xs">{t("Change")}</p>
                  <p className="tabular text-xl font-bold">{formatMoney(changePreview, changeCurrency)}</p>
                </div>
              ) : null}
            </div>

            {pending.map((p) => (
              <div key={p.id} className="space-y-2 rounded-md border border-warning/40 p-2.5">
                <div className="flex items-center justify-between"><span className="text-sm font-medium">{titleCase(p.method)} {formatUsd(p.amountApplied)}</span><StatusBadge status={p.status} /></div>
                <p className="text-xs text-muted-foreground">Payment still pending — waiting for confirmation.</p>
                <Input placeholder="Verified reference" aria-label="Verified reference" value={qrReference} onChange={(e) => setQrReference(e.target.value)} />
                <div className="flex gap-1.5">
                  <Button size="sm" className="flex-1" disabled={busy || !qrReference} onClick={() => void guarded(async () => {
                    const updated = await resolvePayment(p.id, "COMPLETED", qrReference);
                    setQrReference("");
                    if (updated.balance <= 0.005 && !updated.payments.some((x) => x.status === "PENDING")) await finish();
                  })}>Confirm</Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void guarded(async () => { await resolvePayment(p.id, "FAILED", undefined, "Customer payment failed"); })}>Failed</Button>
                  <Button size="sm" variant="ghost" disabled={busy} aria-label="Cancel payment" onClick={() => void guarded(async () => { await resolvePayment(p.id, "CANCELLED"); })}><Trash2 /></Button>
                </div>
              </div>
            ))}
            {recorded.length ? (
              <div className="rounded-md border p-2.5 text-sm">
                <p className="mb-1 text-xs text-muted-foreground">Payments recorded</p>
                {recorded.map((p) => <div key={p.id} className="flex justify-between"><span>{titleCase(p.method)}</span><span className="tabular">{formatUsd(p.amountApplied)}</span></div>)}
              </div>
            ) : null}
            {failed.length ? <p className="text-xs text-destructive">Last payment failed: {failed[failed.length - 1].failureReason}. Choose another method.</p> : null}
            {balance <= 0 && !pending.length ? <Button className="w-full" onClick={() => void guarded(finish)}><TicketPercent />{t("Complete sale")}</Button> : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
