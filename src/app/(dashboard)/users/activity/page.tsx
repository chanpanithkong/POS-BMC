"use client";

import { Flag } from "lucide-react";
import { useState } from "react";
import { type Column, DataTable } from "@/components/shared/data-table";
import { DetailSheet, Fields, PageHeader, RequirePermission } from "@/components/shared/page";
import { useApiQuery } from "@/hooks/use-api";
import { formatDateTime, titleCase } from "@/lib/format";
import { auditApi } from "@/services";
import type { AuditLog } from "@/types";

const COLUMNS: Column<AuditLog>[] = [
  { id: "at", header: "Time", value: (a) => a.at, cell: (a) => <span className="whitespace-nowrap">{formatDateTime(a.at)}</span> },
  { id: "user", header: "User", value: (a) => a.userName },
  { id: "action", header: "Action", value: (a) => titleCase(a.action), cell: (a) => <span className="inline-flex items-center gap-1.5">{a.flagged ? <Flag className="size-3 text-warning" aria-label="Flagged" /> : null}{titleCase(a.action)}</span> },
  { id: "module", header: "Module", value: (a) => a.module, hideBelow: "md" },
  { id: "entity", header: "Record", value: (a) => `${a.entity} ${a.entityId.slice(0, 14)}`, hideBelow: "lg" },
];

export default function ActivityPage() {
  const query = useApiQuery(["audit"], auditApi.list);
  const [detail, setDetail] = useState<AuditLog | null>(null);
  const pretty = (value: string | null) => {
    if (!value) return null;
    try {
      return <pre className="max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-xs break-all whitespace-pre-wrap">{JSON.stringify(JSON.parse(value), null, 2)}</pre>;
    } catch {
      return value;
    }
  };
  return (
    <RequirePermission anyOf={["audit.view"]}>
      <PageHeader title="Activity logs" description="Append-only record of sensitive actions" />
      <DataTable data={query.data} columns={COLUMNS} getRowId={(a) => a.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="activity-log" onRowClick={setDetail} searchPlaceholder="User, action or record" dateFilter={{ label: "Time", value: (a) => a.at }} emptyTitle="No activity recorded yet"
        filters={[{ id: "flag", label: "Flags", options: [{ value: "yes", label: "Flagged" }, { value: "no", label: "Not flagged" }], value: (a) => (a.flagged ? "yes" : "no") }]} />
      <DetailSheet open={detail !== null} onOpenChange={(o) => !o && setDetail(null)} title={detail ? titleCase(detail.action) : ""} description={detail ? formatDateTime(detail.at) : undefined}>
        {detail ? <Fields items={[["User", detail.userName], ["Module", detail.module], ["Record type", detail.entity], ["Record", detail.entityId]]} /> : null}
        {detail?.before ? <div><p className="mb-1 text-xs text-muted-foreground">Before</p>{pretty(detail.before)}</div> : null}
        {detail?.after ? <div><p className="mb-1 text-xs text-muted-foreground">After</p>{pretty(detail.after)}</div> : null}
      </DetailSheet>
    </RequirePermission>
  );
}
