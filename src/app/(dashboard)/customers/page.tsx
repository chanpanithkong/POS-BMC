"use client";

import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { type Column, DataTable } from "@/components/shared/data-table";
import { FormDialog } from "@/components/shared/form-dialog";
import { PageHeader, RequirePermission } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useParamDialog } from "@/hooks/use-param-dialog";
import { useCustomerGroupOptions } from "@/hooks/use-lookups";
import { customerFields, customerSchema, emptyCustomer, type CustomerForm, toCustomerPayload } from "@/components/customers/customer-form";
import { formatDate, formatUsd } from "@/lib/format";
import { customersApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Customer } from "@/types";

export default function CustomersPage() {
  const can = useCan();
  const router = useRouter();
  const groups = useCustomerGroupOptions();
  const query = useApiQuery(["customers"], () => customersApi.list());
  const [open, setOpen] = useParamDialog("new", can("customers.manage"));
  const create = useApiMutation((v: CustomerForm) => customersApi.create(toCustomerPayload(v)), { success: "Customer created", silentError: true });

  const columns: Column<Customer>[] = [
    { id: "code", header: "Code", value: (c) => c.code, cell: (c) => <span className="font-mono text-xs">{c.code}</span> },
    { id: "name", header: "Name", value: (c) => c.name },
    { id: "phone", header: "Phone", value: (c) => c.phone },
    { id: "group", header: "Group", value: (c) => c.groupName, hideBelow: "md" },
    { id: "points", header: "Points", value: (c) => c.loyaltyPoints, align: "right", hideBelow: "sm" },
    { id: "credit", header: "Store credit", value: (c) => c.storeCredit, cell: (c) => formatUsd(c.storeCredit), align: "right", hideBelow: "lg" },
    { id: "spent", header: "Total spent", value: (c) => c.totalSpent, cell: (c) => formatUsd(c.totalSpent), align: "right", hideBelow: "lg" },
    { id: "last", header: "Last purchase", value: (c) => c.lastPurchaseAt, cell: (c) => formatDate(c.lastPurchaseAt), hideBelow: "xl" },
  ];

  return (
    <RequirePermission anyOf={["customers.view"]}>
      <PageHeader title="Customers" description="Walk-in sales need no customer record. Personal data is masked for roles without permission." />
      <DataTable data={query.data} columns={columns} getRowId={(c) => c.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="customers" onRowClick={(c) => router.push(`/customers/${c.id}`)} searchPlaceholder="Phone, code or name"
        filters={[{ id: "group", label: "Groups", options: groups, value: (c) => c.groupId }]}
        toolbar={can("customers.manage") ? <Button size="sm" onClick={() => setOpen(true)}><Plus />New customer</Button> : undefined} emptyTitle="No customers yet" />
      <FormDialog<CustomerForm> open={open} onOpenChange={setOpen} title="New customer" schema={customerSchema} defaultValues={emptyCustomer} fields={customerFields(groups)} onSubmit={(v) => create.run(v)} />
    </RequirePermission>
  );
}
