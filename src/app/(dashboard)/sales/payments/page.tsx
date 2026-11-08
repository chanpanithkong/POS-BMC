"use client";

import { type Column, DataTable } from "@/components/shared/data-table";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchParam } from "@/hooks/use-lookups";
import { formatDate, formatUsd, titleCase } from "@/lib/format";
import { type PaymentRow, paymentsApi } from "@/services";
import { useCan } from "@/stores/auth-store";

export default function PaymentReconciliationPage() {
  const can = useCan();
  const branchId = useBranchParam();
  const query = useApiQuery(["payments", branchId], () => paymentsApi.list({ branchId }));
  const toggle = useApiMutation(({ id, value }: { id: string; value: boolean }) => paymentsApi.reconcile(id, value), { success: "Reconciliation updated" });
  const rows = query.data?.filter((p) => p.method !== "CASH" && p.method !== "STORE_CREDIT");
  const columns: Column<PaymentRow>[] = [
    { id: "date", header: "Date", value: (p) => p.businessDate, cell: (p) => formatDate(p.businessDate) },
    { id: "receipt", header: "Receipt", value: (p) => p.receiptNo, cell: (p) => <span className="font-mono text-xs">{p.receiptNo}</span>, hideBelow: "md" },
    { id: "method", header: "Method", value: (p) => titleCase(p.method) },
    { id: "provider", header: "Provider", value: (p) => p.provider, hideBelow: "lg" },
    { id: "reference", header: "Reference", value: (p) => p.reference, cell: (p) => <span className="font-mono text-xs">{p.reference}</span>, hideBelow: "sm" },
    { id: "amount", header: "Amount", value: (p) => p.amountApplied, cell: (p) => formatUsd(p.amountApplied), align: "right" },
    { id: "status", header: "Status", value: (p) => p.status, cell: (p) => <StatusBadge status={p.status} />, hideBelow: "md" },
    { id: "rec", header: "Reconciliation", value: (p) => (p.reconciled ? "Matched" : "Unmatched"), cell: (p) => <StatusBadge status={p.reconciled ? "MATCHED" : "PENDING"} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (p) => can("cash.session.approve", "reports.cash") ? <Button variant="ghost" size="sm" onClick={() => void toggle.fire({ id: p.id, value: !p.reconciled })}>{p.reconciled ? "Unmatch" : "Match"}</Button> : null },
  ];
  return (
    <RequirePermission anyOf={["reports.cash"]}>
      <PageHeader title="Payment reconciliation" description="Match electronic payments to provider or bank statements. Settlement file import arrives with provider integrations (V-03)." />
      <DataTable data={rows} columns={columns} getRowId={(p) => p.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="payment-reconciliation" searchPlaceholder="Receipt or reference" dateFilter={{ label: "Date", value: (p) => p.businessDate }} emptyTitle="No electronic payments"
        filters={[{ id: "rec", label: "Matching", options: [{ value: "Matched", label: "Matched" }, { value: "Unmatched", label: "Unmatched" }], value: (p) => (p.reconciled ? "Matched" : "Unmatched") }, { id: "method", label: "Methods", options: ["CARD", "QR", "BANK_TRANSFER"].map((value) => ({ value, label: titleCase(value) })), value: (p) => p.method }]} />
    </RequirePermission>
  );
}
