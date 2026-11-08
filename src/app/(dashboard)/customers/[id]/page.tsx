"use client";

import { Pencil, ShieldOff } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { customerFields, customerSchema, type CustomerForm, toCustomerPayload } from "@/components/customers/customer-form";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { Fields, PageHeader, RequirePermission, StatCard, StatusBadge } from "@/components/shared/page";
import { ErrorState, PageSkeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useCustomerGroupOptions } from "@/hooks/use-lookups";
import { formatDate, formatDateTime, formatNumber, formatUsd } from "@/lib/format";
import { customersApi, salesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Sale } from "@/types";

const SALE_COLUMNS: Column<Sale>[] = [
  { id: "receipt", header: "Receipt", value: (s) => s.receiptNo, cell: (s) => <span className="font-mono text-xs">{s.receiptNo}</span> },
  { id: "at", header: "Date", value: (s) => s.finalizedAt, cell: (s) => formatDateTime(s.finalizedAt) },
  { id: "branch", header: "Branch", value: (s) => s.branchName, hideBelow: "md" },
  { id: "items", header: "Items", value: (s) => s.lines.length, align: "right" },
  { id: "total", header: "Total", value: (s) => s.grandTotal, cell: (s) => formatUsd(s.grandTotal), align: "right" },
  { id: "status", header: "Status", value: (s) => s.paymentStatus, cell: (s) => <StatusBadge status={s.paymentStatus} /> },
];

export default function CustomerProfilePage() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const router = useRouter();
  const { confirm } = useDialogs();
  const groups = useCustomerGroupOptions();
  const query = useApiQuery(["customers", id], () => customersApi.get(id));
  const sales = useApiQuery(["sales", "customer", id], () => salesApi.list({ customerId: id }), { enabled: can("sales.view") });
  const [editing, setEditing] = useState(false);
  const save = useApiMutation((v: CustomerForm) => customersApi.update(id, toCustomerPayload(v)), { success: "Customer saved", silentError: true });
  const anonymize = useApiMutation(() => customersApi.anonymize(id), { success: "Customer anonymised", onSuccess: () => router.replace("/customers") });

  return (
    <RequirePermission anyOf={["customers.view"]}>
      {query.error ? <Card className="rounded-lg shadow-none"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Card> : !query.data ? <PageSkeleton /> : (
        <>
          <PageHeader title={query.data.name} description={query.data.code} actions={
            <>
              {can("customers.manage") ? <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Pencil />Edit</Button> : null}
              {can("customers.personal_data") ? <Button size="sm" variant="outline" onClick={async () => { if (await confirm({ title: "Anonymise this customer?", description: "Name and contact details are removed permanently. Sales records are kept without personal data.", confirmLabel: "Anonymise", destructive: true })) void anonymize.fire(undefined); }}><ShieldOff />Anonymise</Button> : null}
            </>
          } />
          <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Total spent" value={formatUsd(query.data.totalSpent)} />
            <StatCard label="Loyalty points" value={formatNumber(query.data.loyaltyPoints)} hint={query.data.tier} />
            <StatCard label="Store credit" value={formatUsd(query.data.storeCredit)} />
            <StatCard label="Last purchase" value={<span className="text-base">{formatDate(query.data.lastPurchaseAt)}</span>} />
          </div>
          <Card className="mb-3 rounded-lg p-4 shadow-none">
            <Fields columns={3} items={[["Phone", query.data.phone], ["Email", query.data.email], ["Address", query.data.address], ["Group", query.data.groupName], ["Marketing consent", query.data.consentMarketing ? "Yes" : "No"], ["Notes", query.data.notes]]} />
          </Card>
          {can("sales.view") ? <DataTable data={sales.data} columns={SALE_COLUMNS} getRowId={(s) => s.id} isLoading={sales.isLoading} error={sales.error} searchPlaceholder="Search purchases" emptyTitle="No purchases yet" exportName={`customer-${query.data.code}-purchases`} /> : null}
          <FormDialog<CustomerForm> open={editing} onOpenChange={setEditing} title="Edit customer" schema={customerSchema} fields={customerFields(groups)} onSubmit={(v) => save.run(v)}
            defaultValues={{ code: query.data.code, name: query.data.name, phone: query.data.phone, email: query.data.email, address: query.data.address, groupId: query.data.groupId ?? "", notes: query.data.notes, consentMarketing: query.data.consentMarketing }} />
        </>
      )}
    </RequirePermission>
  );
}
