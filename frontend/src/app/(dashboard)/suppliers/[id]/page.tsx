"use client";

import { Plus, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { z } from "zod";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { useProducts } from "@/components/shared/line-items";
import { Fields, PageHeader, RequirePermission, StatCard, StatusBadge } from "@/components/shared/page";
import { ErrorState, PageSkeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { formatDate, formatDateTime, formatUsd } from "@/lib/format";
import { goodsReceiptsApi, purchaseOrdersApi, purchaseReturnsApi, suppliersApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { GoodsReceipt, ProductListItem, PurchaseOrder, PurchaseReturn, SupplierContact } from "@/types";

const contactSchema = z.object({ name: z.string().min(1, "Name is required."), position: z.string(), phone: z.string(), email: z.union([z.literal(""), z.email("Enter a valid email.")]) });
type ContactForm = z.infer<typeof contactSchema>;

export default function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const can = useCan();
  const { confirm } = useDialogs();
  const supplier = useApiQuery(["suppliers", id], () => suppliersApi.get(id));
  const orders = useApiQuery(["purchase-orders", "supplier", id], () => purchaseOrdersApi.list({ supplierId: id }));
  const receipts = useApiQuery(["goods-receipts"], () => goodsReceiptsApi.list());
  const returns = useApiQuery(["purchase-returns"], purchaseReturnsApi.list);
  const products = useProducts((p) => p.suppliers.some((s) => s.supplierId === id));
  const [adding, setAdding] = useState(false);
  const saveContacts = useApiMutation((contacts: SupplierContact[]) => suppliersApi.update(id, { contacts }), { success: "Contacts saved", silentError: true });

  const poColumns: Column<PurchaseOrder>[] = [
    { id: "no", header: "PO", value: (p) => p.poNo, cell: (p) => <span className="font-mono text-xs">{p.poNo}</span> },
    { id: "at", header: "Created", value: (p) => p.createdAt, cell: (p) => formatDate(p.createdAt) },
    { id: "expected", header: "Expected", value: (p) => p.expectedDate, cell: (p) => formatDate(p.expectedDate), hideBelow: "md" },
    { id: "total", header: "Total", value: (p) => p.total, cell: (p) => formatUsd(p.total), align: "right" },
    { id: "status", header: "Status", value: (p) => p.status, cell: (p) => <StatusBadge status={p.status} /> },
  ];
  const grnColumns: Column<GoodsReceipt>[] = [
    { id: "no", header: "Receipt", value: (g) => g.receiptNo, cell: (g) => <span className="font-mono text-xs">{g.receiptNo}</span> },
    { id: "po", header: "PO", value: (g) => g.poNo },
    { id: "posted", header: "Posted", value: (g) => g.postedAt, cell: (g) => formatDateTime(g.postedAt) },
    { id: "disc", header: "Discrepancies", value: (g) => g.discrepancies.length, align: "right" },
    { id: "status", header: "Status", value: (g) => g.status, cell: (g) => <StatusBadge status={g.status} /> },
  ];
  const retColumns: Column<PurchaseReturn>[] = [
    { id: "no", header: "Return", value: (r) => r.returnNo, cell: (r) => <span className="font-mono text-xs">{r.returnNo}</span> },
    { id: "reason", header: "Reason", value: (r) => r.reason },
    { id: "total", header: "Total", value: (r) => r.total, cell: (r) => formatUsd(r.total), align: "right" },
    { id: "status", header: "Status", value: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> },
  ];
  const productColumns: Column<ProductListItem>[] = [
    { id: "sku", header: "SKU", value: (p) => p.sku, cell: (p) => <span className="font-mono text-xs">{p.sku}</span> },
    { id: "name", header: "Product", value: (p) => p.nameEn },
    { id: "ssku", header: "Supplier SKU", value: (p) => p.suppliers.find((s) => s.supplierId === id)?.supplierSku, hideBelow: "md" },
    { id: "lead", header: "Lead days", value: (p) => p.suppliers.find((s) => s.supplierId === id)?.leadTimeDays, align: "right", hideBelow: "md" },
    ...(can("costs.view") ? [{ id: "cost", header: "Cost", value: (p: ProductListItem) => p.suppliers.find((s) => s.supplierId === id)?.cost ?? 0, cell: (p: ProductListItem) => formatUsd(p.suppliers.find((s) => s.supplierId === id)?.cost), align: "right" as const }] : []),
  ];

  const s = supplier.data;
  return (
    <RequirePermission anyOf={["suppliers.view"]}>
      {supplier.error ? <Card className="rounded-lg shadow-none"><ErrorState error={supplier.error} onRetry={() => void supplier.refetch()} /></Card> : !s ? <PageSkeleton /> : (
        <>
          <PageHeader title={s.nameEn} description={`${s.code} · ${s.nameKm}`} actions={<StatusBadge status={s.status} />} />
          <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard label="Open POs" value={s.openPoCount ?? 0} />
            <StatCard label="On-time delivery" value={s.onTimeRate === null ? "—" : `${s.onTimeRate}%`} />
            <StatCard label="Fill rate" value={s.fillRate === null ? "—" : `${s.fillRate}%`} />
            <StatCard label="Outstanding" value={formatUsd(s.outstandingBalance)} />
          </div>
          <Tabs defaultValue="details">
            <TabsList className="h-auto max-w-full flex-wrap justify-start">{["details", "contacts", "products", "orders", "receipts", "returns"].map((t) => <TabsTrigger key={t} value={t} className="capitalize">{t}</TabsTrigger>)}</TabsList>
            <TabsContent value="details"><Card className="rounded-lg p-4 shadow-none"><Fields columns={3} items={[["Phone", s.phone], ["Email", s.email], ["Address", s.address], ["Terms", s.paymentTerms], ["Currency", s.currency], ["Lead time", `${s.leadTimeDays} days`], ["Tax ID", s.taxId]]} /></Card></TabsContent>
            <TabsContent value="contacts">
              <Card className="gap-2 rounded-lg p-4 shadow-none">
                {can("suppliers.manage") ? <div className="flex justify-end"><Button size="sm" onClick={() => setAdding(true)}><Plus />Add contact</Button></div> : null}
                <ul className="divide-y">{s.contacts.map((c) => <li key={c.id} className="flex items-center justify-between gap-2 py-2 text-sm"><span className="min-w-0"><span className="block font-medium">{c.name}</span><span className="block truncate text-xs text-muted-foreground">{c.position} · {c.phone} · {c.email}</span></span>{can("suppliers.manage") ? <Button variant="ghost" size="icon-sm" aria-label={`Remove ${c.name}`} onClick={async () => { if (await confirm({ title: `Remove ${c.name}?`, confirmLabel: "Remove", destructive: true })) void saveContacts.fire(s.contacts.filter((x) => x.id !== c.id)); }}><Trash2 /></Button> : null}</li>)}</ul>
                {!s.contacts.length ? <p className="py-6 text-center text-sm text-muted-foreground">No contacts yet</p> : null}
              </Card>
            </TabsContent>
            <TabsContent value="products"><DataTable data={products} columns={productColumns} getRowId={(p) => p.id} searchPlaceholder="Product" emptyTitle="No linked products" /></TabsContent>
            <TabsContent value="orders"><DataTable data={orders.data} columns={poColumns} getRowId={(p) => p.id} isLoading={orders.isLoading} error={orders.error} searchPlaceholder="PO number" emptyTitle="No purchase orders" exportName={`${s.code}-orders`} /></TabsContent>
            <TabsContent value="receipts"><DataTable data={receipts.data?.filter((g) => g.supplierId === id)} columns={grnColumns} getRowId={(g) => g.id} isLoading={receipts.isLoading} searchPlaceholder="Receipt number" emptyTitle="No receipts" /></TabsContent>
            <TabsContent value="returns"><DataTable data={returns.data?.filter((r) => r.supplierId === id)} columns={retColumns} getRowId={(r) => r.id} isLoading={returns.isLoading} searchPlaceholder="Return number" emptyTitle="No returns" /></TabsContent>
          </Tabs>
          <FormDialog<ContactForm> open={adding} onOpenChange={setAdding} title="Add contact" schema={contactSchema} defaultValues={{ name: "", position: "", phone: "", email: "" }} fields={[{ name: "name", label: "Name", required: true }, { name: "position", label: "Position" }, { name: "phone", label: "Phone", type: "tel" }, { name: "email", label: "Email", type: "email" }]} onSubmit={(v) => saveContacts.run([...s.contacts, { ...v, id: crypto.randomUUID() }])} />
        </>
      )}
    </RequirePermission>
  );
}
