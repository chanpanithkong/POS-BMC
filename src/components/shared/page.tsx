"use client";

import { Info, TrendingDown, TrendingUp, type LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Forbidden } from "@/components/shared/states";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDateTime, formatNumber, formatPercent, formatUsd, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useCan } from "@/stores/auth-store";
import type { KpiValue, Permission, TimelineEvent } from "@/types";

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="no-print mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="mt-0.5 text-sm text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function RequirePermission({ anyOf, children }: { anyOf: Permission[]; children: ReactNode }) {
  const can = useCan();
  return can(...anyOf) ? <>{children}</> : <Forbidden />;
}

export function StatCard({ label, value, hint, icon: Icon, tone }: { label: string; value: ReactNode; hint?: ReactNode; icon?: LucideIcon; tone?: "default" | "warning" | "danger" | "success" }) {
  const toneClass = tone === "danger" ? "text-destructive" : tone === "warning" ? "text-warning" : tone === "success" ? "text-success" : "text-foreground";
  return (
    <Card className="gap-1 rounded-lg p-3.5 shadow-none">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{label}</span>
        {Icon ? <Icon className="size-3.5" aria-hidden /> : null}
      </div>
      <div className={cn("tabular truncate text-xl font-semibold", toneClass)}>{value}</div>
      {hint ? <div className="truncate text-xs text-muted-foreground">{hint}</div> : null}
    </Card>
  );
}

export function formatKpi(kpi: Pick<KpiValue, "format" | "value">) {
  return kpi.format === "money" ? formatUsd(kpi.value) : kpi.format === "percent" ? formatPercent(kpi.value) : formatNumber(kpi.value);
}

export function KpiCard({ kpi }: { kpi: KpiValue }) {
  const delta = kpi.previous && kpi.previous !== 0 ? ((kpi.value - kpi.previous) / Math.abs(kpi.previous)) * 100 : null;
  return (
    <Card className="gap-1 rounded-lg p-3.5 shadow-none transition-colors hover:border-primary/40">
      <div className="flex items-center gap-1 text-xs text-muted-foreground">
        <Link href={kpi.href} className="truncate hover:underline">{kpi.label}</Link>
        <Tooltip>
          <TooltipTrigger asChild><button type="button" aria-label={`How ${kpi.label} is calculated`}><Info className="size-3 opacity-60" /></button></TooltipTrigger>
          <TooltipContent className="max-w-60">{kpi.definition}</TooltipContent>
        </Tooltip>
      </div>
      <Link href={kpi.href} className="tabular truncate text-xl font-semibold">{formatKpi(kpi)}</Link>
      <div className="h-4 text-xs text-muted-foreground">
        {delta === null ? null : (
          <span className={cn("inline-flex items-center gap-0.5", delta >= 0 ? "text-success" : "text-destructive")}>
            {delta >= 0 ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
            {Math.abs(delta).toFixed(1)}%<span className="ml-1 text-muted-foreground">vs previous period</span>
          </span>
        )}
      </div>
    </Card>
  );
}

const TONES: Record<string, string> = {
  good: "border-success/30 bg-success/10 text-success",
  warn: "border-warning/30 bg-warning/10 text-warning",
  bad: "border-destructive/30 bg-destructive/10 text-destructive",
  info: "border-info/30 bg-info/10 text-info",
  neutral: "border-border bg-muted text-muted-foreground",
};

const STATUS_TONE: Record<string, keyof typeof TONES> = {
  ACTIVE: "good", FINALIZED: "good", PAID: "good", COMPLETED: "good", POSTED: "good", RECEIVED: "good", CLOSED: "good", APPROVED: "good", IN_STOCK: "good", MATCHED: "good", CREDITED: "good", RESOLVED: "good", COMMITTED: "good", SENT: "info",
  DRAFT: "neutral", HELD: "neutral", INACTIVE: "neutral", CANCELLED: "neutral", EXPIRED: "neutral", DISABLED: "neutral", DISCONTINUED: "neutral", ROLLED_BACK: "neutral", SNOOZED: "neutral", NOT_REQUIRED: "neutral",
  PENDING: "warn", PENDING_PAYMENT: "warn", PENDING_APPROVAL: "warn", SUBMITTED: "warn", REQUESTED: "warn", PARTIALLY_PAID: "warn", PARTIALLY_RECEIVED: "warn", PARTIALLY_REFUNDED: "warn", CLOSING: "warn", REVIEW: "warn", COUNTING: "info", OPEN: "info", LOW: "warn", OVER: "info", UNPAID: "warn", RECORDED: "info", ACKNOWLEDGED: "info", DISPATCHED: "info", AUTHORIZED: "info",
  VOIDED: "bad", REJECTED: "bad", FAILED: "bad", OUT: "bad", NEGATIVE: "bad", REFUNDED: "bad", MISMATCH: "bad", FORCE_CLOSED: "bad", SHORT_CLOSED: "warn",
};

const STATUS_LABEL: Record<string, string> = { IN_STOCK: "In stock", OUT: "Out of stock", LOW: "Low stock", OVER: "Overstock" };

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge variant="outline" className={cn("font-medium whitespace-nowrap", TONES[STATUS_TONE[status] ?? "neutral"], className)}>
      {STATUS_LABEL[status] ?? titleCase(status)}
    </Badge>
  );
}

export function DetailSheet({ open, onOpenChange, title, description, children, footer, wide }: { open: boolean; onOpenChange: (open: boolean) => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className={cn("flex w-full flex-col gap-0 p-0", wide ? "sm:max-w-3xl" : "sm:max-w-xl")}>
        <SheetHeader className="border-b p-4 pr-10">
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription className={description ? undefined : "sr-only"}>{description ?? "Record details"}</SheetDescription>
        </SheetHeader>
        <div className="flex-1 space-y-4 overflow-y-auto p-4">{children}</div>
        {footer ? <div className="no-print flex flex-wrap justify-end gap-2 border-t p-3">{footer}</div> : null}
      </SheetContent>
    </Sheet>
  );
}

export function Fields({ items, columns = 2 }: { items: [string, ReactNode][]; columns?: 2 | 3 }) {
  return (
    <dl className={cn("grid gap-x-4 gap-y-3 text-sm", columns === 3 ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-2")}>
      {items.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-xs text-muted-foreground">{label}</dt>
          <dd className="mt-0.5 break-words">{value === null || value === undefined || value === "" ? "—" : value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="space-y-2.5 border-l pl-3.5">
      {events.map((e, i) => (
        <li key={i} className="relative text-sm">
          <span className="absolute top-1.5 -left-[18px] size-2 rounded-full bg-primary" aria-hidden />
          <span className="font-medium">{e.label}</span>
          <span className="ml-1.5 text-xs text-muted-foreground">{e.by} · {formatDateTime(e.at)}</span>
          {e.note ? <p className="text-xs text-muted-foreground">{e.note}</p> : null}
        </li>
      ))}
    </ol>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="text-sm font-medium">{children}</h3>;
}
