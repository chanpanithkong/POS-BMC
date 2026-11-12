"use client";

import { AlertTriangle, CheckCircle2, ChevronRight, Banknote, MonitorSmartphone, ShoppingBag, Clock } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { RankBars, TrendChart } from "@/components/shared/charts";
import { KpiCard, PageHeader, RequirePermission, StatCard, StatusBadge } from "@/components/shared/page";
import { ErrorState, PageSkeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApiQuery } from "@/hooks/use-api";
import { exportCsv } from "@/lib/export";
import { addDaysIso, formatDateTime, formatNumber, formatUsd, titleCase, todayIso } from "@/lib/format";
import { dashboardApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";
import type { ReactNode } from "react";
import type { DashboardData } from "@/types";

type Preset = "today" | "yesterday" | "week" | "month" | "custom";

function rangeFor(preset: Preset) {
  const today = todayIso();
  if (preset === "yesterday") {
    const y = addDaysIso(today, -1);
    return { from: y, to: y };
  }
  if (preset === "week") return { from: addDaysIso(today, -6), to: today };
  if (preset === "month") return { from: addDaysIso(today, -29), to: today };
  return { from: today, to: today };
}

function Panel({ title, action, children, className }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <Card className={`min-w-0 gap-2 rounded-lg p-3.5 shadow-none ${className ?? ""}`}>
      <div className="flex items-center justify-between gap-2"><h2 className="text-sm font-medium">{title}</h2>{action}</div>
      {children}
    </Card>
  );
}

const NoData = ({ text = "No sales in this period" }: { text?: string }) => <p className="py-8 text-center text-sm text-muted-foreground">{text}</p>;

function DashboardBody({ data, showCost }: { data: DashboardData; showCost: boolean }) {
  const isSalesView = data.variant === "OWNER" || data.variant === "MANAGER" || data.variant === "BASIC";
  const trendSeries = showCost && data.trend.some((t) => t.grossProfit !== undefined) && data.variant === "OWNER" ? [{ key: "netSales", label: "Net sales" }, { key: "grossProfit", label: "Gross profit" }] : [{ key: "netSales", label: "Net sales" }];
  return (
    <div className="space-y-3">
      {data.cashier ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Current shift" value={data.cashier.shift} hint={<StatusBadge status={data.cashier.status} />} icon={Clock} />
          <StatCard label="Assigned terminal" value={<span className="text-base">{data.cashier.terminal}</span>} icon={MonitorSmartphone} />
          <StatCard label="Sales completed" value={formatNumber(data.cashier.salesCompleted)} hint={`${data.cashier.pending} pending`} icon={ShoppingBag} />
          <StatCard label="Cash received" value={formatUsd(data.cashier.cashReceived)} hint="This session, net of change" icon={Banknote} />
        </div>
      ) : null}
      {data.kpis.length ? <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-5">{data.kpis.map((kpi) => <KpiCard key={kpi.key} kpi={kpi} />)}</div> : null}
      {isSalesView ? (
        <div className="grid gap-3 xl:grid-cols-3">
          <Panel title="Sales trend" className="xl:col-span-2">{data.trend.length ? <TrendChart data={data.trend} xKey="date" series={trendSeries} /> : <NoData />}</Panel>
          <Panel title="Summaries">
            <div className="divide-y">
              {data.summaries.map((s) => (
                <div key={s.label} className="flex items-center justify-between py-2 text-sm">
                  <span className="text-muted-foreground">{s.label}</span>
                  <span className="text-right">
                    <span className="tabular block font-semibold">{formatUsd(s.netSales)}</span>
                    <span className="tabular block text-xs text-muted-foreground">{s.transactions} sales{s.grossProfit !== undefined ? ` · GP ${formatUsd(s.grossProfit)}` : ""}</span>
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      ) : null}
      {isSalesView ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <Panel title="Sales by category">{data.byCategory.length ? <RankBars data={data.byCategory} nameKey="name" valueKey="netSales" label="Net sales" /> : <NoData />}</Panel>
          <Panel title="Payment methods">{data.byPayment.length ? <RankBars data={data.byPayment} nameKey="name" valueKey="amount" label="Received" /> : <NoData />}</Panel>
          {data.variant === "MANAGER" ? (
            <Panel title="Sales by cashier">{data.byCashier.length ? <RankBars data={data.byCashier} nameKey="name" valueKey="netSales" label="Net sales" /> : <NoData />}</Panel>
          ) : (
            <Panel title="Branch comparison">{data.branchComparison.length ? <RankBars data={data.branchComparison} nameKey="name" valueKey="netSales" label="Net sales" /> : <NoData />}</Panel>
          )}
        </div>
      ) : null}
      <div className="grid gap-3 xl:grid-cols-2">
        {isSalesView ? (
          <Panel title="Top-selling products" action={<Button asChild variant="link" size="xs"><Link href="/reports/RPT-03">Report</Link></Button>}>
            {data.topProducts.length ? (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader><TableRow><TableHead className="h-8 w-8">#</TableHead><TableHead className="h-8">Product</TableHead><TableHead className="h-8 text-right">Qty</TableHead><TableHead className="h-8 text-right">Net sales</TableHead>{showCost ? <TableHead className="h-8 text-right">Gross profit</TableHead> : null}</TableRow></TableHeader>
                  <TableBody>{data.topProducts.map((p) => <TableRow key={p.productId}><TableCell className="tabular py-1.5">{p.rank}</TableCell><TableCell className="max-w-48 truncate py-1.5"><Link className="hover:underline" href={`/products/${p.productId}`}>{p.name}</Link></TableCell><TableCell className="tabular py-1.5 text-right">{formatNumber(p.quantity)}</TableCell><TableCell className="tabular py-1.5 text-right">{formatUsd(p.netSales)}</TableCell>{showCost ? <TableCell className="tabular py-1.5 text-right">{formatUsd(p.grossProfit)}</TableCell> : null}</TableRow>)}</TableBody>
                </Table>
              </div>
            ) : <NoData />}
          </Panel>
        ) : null}
        <Panel title="Recent transactions" action={<Button asChild variant="link" size="xs"><Link href="/sales">All sales</Link></Button>}>
          {data.recentTransactions.length ? (
            <ul className="divide-y">
              {data.recentTransactions.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-2 py-1.5 text-sm">
                  <span className="min-w-0"><span className="block truncate font-mono text-xs">{s.receiptNo}</span><span className="block truncate text-xs text-muted-foreground">{formatDateTime(s.at)} · {s.customer}</span></span>
                  <span className="flex shrink-0 items-center gap-2"><StatusBadge status={s.paymentStatus} /><span className="tabular font-medium">{formatUsd(s.total)}</span></span>
                </li>
              ))}
            </ul>
          ) : <NoData text="No recent transactions" />}
        </Panel>
        <Panel title="Stock alerts" action={<Button asChild variant="link" size="xs"><Link href="/inventory/alerts">All alerts</Link></Button>}>
          {data.alerts.length ? (
            <ul className="divide-y">{data.alerts.map((a) => <li key={a.id} className="flex items-start gap-2 py-1.5 text-sm"><AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" aria-hidden /><span className="min-w-0"><span className="font-medium">{titleCase(a.type)}</span><span className="block truncate text-xs text-muted-foreground">{a.message}</span></span></li>)}</ul>
          ) : <NoData text="No open alerts" />}
        </Panel>
        {data.approvals.length || data.variant === "MANAGER" || data.variant === "OWNER" ? (
          <Panel title="Pending approvals">
            {data.approvals.length ? (
              <ul className="divide-y">{data.approvals.slice(0, 8).map((a) => <li key={a.id}><Link href={a.href} className="flex items-center justify-between gap-2 py-1.5 text-sm hover:underline"><span className="min-w-0 truncate"><span className="text-muted-foreground">{a.kind}:</span> {a.label}</span><ChevronRight className="size-3.5 shrink-0 text-muted-foreground" /></Link></li>)}</ul>
            ) : <p className="flex items-center justify-center gap-1.5 py-8 text-sm text-muted-foreground"><CheckCircle2 className="size-4" />Nothing waiting for you</p>}
          </Panel>
        ) : null}
        {data.variant === "OWNER" ? (
          <Panel title="Slow-moving products">
            <ul className="divide-y">{data.slowProducts.map((p) => <li key={p.productId} className="flex items-center justify-between gap-2 py-1.5 text-sm"><span className="min-w-0 truncate">{p.name}</span><span className="tabular shrink-0 text-xs text-muted-foreground">{formatNumber(p.soldQty)} sold · {formatNumber(p.onHand)} on hand</span></li>)}</ul>
          </Panel>
        ) : null}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const branchId = useUiStore((s) => s.branchId);
  const can = useCan();
  const [preset, setPreset] = useState<Preset>("week");
  const [custom, setCustom] = useState(() => rangeFor("week"));
  const range = useMemo(() => (preset === "custom" ? custom : rangeFor(preset)), [custom, preset]);
  const query = useApiQuery(["dashboard", branchId, range], () => dashboardApi.get({ branchId, dateFrom: range.from, dateTo: range.to }));

  const exportKpis = () => {
    if (!query.data) return;
    exportCsv("dashboard-kpis", [{ header: "KPI", key: "label" }, { header: "Value", key: "value" }, { header: "Previous", key: "previous" }], query.data.kpis.map((k) => ({ label: k.label, value: k.value, previous: k.previous })));
  };

  return (
    <RequirePermission anyOf={["dashboard.view"]}>
      <PageHeader
        title="Dashboard"
        actions={
          <>
            <Select value={preset} onValueChange={(v) => setPreset(v as Preset)}>
              <SelectTrigger size="sm" className="w-36" aria-label="Date range"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="today">Today</SelectItem>
                <SelectItem value="yesterday">Yesterday</SelectItem>
                <SelectItem value="week">Last 7 days</SelectItem>
                <SelectItem value="month">Last 30 days</SelectItem>
                <SelectItem value="custom">Custom</SelectItem>
              </SelectContent>
            </Select>
            {preset === "custom" ? (
              <>
                <Input type="date" aria-label="From" value={custom.from} max={custom.to} onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))} className="h-8 w-36" />
                <Input type="date" aria-label="To" value={custom.to} min={custom.from} onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))} className="h-8 w-36" />
              </>
            ) : null}
            {can("reports.export") ? <Button variant="outline" size="sm" disabled={!query.data?.kpis.length} onClick={exportKpis}>Export</Button> : null}
          </>
        }
      />
      {query.error ? <Card className="rounded-lg shadow-none"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Card> : query.data ? <DashboardBody data={query.data} showCost={can("costs.view")} /> : <PageSkeleton />}
    </RequirePermission>
  );
}
