"use client";

import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { z } from "zod";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { PageHeader, RequirePermission, StatCard, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchOptions, useBranchParam } from "@/hooks/use-lookups";
import { formatDate, formatMoney, formatUsd, titleCase, todayIso } from "@/lib/format";
import { expenseCategoriesApi, expensesApi, settingsApi } from "@/services";
import { useAuthStore, useCan } from "@/stores/auth-store";
import type { Expense } from "@/types";

const schema = z.object({ date: z.string().min(1, "Enter a date."), categoryId: z.string().min(1, "Select a category."), description: z.string().min(1, "A description is required."), amount: z.number({ error: "Enter an amount." }).positive("Amount must be greater than zero."), currency: z.enum(["USD", "KHR"]), paymentMethod: z.string().min(1, "Select a method."), branchId: z.string().min(1, "Select a branch."), attachment: z.string() });
type V = z.infer<typeof schema>;

export default function ExpensesPage() {
  const can = useCan();
  const user = useAuthStore((s) => s.user);
  const branchId = useBranchParam();
  const { confirm, prompt } = useDialogs();
  const query = useApiQuery(["expenses", branchId], () => expensesApi.list({ branchId }));
  const categories = useApiQuery(["expense-categories"], () => expenseCategoriesApi.list());
  const settings = useApiQuery(["settings"], settingsApi.get);
  const branches = useBranchOptions();
  const [editing, setEditing] = useState<Expense | null>(null);
  const [open, setOpen] = useState(false);
  const save = useApiMutation((v: V) => (editing ? expensesApi.update(editing.id, { ...v, attachment: v.attachment || null } as object) : expensesApi.create({ ...v, attachment: v.attachment || null })), { success: "Expense saved", silentError: true });
  const act = useApiMutation(({ id, verb, body }: { id: string; verb: string; body?: unknown }) => expensesApi.action(id, verb, body), { success: (e) => `${e.expenseNo}: ${titleCase(e.status)}` });
  const remove = useApiMutation((id: string) => expensesApi.remove(id), { success: "Expense deleted" });

  const approved = (query.data ?? []).filter((e) => e.status === "APPROVED");
  const month = todayIso().slice(0, 7);
  const columns: Column<Expense>[] = [
    { id: "no", header: "Number", value: (e) => e.expenseNo, cell: (e) => <span className="font-mono text-xs whitespace-nowrap">{e.expenseNo}</span>, hideBelow: "md" },
    { id: "date", header: "Date", value: (e) => e.date, cell: (e) => formatDate(e.date) },
    { id: "category", header: "Category", value: (e) => e.categoryName },
    { id: "desc", header: "Description", value: (e) => e.description, hideBelow: "lg", className: "max-w-56 truncate" },
    { id: "branch", header: "Branch", value: (e) => e.branchName, hideBelow: "lg" },
    { id: "amount", header: "Amount", value: (e) => e.amountBase, cell: (e) => formatMoney(e.amount, e.currency), align: "right" },
    { id: "status", header: "Status", value: (e) => e.status, cell: (e) => <StatusBadge status={e.status} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (e) => (
      <div className="flex justify-end gap-0.5">
        {e.status === "SUBMITTED" && can("expenses.approve") && e.createdById !== user?.id ? <><Button variant="ghost" size="icon-sm" aria-label="Approve" onClick={() => void act.fire({ id: e.id, verb: "approve" })}><Check /></Button><Button variant="ghost" size="icon-sm" aria-label="Reject" onClick={async () => { const reason = await prompt({ title: "Reject this expense?", label: "Reason", confirmLabel: "Reject" }); if (reason) void act.fire({ id: e.id, verb: "reject", body: { reason } }); }}><X /></Button></> : null}
        {can("expenses.create") && (e.status !== "APPROVED" || e.approvedBy === "Auto-approved within limit") ? <Button variant="ghost" size="icon-sm" aria-label="Edit" onClick={() => { setEditing(e); setOpen(true); }}><Pencil /></Button> : null}
        {can("expenses.create") && e.status !== "APPROVED" ? <Button variant="ghost" size="icon-sm" aria-label="Delete" onClick={async () => { if (await confirm({ title: "Delete this expense?", confirmLabel: "Delete", destructive: true })) void remove.fire(e.id); }}><Trash2 /></Button> : null}
      </div>
    ) },
  ];

  return (
    <RequirePermission anyOf={["expenses.view"]}>
      <PageHeader title="Expenses" description="Operating costs, kept separate from inventory and cost of goods sold" />
      <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="This month" value={formatUsd(approved.filter((e) => e.date.startsWith(month)).reduce((s, e) => s + e.amountBase, 0))} hint="Approved" />
        <StatCard label="Awaiting approval" value={(query.data ?? []).filter((e) => e.status === "SUBMITTED").length} />
        <StatCard label="Approval above" value={formatUsd(settings.data?.expenseApprovalThreshold)} />
        <StatCard label="Document required above" value={formatUsd(settings.data?.expenseAttachmentThreshold)} />
      </div>
      <DataTable data={query.data} columns={columns} getRowId={(e) => e.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="expenses" searchPlaceholder="Number, category or description" dateFilter={{ label: "Date", value: (e) => e.date }} emptyTitle="No expenses yet"
        filters={[{ id: "status", label: "Statuses", options: ["SUBMITTED", "APPROVED", "REJECTED"].map((value) => ({ value, label: titleCase(value) })), value: (e) => e.status }, { id: "category", label: "Categories", options: (categories.data ?? []).map((c) => ({ value: c.id, label: c.name })), value: (e) => e.categoryId }, { id: "branch", label: "Branches", options: branches, value: (e) => e.branchId }]}
        toolbar={can("expenses.create") ? <Button size="sm" onClick={() => { setEditing(null); setOpen(true); }}><Plus />New expense</Button> : undefined} />
      <FormDialog<V> open={open} onOpenChange={setOpen} title={editing ? "Edit expense" : "New expense"} schema={schema} onSubmit={(v) => save.run(v)}
        defaultValues={editing ? { date: editing.date, categoryId: editing.categoryId, description: editing.description, amount: editing.amount, currency: editing.currency, paymentMethod: editing.paymentMethod, branchId: editing.branchId, attachment: editing.attachment ?? "" } : { date: todayIso(), categoryId: "", description: "", amount: 0, currency: "USD", paymentMethod: "Cash", branchId: branchId === "all" ? "" : branchId, attachment: "" }}
        fields={[{ name: "date", label: "Date", type: "date", required: true }, { name: "categoryId", label: "Category", type: "select", required: true, options: (categories.data ?? []).map((c) => ({ value: c.id, label: c.name })) }, { name: "description", label: "Description", full: true, required: true }, { name: "amount", label: "Amount", type: "number", required: true }, { name: "currency", label: "Currency", type: "select", options: [{ value: "USD", label: "USD" }, { value: "KHR", label: "KHR" }] }, { name: "paymentMethod", label: "Payment method", type: "select", options: ["Cash", "Bank transfer", "Card"].map((value) => ({ value, label: value })) }, { name: "branchId", label: "Branch", type: "select", required: true, options: branches }, { name: "attachment", label: "Supporting document", type: "file", full: true, help: "Image or PDF, up to 2 MB." }]} />
    </RequirePermission>
  );
}
