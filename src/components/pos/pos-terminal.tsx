"use client";

import { ArrowLeft, Ban, CircleUserRound, History, Lock, Minus, PackageX, PauseCircle, Percent, Plus, Printer, RotateCcw, ScanBarcode, Search, Tag, Trash2, UserRoundSearch, CheckCircle2, Wifi, WifiOff, Hash } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { useRequireAuth, LanguageToggle, ThemeToggle } from "@/components/layout/app-shell";
import { PaymentDialog } from "@/components/pos/payment-dialog";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { StatusBadge } from "@/components/shared/page";
import { categoryIcon, ProductVisual } from "@/components/shared/product-visual";
import { ReceiptBody, ReceiptDialog } from "@/components/shared/receipt";
import { Forbidden, PageSkeleton } from "@/components/shared/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { usePosActions } from "@/hooks/use-pos";
import { getErrorMessage } from "@/lib/api/errors";
import { formatDateTime, formatKhr, formatNumber, formatTime, formatUsd } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { authApi, cashSessionsApi, categoriesApi, customersApi, productsApi, salesApi, settingsApi, terminalsApi } from "@/services";
import { useAuthStore, useCan } from "@/stores/auth-store";
import { usePosStore } from "@/stores/pos-store";
import { useUiStore } from "@/stores/ui-store";
import type { DiscountType, ProductListItem, Sale, SaleLine } from "@/types";

function TerminalPicker({ onPicked }: { onPicked: () => void }) {
  const setTerminal = useUiStore((s) => s.setTerminal);
  const user = useAuthStore((s) => s.user);
  const terminals = useApiQuery(["terminals"], () => terminalsApi.list());
  const allowed = terminals.data?.filter((t) => t.status === "ACTIVE" && (!user?.branchIds.length || user.branchIds.includes(t.branchId))) ?? [];
  return (
    <main className="grid min-h-svh place-items-center p-4">
      <div className="w-full max-w-sm space-y-3 rounded-lg border bg-card p-5">
        <h1 className="text-lg font-semibold">Select this terminal</h1>
        <p className="text-sm text-muted-foreground">The POS needs a registered terminal to know its branch and stock location.</p>
        {allowed.map((t) => <Button key={t.id} variant="outline" className="h-14 w-full justify-start" onClick={() => { setTerminal(t.id); onPicked(); }}>{t.name}</Button>)}
        {terminals.data && !allowed.length ? <p className="text-sm text-destructive">No terminal is available at your branch.</p> : null}
        <Button asChild variant="ghost" className="w-full"><Link href="/dashboard"><ArrowLeft />Back office</Link></Button>
      </div>
    </main>
  );
}

const discountSchema = z.object({
  type: z.enum(["PERCENT", "AMOUNT"]),
  value: z.number({ error: "Enter a value." }).min(0, "Must not be negative."),
  reason: z.string().min(1, "A reason is required for discounts."),
});

const sessionSchema = z.object({
  usd: z.number({ error: "Enter the opening USD." }).min(0),
  khr: z.number({ error: "Enter the opening KHR." }).min(0),
  witness: z.string(),
});

const overrideSchema = z.object({ price: z.number({ error: "Enter a price." }).min(0), reason: z.string().min(1, "A reason is required for price overrides.") });

function LockScreen({ onUnlock }: { onUnlock: () => void }) {
  const terminalId = useUiStore((s) => s.terminalId) as string;
  const applyAuth = useAuthStore((s) => s.applyAuth);
  const user = useAuthStore((s) => s.user);
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const auth = await authApi.pin(pin, terminalId);
      applyAuth(auth);
      if (auth.user.id !== user?.id) usePosStore.getState().setSale(null);
      onUnlock();
    } catch (err) {
      setError(getErrorMessage(err));
      setPin("");
    }
  };
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-background/95 p-4 backdrop-blur-sm">
      <form onSubmit={(e) => void submit(e)} className="w-full max-w-xs space-y-3 rounded-lg border bg-card p-5 text-center">
        <Lock className="mx-auto size-7 text-muted-foreground" />
        <h2 className="font-semibold">Terminal locked</h2>
        <p className="text-sm text-muted-foreground">Enter a PIN to continue or switch cashier.</p>
        <Input autoFocus type="password" inputMode="numeric" value={pin} aria-label="PIN" onChange={(e) => setPin(e.target.value)} className="h-12 text-center text-xl tracking-[0.4em]" />
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <Button type="submit" className="h-12 w-full" disabled={pin.length < 4}>Unlock</Button>
      </form>
    </div>
  );
}

export function PosTerminal() {
  const ready = useRequireAuth();
  const can = useCan();
  const terminalId = useUiStore((s) => s.terminalId);
  const [, force] = useState(0);
  if (!ready) return <div className="p-6"><PageSkeleton /></div>;
  if (!can("pos.sell", "pos.hold")) return <div className="p-6"><Forbidden /></div>;
  if (!terminalId) return <TerminalPicker onPicked={() => force((n) => n + 1)} />;
  return <Terminal key={terminalId} terminalId={terminalId} />;
}

function Terminal({ terminalId }: { terminalId: string }) {
  const t = useT();
  const router = useRouter();
  const can = useCan();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const setTerminal = useUiStore((s) => s.setTerminal);
  const sale = usePosStore((s) => s.sale);
  const session = usePosStore((s) => s.session);
  const setSale = usePosStore((s) => s.setSale);
  const setSession = usePosStore((s) => s.setSession);
  const selectedLineId = usePosStore((s) => s.selectedLineId);
  const selectLine = usePosStore((s) => s.selectLine);
  const completed = usePosStore((s) => s.completed);
  const setCompleted = usePosStore((s) => s.setCompleted);
  const { apply, cancel, resume } = usePosActions();
  const { prompt } = useDialogs();

  const terminals = useApiQuery(["terminals"], () => terminalsApi.list());
  const terminal = terminals.data?.find((x) => x.id === terminalId);
  const settings = useApiQuery(["settings"], settingsApi.get);
  const products = useApiQuery(["products", "pos", terminalId], () => productsApi.list({ sellable: true, terminalId }));
  const categories = useApiQuery(["categories"], () => categoriesApi.list());
  const customers = useApiQuery(["customers"], () => customersApi.list(), { enabled: can("customers.view", "pos.sell") });
  const held = useApiQuery(["sales", "held"], () => salesApi.held());
  const recent = useApiQuery(["sales", "recent", terminalId], () => salesApi.list({ terminalId }), { enabled: can("sales.view") });

  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("fav");
  const [dialog, setDialog] = useState<null | "pay" | "qty" | "lineDiscount" | "orderDiscount" | "customer" | "override" | "held" | "recent" | "price" | "session">(null);
  const [qtyValue, setQtyValue] = useState("");
  const [customerQuery, setCustomerQuery] = useState("");
  const [reprint, setReprint] = useState<Sale | null>(null);
  const [locked, setLocked] = useState(false);
  const [online, setOnline] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);

  const selected = sale?.lines.find((l) => l.id === selectedLineId) ?? null;
  const dialogOpen = dialog !== null || completed !== null || reprint !== null || locked;

  const focusScan = useCallback(() => setTimeout(() => inputRef.current?.focus(), 30), []);

  // Restore the draft and the session after a refresh (NFR-REL-003).
  useEffect(() => {
    let live = true;
    void Promise.all([salesApi.current(), cashSessionsApi.current()]).then(([draft, current]) => {
      if (!live) return;
      setSale(draft);
      setSession(current);
      if (!current && can("cash.session.open")) setDialog("session");
    }).catch((e: unknown) => toast.error(getErrorMessage(e)));
    return () => {
      live = false;
    };
    // Runs once per terminal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terminalId]);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  // Idle lock (FR-AUTH-002).
  useEffect(() => {
    const minutes = settings.data?.posIdleLockMinutes ?? 2;
    let timer = setTimeout(() => setLocked(true), minutes * 60_000);
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(() => setLocked(true), minutes * 60_000);
    };
    const events = ["keydown", "pointerdown"] as const;
    events.forEach((e) => window.addEventListener(e, reset));
    return () => {
      clearTimeout(timer);
      events.forEach((e) => window.removeEventListener(e, reset));
    };
  }, [settings.data?.posIdleLockMinutes]);

  const addByCode = useCallback(
    async (code: string) => {
      const value = code.trim();
      if (!value) return;
      const list = products.data ?? [];
      const hit = list.find((p) => p.barcodes.some((b) => b.active && b.barcode === value));
      const bySku = list.find((p) => p.sku.toLowerCase() === value.toLowerCase());
      if (hit || !bySku) {
        await apply(() => [{ type: "add_barcode", barcode: value }]);
      } else {
        await apply(() => [{ type: "add_product", productId: bySku.id }]);
      }
      setQuery("");
    },
    [apply, products.data],
  );

  const addProduct = useCallback(
    async (product: ProductListItem) => {
      if (product.allowFraction) {
        const value = await prompt({ title: `Weight of ${product.nameEn}`, label: `Quantity (${product.unitCode})`, placeholder: "0.500", confirmLabel: "Add" });
        const quantity = Number(value);
        if (value && quantity > 0) await apply(() => [{ type: "add_product", productId: product.id, quantity }]);
      } else {
        await apply(() => [{ type: "add_product", productId: product.id }]);
      }
      focusScan();
    },
    [apply, focusScan, prompt],
  );

  // Keyboard-wedge scanner support without focusing a field (NFR-USA-003).
  useEffect(() => {
    let buffer = "";
    let last = 0;
    const handler = (e: KeyboardEvent) => {
      if (dialogOpen) return;
      const target = e.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
      const now = Date.now();
      if (now - last > 80) buffer = "";
      last = now;
      if (e.key === "Enter") {
        if (buffer.length >= 3) {
          e.preventDefault();
          void addByCode(buffer);
        }
        buffer = "";
      } else if (e.key.length === 1) {
        buffer += e.key;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [addByCode, dialogOpen]);

  const openQty = useCallback(() => {
    if (!selected) return;
    setQtyValue(String(selected.quantity));
    setDialog("qty");
  }, [selected]);

  const hold = useCallback(async () => {
    if (!sale?.lines.length) return;
    const label = await prompt({ title: "Hold this sale", label: "Label", placeholder: "Customer name or note", required: false, confirmLabel: "Hold" });
    if (label === null) return;
    const ok = await apply(() => [{ type: "hold", label }]);
    if (ok) {
      setSale(null);
      void held.refetch();
      toast.success("Sale held");
    }
    focusScan();
  }, [apply, focusScan, held, prompt, sale?.lines.length, setSale]);

  const removeSelected = useCallback(() => {
    if (selected) void apply(() => [{ type: "remove_line", lineId: selected.id }]);
  }, [apply, selected]);

  const openPay = useCallback(() => {
    if (!sale?.lines.length) return;
    if (!can("pos.sell")) {
      toast.error("Your role can build and hold sales, but not collect payment.");
      return;
    }
    if (!session) {
      setDialog("session");
      return;
    }
    setDialog("pay");
  }, [can, sale?.lines.length, session]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (dialogOpen) return;
      const actions: Record<string, () => void> = {
        F2: openQty,
        F3: () => inputRef.current?.focus(),
        F4: () => setDialog("customer"),
        F6: () => selected && setDialog("lineDiscount"),
        F7: () => setDialog("price"),
        F8: () => void hold(),
        F9: () => setDialog("held"),
        F12: openPay,
      };
      if (actions[e.key]) {
        e.preventDefault();
        actions[e.key]();
        return;
      }
      if (e.key === "Delete" && (e.target as HTMLElement).tagName !== "INPUT") {
        e.preventDefault();
        removeSelected();
      }
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && sale?.lines.length) {
        e.preventDefault();
        const index = sale.lines.findIndex((l) => l.id === selectedLineId);
        const next = e.key === "ArrowDown" ? Math.min(index + 1, sale.lines.length - 1) : Math.max(index - 1, 0);
        selectLine(sale.lines[next].id);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [dialogOpen, hold, openPay, openQty, removeSelected, sale, selectLine, selected, selectedLineId]);

  const closeDialog = () => {
    setDialog(null);
    focusScan();
  };

  const visibleProducts = useMemo(() => {
    const term = query.trim().toLowerCase();
    const list = products.data ?? [];
    if (term) return list.filter((p) => `${p.nameEn} ${p.nameKm} ${p.sku} ${p.barcodes.map((b) => b.barcode).join(" ")}`.toLowerCase().includes(term)).slice(0, 60);
    if (category === "fav") return list.filter((p) => p.isFavourite);
    if (category === "all") return list.slice(0, 80);
    return list.filter((p) => p.categoryId === category);
  }, [category, products.data, query]);

  const parentCategories = categories.data?.filter((c) => c.status === "ACTIVE" && !c.parentId) ?? [];

  const cancelSale = async () => {
    if (!sale) return;
    const reason = await prompt({ title: "Cancel this sale?", description: "The sale will not be recorded and no stock will change.", label: "Reason", confirmLabel: "Cancel sale" });
    if (reason === null) return;
    if (await cancel(reason)) toast.success("Sale cancelled");
    focusScan();
  };

  const startCompletedNew = () => {
    setCompleted(null);
    focusScan();
  };

  const openSession = useApiMutation(
    (values: z.infer<typeof sessionSchema>) => cashSessionsApi.open({ USD: values.usd, KHR: values.khr }, values.witness || undefined),
    { success: "Session opened", onSuccess: (s) => setSession(s) },
  );

  const reprintMutation = useApiMutation((id: string) => salesApi.reprint(id), { onSuccess: (s) => setReprint(s) });
  const reprintLast = () => {
    const last = recent.data?.find((s) => s.status === "FINALIZED");
    if (last) void reprintMutation.fire(last.id);
    else toast.info("No sale to reprint on this terminal yet.");
  };

  const switchCashier = () => setLocked(true);

  const filteredCustomers = useMemo(() => {
    const term = customerQuery.trim().toLowerCase();
    return (customers.data ?? []).filter((c) => !term || `${c.name} ${c.phone} ${c.code}`.toLowerCase().includes(term)).slice(0, 30);
  }, [customerQuery, customers.data]);

  return (
    <div className="flex h-svh flex-col overflow-hidden bg-background">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b bg-card px-2.5 text-sm sm:gap-3">
        <Button asChild variant="ghost" size="sm"><Link href="/dashboard" aria-label="Back office"><ArrowLeft /><span className="hidden lg:inline">{t("Back office")}</span></Link></Button>
        <span className="hidden truncate font-medium md:block">{terminal?.name}</span>
        <Badge variant="outline" className={online ? "border-success/40 text-success" : "border-destructive/40 text-destructive"}>{online ? <Wifi /> : <WifiOff />}{online ? t("Online") : t("Offline")}</Badge>
        {session ? <button type="button" onClick={() => router.push("/cashier-sessions")} className="hidden lg:block"><StatusBadge status="OPEN" className="cursor-pointer" /></button> : <Button size="sm" variant="outline" disabled={!can("cash.session.open")} onClick={() => setDialog("session")}>{t("Open session")}</Button>}
        {session ? <span className="tabular hidden text-xs text-muted-foreground lg:inline">{session.sessionNo} · {formatTime(session.openedAt)}</span> : null}
        <div className="ml-auto flex min-w-0 items-center gap-1">
          <span className="hidden max-w-36 truncate text-xs text-muted-foreground sm:block">{user?.fullName}</span>
          <Button variant="ghost" size="icon-sm" aria-label="Lock or switch cashier" onClick={switchCashier}><Lock /></Button>
          <LanguageToggle />
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={() => { setTerminal(null); }}>Change terminal</Button>
          <Button variant="ghost" size="sm" className="hidden sm:inline-flex" onClick={() => void logout().then(() => router.replace("/login"))}>{t("Sign out")}</Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 p-2.5" aria-label="Products">
          <div className="relative">
            <ScanBarcode className="pointer-events-none absolute top-3.5 left-3 size-5 text-muted-foreground" />
            <Input
              ref={inputRef}
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  if (visibleProducts.length === 1 && query && !/^\d{8,}$/.test(query.trim())) void addProduct(visibleProducts[0]).then(() => setQuery(""));
                  else void addByCode(query);
                }
              }}
              placeholder={`${t("Scan barcode or search products")} (F3)`}
              aria-label="Scan barcode or search products"
              className="h-12 pl-10 text-base"
            />
          </div>
          <div className="flex shrink-0 gap-1.5 overflow-x-auto [scrollbar-width:none]">
            {[{ id: "fav", label: t("Favourites"), Icon: Tag }, { id: "all", label: t("All"), Icon: Search }, ...parentCategories.map((c) => ({ id: c.id, label: c.nameEn, Icon: categoryIcon(c.icon) }))].map((c) => (
              <button key={c.id} type="button" aria-pressed={category === c.id} onClick={() => { setCategory(c.id); setQuery(""); focusScan(); }} className={cn("flex h-12 shrink-0 items-center gap-1.5 rounded-md border px-3 text-sm font-medium whitespace-nowrap", category === c.id && !query ? "border-primary bg-accent text-accent-foreground" : "bg-card hover:bg-muted")}>
                <c.Icon className="size-4" />{c.label}
              </button>
            ))}
          </div>
          <ScrollArea className="min-h-0 flex-1">
            {products.isLoading ? <p className="p-6 text-center text-sm text-muted-foreground">Loading products...</p> : null}
            <div className="grid grid-cols-2 gap-2 pr-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">
              {visibleProducts.map((p) => {
                const out = p.type !== "SERVICE" && p.available <= 0;
                return (
                  <button key={p.id} type="button" onClick={() => void addProduct(p)} className="flex min-h-28 min-w-0 flex-col gap-1.5 rounded-md border bg-card p-2 text-left hover:border-primary/50 focus-visible:ring-2">
                    <div className="flex items-start gap-2">
                      <ProductVisual image={p.image} icon={categories.data?.find((c) => c.id === p.categoryId)?.icon} name={p.nameEn} className="size-11 shrink-0" />
                      <span className="line-clamp-3 min-w-0 text-[13px] leading-tight font-medium">{p.nameEn}</span>
                    </div>
                    <div className="mt-auto flex items-end justify-between gap-1">
                      <span className="tabular text-sm font-semibold">{formatUsd(p.retailPrice)}</span>
                      {p.type === "SERVICE" ? <span className="text-[11px] text-muted-foreground">Service</span> : out ? <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-destructive"><PackageX className="size-3" />{t("Out of stock")}</span> : <span className="tabular text-[11px] text-muted-foreground">{formatNumber(p.available)} {p.unitCode}</span>}
                    </div>
                  </button>
                );
              })}
            </div>
            {products.data && !visibleProducts.length ? <p className="p-8 text-center text-sm text-muted-foreground">No products match. Try another name, SKU or barcode.</p> : null}
          </ScrollArea>
        </section>

        <section className="flex min-h-0 w-full shrink-0 flex-col border-t bg-card max-md:h-[55svh] md:w-[23rem] md:border-t-0 md:border-l lg:w-[28rem]" aria-label="Current sale">
          <div className="flex items-center justify-between gap-2 border-b p-2.5">
            <button type="button" onClick={() => setDialog("customer")} className="flex h-12 min-w-0 flex-1 items-center gap-2 rounded-md border px-2.5 text-left hover:bg-muted">
              <CircleUserRound className="size-5 shrink-0 text-muted-foreground" />
              <span className="truncate text-sm font-medium">{sale?.customerName ?? t("Walk-in customer")}</span>
              <kbd className="ml-auto text-[10px] text-muted-foreground">F4</kbd>
            </button>
            <Button variant="outline" className="h-12 min-w-12 px-2.5" aria-label="Held sales" onClick={() => setDialog("held")}><PauseCircle />{held.data?.length ? <span className="tabular text-xs">{held.data.length}</span> : null}</Button>
            <Button variant="outline" className="h-12 min-w-12 px-2.5" aria-label="Recent sales" disabled={!can("sales.view")} onClick={() => setDialog("recent")}><History /></Button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {!sale?.lines.length ? (
              <div className="flex h-full flex-col items-center justify-center gap-1.5 p-6 text-center text-muted-foreground">
                <ScanBarcode className="size-9 opacity-50" />
                <p className="text-sm">{t("Scan an item to start")}</p>
              </div>
            ) : (
              <ul>
                {sale.lines.map((line, index) => <CartLine key={line.id} line={line} index={index} selected={line.id === selectedLineId} onSelect={() => selectLine(line.id)} onQty={(q) => void apply(() => [{ type: "set_quantity", lineId: line.id, quantity: q }])} onRemove={() => void apply(() => [{ type: "remove_line", lineId: line.id }])} />)}
              </ul>
            )}
          </div>

          <div className="border-t p-2.5">
            <dl className="tabular space-y-0.5 text-sm">
              <div className="flex justify-between"><dt className="text-muted-foreground">{t("Subtotal")}</dt><dd>{formatUsd(sale?.subtotal)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">{t("Discount")}</dt><dd>-{formatUsd(sale?.discountTotal)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">{t("Tax")}</dt><dd>{formatUsd(sale?.taxTotal)}</dd></div>
              <div className="flex items-baseline justify-between pt-1"><dt className="font-semibold">{t("Total")}</dt><dd className="text-2xl font-bold">{formatUsd(sale?.grandTotal)}</dd></div>
              <div className="flex justify-end text-muted-foreground"><dd>{formatKhr(sale?.grandTotalKhr)}</dd></div>
            </dl>
            <div className="mt-2 grid grid-cols-4 gap-1.5">
              <ActionButton icon={Hash} label={t("Qty")} hint="F2" disabled={!selected} onClick={openQty} />
              <ActionButton icon={Percent} label={t("Discount")} hint="F6" disabled={!selected} onClick={() => setDialog("lineDiscount")} />
              <ActionButton icon={PauseCircle} label={t("Hold")} hint="F8" disabled={!sale?.lines.length || !can("pos.hold")} onClick={() => void hold()} />
              <ActionButton icon={Ban} label={t("Cancel")} disabled={!sale?.lines.length} onClick={() => void cancelSale()} />
              <ActionButton icon={Tag} label="Override" disabled={!selected} onClick={() => setDialog("override")} />
              <ActionButton icon={Percent} label="Order disc." disabled={!sale?.lines.length} onClick={() => setDialog("orderDiscount")} />
              <ActionButton icon={Search} label={t("Price check")} hint="F7" onClick={() => setDialog("price")} />
              <ActionButton icon={RotateCcw} label={t("Return")} disabled={!can("returns.create")} onClick={() => router.push("/sales/returns?new=1")} />
            </div>
            <div className="mt-1.5 flex gap-1.5">
              <Button variant="outline" className="h-16 shrink-0 flex-col gap-0.5 px-3 text-xs" disabled={!can("sales.view")} onClick={reprintLast}><Printer />{t("Reprint last")}</Button>
              <Button className="h-16 flex-1 text-lg font-semibold" disabled={!sale?.lines.length} onClick={openPay}>{t("Pay")} {sale?.lines.length ? formatUsd(sale.balance) : ""}<kbd className="ml-1 text-xs opacity-70">F12</kbd></Button>
            </div>
          </div>
        </section>
      </div>

      {/* Mounted per use so every payment starts from a clean form. */}
      {dialog === "pay" ? <PaymentDialog open onOpenChange={(open) => (open ? setDialog("pay") : closeDialog())} /> : null}

      <Dialog open={dialog === "qty"} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent className="sm:max-w-xs">
          <DialogHeader><DialogTitle>{t("Qty")}</DialogTitle><DialogDescription>{selected?.nameEn}</DialogDescription></DialogHeader>
          <form onSubmit={(e) => { e.preventDefault(); const q = Number(qtyValue); if (selected && q > 0) { void apply(() => [{ type: "set_quantity", lineId: selected.id, quantity: q }]); closeDialog(); } }} className="space-y-3">
            <Input autoFocus inputMode="decimal" value={qtyValue} onChange={(e) => setQtyValue(e.target.value)} onFocus={(e) => e.target.select()} aria-label="Quantity" className="tabular h-14 text-center text-2xl" />
            <div className="grid grid-cols-3 gap-1.5">
              {["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "C"].map((k) => <Button key={k} type="button" variant="secondary" className="h-12 text-lg" onClick={() => setQtyValue((v) => (k === "C" ? "" : `${v}${k}`))}>{k}</Button>)}
            </div>
            <Button type="submit" className="h-12 w-full">{t("Confirm")}</Button>
          </form>
        </DialogContent>
      </Dialog>

      <FormDialog
        open={dialog === "lineDiscount" || dialog === "orderDiscount"}
        onOpenChange={(open) => !open && closeDialog()}
        title={dialog === "orderDiscount" ? "Order discount" : "Line discount"}
        description={dialog === "orderDiscount" ? "Applied across the whole sale. Enter 0 to remove." : `${selected?.nameEn ?? ""}. Enter 0 to remove.`}
        schema={discountSchema}
        defaultValues={{ type: "PERCENT" as DiscountType, value: 0, reason: "" }}
        fields={[
          { name: "type", label: "Type", type: "select", options: [{ value: "PERCENT", label: "Percent" }, { value: "AMOUNT", label: "Amount (USD)" }] },
          { name: "value", label: "Value", type: "number", required: true },
          { name: "reason", label: "Reason", full: true, required: true, placeholder: "e.g. Damaged packaging" },
        ]}
        submitLabel="Apply"
        onSubmit={async (values) => {
          const base = dialog === "orderDiscount" ? (sale?.subtotal ?? 0) : (selected?.grossAmount ?? 0);
          const pct = values.type === "PERCENT" ? values.value : base ? (values.value / base) * 100 : 0;
          const lineId = selected?.id ?? "";
          await apply(() => [dialog === "orderDiscount" ? { type: "order_discount", discountType: values.type, value: values.value, reason: values.reason } : { type: "line_discount", lineId, discountType: values.type, value: values.value, reason: values.reason }], pct);
        }}
      />

      <FormDialog
        open={dialog === "override"}
        onOpenChange={(open) => !open && closeDialog()}
        title="Override price"
        description={selected ? `${selected.nameEn}: list price ${formatUsd(selected.listPrice)}` : undefined}
        schema={overrideSchema}
        defaultValues={{ price: selected?.unitPrice ?? 0, reason: "" }}
        fields={[{ name: "price", label: "New unit price (USD)", type: "number", required: true }, { name: "reason", label: "Reason", full: true, required: true }]}
        submitLabel="Apply override"
        onSubmit={async (values) => {
          const lineId = selected?.id ?? "";
          await apply(() => [{ type: "override_price", lineId, price: values.price, reason: values.reason }]);
        }}
      />

      <FormDialog
        open={dialog === "session"}
        onOpenChange={(open) => !open && closeDialog()}
        title={t("Open session")}
        description={`Count the opening float for ${terminal?.name ?? "this terminal"}.`}
        schema={sessionSchema}
        defaultValues={{ usd: 50, khr: 100000, witness: "" }}
        fields={[{ name: "usd", label: "Opening cash (USD)", type: "number", required: true }, { name: "khr", label: "Opening cash (KHR)", type: "number", required: true }, { name: "witness", label: "Witness (optional)", full: true }]}
        submitLabel={t("Open session")}
        onSubmit={(values) => openSession.run(values)}
      />

      <Dialog open={dialog === "customer"} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>{t("Customer")}</DialogTitle><DialogDescription>Search by phone, code or name. Leave as walk-in if none.</DialogDescription></DialogHeader>
          <Input autoFocus value={customerQuery} onChange={(e) => setCustomerQuery(e.target.value)} placeholder="Phone, code or name" aria-label="Search customers" className="h-12" />
          <Button variant="outline" className="h-12 justify-start" onClick={() => { void apply(() => [{ type: "set_customer", customerId: null }]); closeDialog(); }}>{t("Walk-in customer")}</Button>
          <div className="max-h-72 space-y-1 overflow-y-auto">
            {filteredCustomers.map((c) => (
              <button key={c.id} type="button" onClick={() => { void apply(() => [{ type: "set_customer", customerId: c.id }]); closeDialog(); }} className="flex min-h-12 w-full items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-left text-sm hover:bg-muted">
                <span className="min-w-0"><span className="block truncate font-medium">{c.name}</span><span className="text-xs text-muted-foreground">{c.phone} · {c.groupName}</span></span>
                <span className="tabular shrink-0 text-xs text-muted-foreground">{c.loyaltyPoints} pts</span>
              </button>
            ))}
          </div>
          {can("customers.manage") ? <Button variant="ghost" asChild><Link href="/customers?new=1"><UserRoundSearch />Create customer in back office</Link></Button> : null}
        </DialogContent>
      </Dialog>

      <Dialog open={dialog === "price"} onOpenChange={(open) => !open && closeDialog()}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader><DialogTitle>{t("Price check")}</DialogTitle><DialogDescription>Search without adding to the sale.</DialogDescription></DialogHeader>
          <PriceCheck products={products.data ?? []} />
        </DialogContent>
      </Dialog>

      <Sheet open={dialog === "held"} onOpenChange={(open) => !open && closeDialog()}>
        <SheetContent className="w-full gap-0 sm:max-w-md">
          <SheetHeader className="border-b"><SheetTitle>{t("Held sales")}</SheetTitle><SheetDescription>Resume re-prices each sale at current prices.</SheetDescription></SheetHeader>
          <div className="space-y-2 overflow-y-auto p-3">
            {(held.data ?? []).map((h) => (
              <div key={h.id} className="rounded-md border p-2.5">
                <div className="flex items-center justify-between gap-2"><span className="truncate font-medium">{h.holdLabel}</span><span className="tabular text-sm font-semibold">{formatUsd(h.grandTotal)}</span></div>
                <p className="text-xs text-muted-foreground">{h.lines.length} item{h.lines.length === 1 ? "" : "s"} · {h.cashierName} · {formatDateTime(h.createdAt)}</p>
                <Button size="sm" className="mt-2 h-12 w-full" disabled={Boolean(sale?.lines.length)} onClick={() => { void resume(h.id).then(() => held.refetch()); closeDialog(); }}>{sale?.lines.length ? "Finish the current sale first" : "Resume"}</Button>
              </div>
            ))}
            {held.data && !held.data.length ? <p className="p-6 text-center text-sm text-muted-foreground">No held sales</p> : null}
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={dialog === "recent"} onOpenChange={(open) => !open && closeDialog()}>
        <SheetContent className="w-full gap-0 sm:max-w-md">
          <SheetHeader className="border-b"><SheetTitle>Recent sales</SheetTitle><SheetDescription>{terminal?.name}</SheetDescription></SheetHeader>
          <div className="space-y-2 overflow-y-auto p-3">
            {(recent.data ?? []).slice(0, 25).map((s) => (
              <div key={s.id} className="rounded-md border p-2.5">
                <div className="flex items-center justify-between gap-2"><span className="truncate font-mono text-xs">{s.receiptNo ?? "Not finalized"}</span><StatusBadge status={s.status} /></div>
                <div className="flex items-center justify-between"><span className="text-xs text-muted-foreground">{formatDateTime(s.finalizedAt ?? s.createdAt)}</span><span className="tabular text-sm font-semibold">{formatUsd(s.grandTotal)}</span></div>
                {s.status === "FINALIZED" ? (
                  <div className="mt-2 grid grid-cols-2 gap-1.5">
                    <Button size="sm" variant="outline" onClick={() => void reprintMutation.fire(s.id)}><Printer />Reprint</Button>
                    <Button size="sm" variant="outline" disabled={!can("returns.create")} onClick={() => router.push(`/sales/returns?receipt=${s.receiptNo}`)}><RotateCcw />Return</Button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </SheetContent>
      </Sheet>

      <Dialog open={completed !== null} onOpenChange={(open) => !open && startCompletedNew()}>
        <DialogContent className="max-h-[94vh] overflow-y-auto sm:max-w-md">
          <DialogHeader className="items-center text-center">
            <CheckCircle2 className="size-10 text-success" />
            <DialogTitle>Sale complete</DialogTitle>
            <DialogDescription>{completed?.receiptNo}</DialogDescription>
          </DialogHeader>
          {completed ? <CompletedSummary sale={completed} /> : null}
          <DialogFooter className="sm:flex-col sm:space-x-0">
            <Button className="h-14 w-full text-base" autoFocus onClick={startCompletedNew}>{t("New sale")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ReceiptDialog sale={reprint} copy onClose={() => setReprint(null)} />
      {locked ? <LockScreen onUnlock={() => { setLocked(false); focusScan(); }} /> : null}
      <span className="sr-only" aria-live="polite">{sale ? `${sale.lines.length} items, total ${formatUsd(sale.grandTotal)}` : ""}</span>
    </div>
  );
}

function ActionButton({ icon: Icon, label, hint, onClick, disabled }: { icon: typeof Hash; label: string; hint?: string; onClick: () => void; disabled?: boolean }) {
  return (
    <Button type="button" variant="outline" className="h-12 min-w-0 flex-col gap-0 px-1 text-[11px] leading-tight [&_svg]:size-4" disabled={disabled} onClick={onClick}>
      <Icon />
      <span className="max-w-full truncate">{label}{hint ? ` ${hint}` : ""}</span>
    </Button>
  );
}

function CartLine({ line, index, selected, onSelect, onQty, onRemove }: { line: SaleLine; index: number; selected: boolean; onSelect: () => void; onQty: (q: number) => void; onRemove: () => void }) {
  const short = !line.isService && line.quantityBase > line.available;
  const step = line.allowFraction ? 0.1 : 1;
  return (
    <li onClick={onSelect} className={cn("cursor-pointer border-b px-2.5 py-2", selected && "bg-accent/60")}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium"><span className="tabular mr-1 text-xs text-muted-foreground">{index + 1}.</span>{line.nameEn}</p>
          <p className="truncate text-xs text-muted-foreground">{line.nameKm}</p>
        </div>
        <span className="tabular shrink-0 text-sm font-semibold">{formatUsd(line.lineTotal)}</span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <div className="flex items-center rounded-md border">
          <Button type="button" variant="ghost" size="icon" className="size-10 rounded-r-none" aria-label={`Decrease ${line.nameEn}`} onClick={(e) => { e.stopPropagation(); if (line.quantity - step > 0) onQty(Math.round((line.quantity - step) * 1000) / 1000); else onRemove(); }}><Minus /></Button>
          <span className="tabular w-11 text-center text-sm font-medium">{formatNumber(line.quantity)}</span>
          <Button type="button" variant="ghost" size="icon" className="size-10 rounded-l-none" aria-label={`Increase ${line.nameEn}`} onClick={(e) => { e.stopPropagation(); onQty(Math.round((line.quantity + step) * 1000) / 1000); }}><Plus /></Button>
        </div>
        <span className="tabular min-w-0 truncate text-xs text-muted-foreground">{line.unitCode} @ {formatUsd(line.unitPrice)}</span>
        <Button type="button" variant="ghost" size="icon" className="ml-auto size-10 text-muted-foreground" aria-label={`Remove ${line.nameEn}`} onClick={(e) => { e.stopPropagation(); onRemove(); }}><Trash2 /></Button>
      </div>
      <div className="flex flex-wrap gap-x-2 text-[11px]">
        {line.discountAmount > 0 ? <span className="text-success">Discount -{formatUsd(line.discountAmount)}</span> : null}
        {line.priceSource !== "STANDARD" ? <span className="text-info">{line.priceExplanation}</span> : null}
        {line.priceChanged ? <span className="font-medium text-warning">Price changed</span> : null}
        {short ? <span className="font-medium text-destructive">Only {formatNumber(line.available)} available at this counter</span> : null}
      </div>
    </li>
  );
}

function PriceCheck({ products }: { products: ProductListItem[] }) {
  const [term, setTerm] = useState("");
  const value = term.trim().toLowerCase();
  const rows = value.length >= 2 ? products.filter((p) => `${p.nameEn} ${p.sku} ${p.barcodes.map((b) => b.barcode).join(" ")}`.toLowerCase().includes(value)).slice(0, 12) : [];
  return (
    <div className="space-y-2">
      <Input autoFocus className="h-12" value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Scan or type at least 2 characters" aria-label="Search price" />
      <ul className="max-h-72 divide-y overflow-y-auto">
        {rows.map((p) => (
          <li key={p.id} className="flex items-center justify-between gap-2 py-2 text-sm">
            <span className="min-w-0"><span className="block truncate font-medium">{p.nameEn}</span><span className="tabular text-xs text-muted-foreground">{formatNumber(p.available)} {p.unitCode} available</span></span>
            <span className="tabular shrink-0 font-semibold">{formatUsd(p.retailPrice)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CompletedSummary({ sale }: { sale: Sale }) {
  const ref = useRef<HTMLDivElement>(null);
  const cash = sale.payments.find((p) => p.method === "CASH" && p.changeAmount > 0);
  const paid = sale.payments.reduce((s, p) => s + (p.status === "COMPLETED" ? p.amountApplied : 0), 0);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-md border p-2"><p className="text-xs text-muted-foreground">Total</p><p className="tabular font-semibold">{formatUsd(sale.grandTotal)}</p></div>
        <div className="rounded-md border p-2"><p className="text-xs text-muted-foreground">Paid</p><p className="tabular font-semibold">{formatUsd(paid)}</p></div>
        <div className="rounded-md border p-2"><p className="text-xs text-muted-foreground">Status</p><p className="font-semibold">Paid</p></div>
      </div>
      {cash ? <div className="rounded-md bg-accent p-3 text-center"><p className="text-sm">Change</p><p className="tabular text-3xl font-bold">{cash.changeCurrency === "KHR" ? formatKhr(cash.changeAmount) : formatUsd(cash.changeAmount)}</p></div> : null}
      <div ref={ref} className="max-h-56 overflow-y-auto rounded-md border p-3"><ReceiptBody sale={sale} copy={false} /></div>
      <Button variant="outline" className="h-12 w-full" onClick={async () => { const { printElement } = await import("@/lib/export"); printElement(ref.current, "receipt-80"); }}><Printer />Print receipt</Button>
    </div>
  );
}
