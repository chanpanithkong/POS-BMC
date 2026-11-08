"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/shared/page";
import { ErrorState, Forbidden, PageSkeleton } from "@/components/shared/states";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useApiQuery } from "@/hooks/use-api";
import { reportsApi } from "@/services";

export default function ReportsPage() {
  const query = useApiQuery(["reports"], reportsApi.catalog);
  const [term, setTerm] = useState("");
  const groups = useMemo(() => {
    const value = term.trim().toLowerCase();
    const rows = (query.data ?? []).filter((r) => !value || `${r.id} ${r.name} ${r.purpose}`.toLowerCase().includes(value));
    return ["Sales", "Inventory", "Purchasing", "Cash", "Business", "Control"].map((name) => ({ name, rows: rows.filter((r) => r.group === name) })).filter((g) => g.rows.length);
  }, [query.data, term]);

  return (
    <>
      <PageHeader title="Reports" description="Sales reports use finalized sales by business date. Totals match the dashboard." actions={<Input value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Search reports" aria-label="Search reports" className="h-8 w-56" />} />
      {query.error ? <Card className="rounded-lg shadow-none"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Card> : !query.data ? <PageSkeleton /> : !query.data.length ? <Forbidden message="Your role has no reports assigned." /> : (
        <div className="grid gap-3 lg:grid-cols-2">
          {groups.map((group) => (
            <Card key={group.name} className="gap-1 rounded-lg p-3 shadow-none">
              <h2 className="px-1 pb-1 text-sm font-medium">{group.name}</h2>
              <ul>
                {group.rows.map((r) => (
                  <li key={r.id}>
                    <Link href={`/reports/${r.id}`} className="flex items-center gap-2 rounded-md px-1 py-1.5 hover:bg-muted">
                      <span className="w-14 shrink-0 font-mono text-[11px] text-muted-foreground">{r.id}</span>
                      <span className="min-w-0 flex-1"><span className="block truncate text-sm">{r.name}</span><span className="block truncate text-xs text-muted-foreground">{r.purpose}</span></span>
                      <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
