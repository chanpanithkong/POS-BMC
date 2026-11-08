"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { z } from "zod";
import { type Column, DataTable } from "@/components/shared/data-table";
import { FormDialog } from "@/components/shared/form-dialog";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useSupplierOptions } from "@/hooks/use-lookups";
import { formatDate, formatUsd, titleCase, todayIso, addDaysIso } from "@/lib/format";
import { purchaseOrdersApi, supplierInvoicesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { SupplierInvoice } from "@/types";

const schema = z.object({ invoiceNo: z.string().min(1, "Invoice number is required."), supplierId: z.string().min(1, "Select a supplier."), poId: z.string(), invoiceDate: z.string().min(1, "Enter a date."), dueDate: z.string().min(1, "Enter a due date."), amount: z.number({ error: "Enter an amount." }).positive("Amount must be greater than zero.") });
type V = z.infer<typeof schema>;
const paySchema = z.object({ amount: z.number({ error: "Enter an amount." }).positive("Amount must be greater than zero."), reference: z.string().min(1, "A reference is required.") });
type P = z.infer<typeof paySchema>;

export default function SupplierInvoicesPage() {
  const can = useCan();
  const canWrite = can("purchasing.create", "expenses.approve");
  const query = useApiQuery(["supplier-invoices"], supplierInvoicesApi.list);
  const orders = useApiQuery(["purchase-orders"], () => purchaseOrdersApi.list());
  const suppliers = useSupplierOptions();
  const [open, setOpen] = useState(false);
  const [paying, setPaying] = useState<SupplierInvoice | null>(null);
  const create = useApiMutation((v: V) => supplierInvoicesApi.create({ ...v, poId: v.poId || null }), { success: (i) => `Invoice recorded: ${titleCase(i.status)}`, silentError: true });
  const pay = useApiMutation((v: P) => supplierInvoicesApi.pay(paying?.id ?? "", v.amount, v.reference), { success: "Payment recorded", silentError: true });

  const columns: Column<SupplierInvoice>[] = [
    { id: "no", header: "Invoice", value: (i) => i.invoiceNo, cell: (i) => <span className="font-mono text-xs">{i.invoiceNo}</span> },
    { id: "supplier", header: "Supplier", value: (i) => i.supplierName, className: "max-w-52 truncate" },
    { id: "po", header: "PO", value: (i) => i.poNo, hideBelow: "lg" },
    { id: "due", header: "Due", value: (i) => i.dueDate, cell: (i) => formatDate(i.dueDate), hideBelow: "md" },
    { id: "amount", header: "Amount", value: (i) => i.amount, cell: (i) => formatUsd(i.amount), align: "right" },
    { id: "balance", header: "Outstanding", value: (i) => i.amount - i.paidAmount, cell: (i) => formatUsd(i.amount - i.paidAmount), align: "right" },
    { id: "match", header: "Matching", value: (i) => i.matchNotes, hideBelow: "xl", className: "max-w-56 truncate" },
    { id: "status", header: "Status", value: (i) => i.status, cell: (i) => <StatusBadge status={i.status} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (i) => (canWrite && i.amount - i.paidAmount > 0.005 ? <Button size="sm" variant="outline" onClick={() => setPaying(i)}>Record payment</Button> : null) },
  ];

  return (
    <RequirePermission anyOf={["purchasing.view"]}>
      <PageHeader title="Supplier invoices" description="Matched to purchase orders and receipts. An invoice number can be entered only once per supplier." />
      <DataTable data={query.data} columns={columns} getRowId={(i) => i.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="supplier-invoices" searchPlaceholder="Invoice or supplier"
        filters={[{ id: "status", label: "Statuses", options: ["RECORDED", "MATCHED", "MISMATCH", "PARTIALLY_PAID", "PAID"].map((value) => ({ value, label: titleCase(value) })), value: (i) => i.status }, { id: "supplier", label: "Suppliers", options: suppliers, value: (i) => i.supplierId }]}
        toolbar={canWrite ? <Button size="sm" onClick={() => setOpen(true)}><Plus />Record invoice</Button> : undefined} emptyTitle="No supplier invoices" />
      <FormDialog<V> open={open} onOpenChange={setOpen} title="Record supplier invoice" schema={schema} onSubmit={(v) => create.run(v)} submitLabel="Record invoice"
        defaultValues={{ invoiceNo: "", supplierId: "", poId: "", invoiceDate: todayIso(), dueDate: addDaysIso(todayIso(), 30), amount: 0 }}
        fields={[{ name: "invoiceNo", label: "Invoice number", required: true }, { name: "supplierId", label: "Supplier", type: "select", required: true, options: suppliers }, { name: "poId", label: "Purchase order", type: "select", allowNone: "No purchase order", full: true, options: (orders.data ?? []).map((p) => ({ value: p.id, label: `${p.poNo} · ${p.supplierName}` })) }, { name: "invoiceDate", label: "Invoice date", type: "date", required: true }, { name: "dueDate", label: "Due date", type: "date", required: true }, { name: "amount", label: "Amount (USD)", type: "number", required: true }]} />
      <FormDialog<P> open={paying !== null} onOpenChange={(o) => !o && setPaying(null)} title={`Payment on ${paying?.invoiceNo ?? ""}`} description={paying ? `Outstanding ${formatUsd(paying.amount - paying.paidAmount)}` : undefined} schema={paySchema} onSubmit={(v) => pay.run(v)} submitLabel="Record payment"
        defaultValues={{ amount: paying ? Math.round((paying.amount - paying.paidAmount) * 100) / 100 : 0, reference: "" }} fields={[{ name: "amount", label: "Amount (USD)", type: "number", required: true }, { name: "reference", label: "Payment reference", required: true }]} />
    </RequirePermission>
  );
}
