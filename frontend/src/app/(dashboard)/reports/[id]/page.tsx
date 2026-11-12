"use client";

import { CheckCircle2, Download, FileSpreadsheet, Printer, XCircle } from "lucide-react";
import { useParams, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { RankBars, TrendChart } from "@/components/shared/charts";
import { type Column, DataTable } from "@/components/shared/data-table";
import { PageHeader } from "@/components/shared/page";
import { ErrorState, PageSkeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useApiQuery } from "@/hooks/use-api";
import { useBranchOptions, useCategoryOptions, useSupplierOptions, useWarehouseOptions } from "@/hooks/use-lookups";
import { exportCsv, exportXlsx, printTable } from "@/lib/export";
import { addDaysIso, formatDate, formatDateTime, formatNumber, formatPercent, formatUsd, todayIso } from "@/lib/format";
import { exportsApi, reportsApi, terminalsApi, usersApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { ListParams, ReportColumn, ReportDefinition, ReportFilterKey, ReportResult, ReportRow } from "@/types";

function formatCell(type: ReportColumn["type"], value: ReportRow[string]) {
  if (value === null || value === undefined || value === "") return "—";
  if (type === "money") return formatUsd(Number(value));
  if (type === "number") return formatNumber(Number(value));
  if (type === "percent") return formatPercent(Number(value));
  if (type === "date") return formatDate(String(value));
  if (type === "datetime") return formatDateTime(String(value));
  return String(value);
}

function Filters({ definition, draft, setDraft }: { definition: ReportDefinition; draft: ListParams; setDraft: (update: (d: ListParams) => ListParams) => void }) {
  const can = useCan();
  const branches = useBranchOptions();
  const warehouses = useWarehouseOptions();
  const categories = useCategoryOptions();
  const suppliers = useSupplierOptions();
  const terminals = useApiQuery(["terminals"], () => terminalsApi.list(), { enabled: definition.filters.includes("terminal") });
  const users = useApiQuery(["users"], () => usersApi.list(), { enabled: definition.filters.includes("cashier") && can("users.view") });
  const set = (key: string, value: string) => setDraft((d) => ({ ...d, [key]: value === "__all" ? undefined : value }));
  const select = (key: string, label: string, options: { value: string; label: string }[]) => (
    <div key={key} className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Select value={String(draft[key] ?? "__all")} onValueChange={(v) => set(key, v)}>
        <SelectTrigger size="sm" className="w-full lg:w-40" aria-label={label}><SelectValue /></SelectTrigger>
        <SelectContent><SelectItem value="__all">All</SelectItem>{options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
      </Select>
    </div>
  );
  const map: Record<ReportFilterKey, () => React.ReactNode> = {
    dateRange: () => (
      <div key="range" className="flex gap-2">
        <div className="space-y-1"><Label htmlFor="rf" className="text-xs">From</Label><Input id="rf" type="date" className="h-8" value={String(draft.dateFrom ?? "")} onChange={(e) => set("dateFrom", e.target.value)} /></div>
        <div className="space-y-1"><Label htmlFor="rt" className="text-xs">To</Label><Input id="rt" type="date" className="h-8" value={String(draft.dateTo ?? "")} onChange={(e) => set("dateTo", e.target.value)} /></div>
      </div>
    ),
    asOf: () => <div key="asof" className="space-y-1"><Label htmlFor="ra" className="text-xs">As of (blank = now)</Label><Input id="ra" type="date" className="h-8" value={String(draft.asOf ?? "")} onChange={(e) => set("asOf", e.target.value)} /></div>,
    month: () => null,
    branch: () => select("branchId", "Branch", branches),
    warehouse: () => select("warehouseId", "Warehouse", warehouses),
    category: () => select("categoryId", "Category", categories),
    terminal: () => select("terminalId", "Terminal", (terminals.data ?? []).map((t) => ({ value: t.id, label: t.name }))),
    cashier: () => select("cashierId", "Cashier", (users.data ?? []).map((u) => ({ value: u.id, label: u.fullName }))),
    paymentMethod: () => select("paymentMethod", "Payment method", ["CASH", "CARD", "QR", "BANK_TRANSFER", "STORE_CREDIT"].map((value) => ({ value, label: value.replace("_", " ") }))),
    supplier: () => select("supplierId", "Supplier", suppliers),
  };
  return <>{definition.filters.map((f) => map[f]())}</>;
}

function ReportBody({ result }: { result: ReportResult }) {
  const columns = useMemo<Column<ReportRow & { __i: number }>[]>(() => result.columns.map((c) => ({ id: c.key, header: c.label, value: (r) => r[c.key], cell: (r) => formatCell(c.type, r[c.key]), align: ["money", "number", "percent"].includes(c.type) ? "right" : undefined })), [result.columns]);
  const rows = useMemo(() => result.rows.map((r, i) => ({ ...r, __i: i })), [result.rows]);
  const chart = result.chart;
  const firstSeries = chart?.series[0];
  return (
    <div className="space-y-3">
      {chart && firstSeries && result.rows.length > 1 ? (
        <Card className="gap-1 rounded-lg p-3.5 shadow-none">
          {chart.type === "line" ? <TrendChart data={[...result.rows].reverse().sort((a, b) => String(a[chart.xKey]).localeCompare(String(b[chart.xKey])))} xKey={chart.xKey} series={chart.series} /> : <RankBars data={result.rows} nameKey={chart.xKey} valueKey={firstSeries.key} label={firstSeries.label} />}
        </Card>
      ) : null}
      {result.totals ? (
        <div className="flex flex-wrap gap-x-5 gap-y-1 rounded-lg border bg-card px-3.5 py-2 text-sm">
          {result.columns.filter((c) => result.totals?.[c.key] !== undefined && ["money", "number"].includes(c.type)).map((c) => <span key={c.key}><span className="text-muted-foreground">{c.label}: </span><span className="tabular font-semibold">{formatCell(c.type, result.totals?.[c.key] ?? 0)}</span></span>)}
        </div>
      ) : null}
      {result.checks.length ? (
        <Card className="gap-1 rounded-lg p-3.5 shadow-none">
          <h2 className="text-sm font-medium">Reconciliation checks</h2>
          {result.checks.map((c) => <p key={c.label} className="flex flex-wrap items-center gap-1.5 text-sm">{c.passed ? <CheckCircle2 className="size-4 text-success" /> : <XCircle className="size-4 text-destructive" />}<span>{c.label}</span><span className="tabular text-xs text-muted-foreground">expected {formatNumber(c.expected)}, actual {formatNumber(c.actual)}</span></p>)}
        </Card>
      ) : null}
      <DataTable data={rows} columns={columns} getRowId={(r) => String(r.__i)} searchPlaceholder="Search this report" emptyTitle="No data for these filters" />
    </div>
  );
}

export default function ReportPage() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const can = useCan();
  const catalog = useApiQuery(["reports"], reportsApi.catalog);
  const definition = catalog.data?.find((r) => r.id === id);
  const [draft, setDraft] = useState<ListParams>(() => ({ dateFrom: params.get("dateFrom") ?? addDaysIso(todayIso(), -29), dateTo: params.get("dateTo") ?? todayIso() }));
  const [applied, setApplied] = useState<ListParams>(draft);
  const query = useApiQuery(["report", id, applied], () => reportsApi.run(id, applied));

  const result = query.data;
  const exportRows = () => result?.rows.map((r) => Object.fromEntries(result.columns.map((c) => [c.key, r[c.key]]))) ?? [];
  const cols = result?.columns.map((c) => ({ header: c.label, key: c.key })) ?? [];
  const audit = (format: string) => void exportsApi.audit(`${id}`, format, result?.rows.length ?? 0).catch(() => undefined);
  const basis = result ? `${result.basis} Filters: ${Object.entries(applied).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join(", ") || "none"}. Generated ${formatDateTime(result.generatedAt)} by ${result.generatedBy}.` : "";

  return (
    <>
      <PageHeader title={definition ? `${definition.id} ${definition.name}` : id} description={definition?.purpose} actions={result && can("reports.export") ? (
        <>
          <Button variant="outline" size="sm" onClick={() => { exportXlsx(id, cols, exportRows()); audit("xlsx"); }}><FileSpreadsheet />Excel</Button>
          <Button variant="outline" size="sm" onClick={() => { exportCsv(id, cols, exportRows()); audit("csv"); }}><Download />CSV</Button>
          <Button variant="outline" size="sm" onClick={() => { printTable(`${id} ${definition?.name ?? ""}`, cols, result.rows.map((r) => Object.fromEntries(result.columns.map((c) => [c.key, formatCell(c.type, r[c.key])]))), basis); audit("pdf"); }}><Printer />Print / PDF</Button>
        </>
      ) : undefined} />
      {definition ? (
        <Card className="mb-3 flex-row flex-wrap items-end gap-3 rounded-lg p-3 shadow-none">
          <Filters definition={definition} draft={draft} setDraft={setDraft} />
          <Button size="sm" disabled={query.isFetching} onClick={() => setApplied(draft)}>Run</Button>
        </Card>
      ) : null}
      {result ? <p className="mb-3 text-xs text-muted-foreground">{basis}</p> : null}
      {query.error ? <Card className="rounded-lg shadow-none"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Card> : !result ? <PageSkeleton /> : <ReportBody key={result.generatedAt} result={result} />}
    </>
  );
}
