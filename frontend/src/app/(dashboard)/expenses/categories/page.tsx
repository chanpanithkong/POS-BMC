"use client";

import { z } from "zod";
import { CrudPanel } from "@/components/shared/crud-panel";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { expenseCategoriesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { ExpenseCategory } from "@/types";

const schema = z.object({ code: z.string().min(1, "Code is required."), name: z.string().min(1, "Name is required."), status: z.enum(["ACTIVE", "INACTIVE"]) });
type V = z.infer<typeof schema>;

export default function ExpenseCategoriesPage() {
  const can = useCan();
  return (
    <RequirePermission anyOf={["expenses.view"]}>
      <PageHeader title="Expense categories" />
      <CrudPanel<ExpenseCategory, V, Partial<ExpenseCategory>>
        queryKey="expense-categories" singular="Category" api={expenseCategoriesApi} canManage={can("expenses.approve", "settings.manage")} exportName="expense-categories" schema={schema} empty={{ code: "", name: "", status: "ACTIVE" }}
        columns={[{ id: "code", header: "Code", value: (c) => c.code, cell: (c) => <span className="font-mono text-xs">{c.code}</span> }, { id: "name", header: "Name", value: (c) => c.name }, { id: "status", header: "Status", value: (c) => c.status, cell: (c) => <StatusBadge status={c.status} /> }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] }]}
        toForm={(c) => ({ code: c.code, name: c.name, status: c.status })} toPayload={(v) => v}
      />
    </RequirePermission>
  );
}
