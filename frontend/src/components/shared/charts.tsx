"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, type TooltipContentProps, XAxis, YAxis } from "recharts";
import { formatDate, formatUsd } from "@/lib/format";

type Datum = Record<string, string | number | null | undefined>;

export interface Series {
  key: string;
  label: string;
}

const COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
const AXIS = { fontSize: 11, fill: "var(--muted-foreground)" };

function shortMoney(value: number) {
  return Math.abs(value) >= 1000 ? `$${(value / 1000).toFixed(1)}k` : `$${Math.round(value)}`;
}

function ChartTooltip({ active, payload, label, valueFormat, labelFormat }: TooltipContentProps<number, string> & { valueFormat: (v: number) => string; labelFormat?: (v: string) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md">
      <p className="mb-0.5 font-medium">{labelFormat ? labelFormat(String(label)) : String(label)}</p>
      {payload.map((entry) => (
        <p key={String(entry.dataKey)} className="flex items-center gap-1.5 text-muted-foreground">
          <span className="size-2 rounded-full" style={{ background: entry.color }} aria-hidden />
          {entry.name}: <span className="tabular font-medium text-foreground">{valueFormat(Number(entry.value))}</span>
        </p>
      ))}
    </div>
  );
}

function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null;
  return (
    <div className="mb-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
      {series.map((s, i) => (
        <span key={s.key} className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded-full" style={{ background: COLORS[i] }} aria-hidden />
          {s.label}
        </span>
      ))}
    </div>
  );
}

const isIsoDate = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value);
const tickDate = (value: string) => (isIsoDate(value) ? value.slice(8) + "/" + value.slice(5, 7) : value);

export function TrendChart({ data, xKey, series, height = 240, money = true }: { data: Datum[]; xKey: string; series: Series[]; height?: number; money?: boolean }) {
  const format = money ? formatUsd : (v: number) => v.toLocaleString();
  return (
    <div>
      <Legend series={series} />
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.7} />
          <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={false} tickFormatter={tickDate} minTickGap={24} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={46} tickFormatter={money ? shortMoney : undefined} />
          <Tooltip cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }} content={(props) => <ChartTooltip {...(props as TooltipContentProps<number, string>)} valueFormat={format} labelFormat={(v) => (isIsoDate(v) ? formatDate(v) : v)} />} />
          {series.map((s, i) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={COLORS[i]} strokeWidth={2} dot={data.length < 16 ? { r: 3, strokeWidth: 0, fill: COLORS[i] } : false} activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Ranked magnitudes with one hue; horizontal so long names stay readable. */
export function RankBars({ data, nameKey, valueKey, label, height, money = true }: { data: Datum[]; nameKey: string; valueKey: string; label: string; height?: number; money?: boolean }) {
  const rows = data.slice(0, 10);
  const format = money ? formatUsd : (v: number) => v.toLocaleString();
  return (
    <ResponsiveContainer width="100%" height={height ?? Math.max(120, rows.length * 30 + 24)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }} barCategoryGap={8}>
        <CartesianGrid horizontal={false} stroke="var(--border)" strokeOpacity={0.7} />
        <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} tickFormatter={money ? shortMoney : undefined} />
        <YAxis type="category" dataKey={nameKey} tick={AXIS} tickLine={false} axisLine={false} width={116} tickFormatter={(v: string) => (v.length > 18 ? `${v.slice(0, 17)}…` : v)} />
        <Tooltip cursor={{ fill: "var(--muted)", opacity: 0.5 }} content={(props) => <ChartTooltip {...(props as TooltipContentProps<number, string>)} valueFormat={format} />} />
        <Bar dataKey={valueKey} name={label} fill={COLORS[0]} radius={[0, 4, 4, 0]} maxBarSize={14} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}
