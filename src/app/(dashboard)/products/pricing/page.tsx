"use client";

import { AlertTriangle, Eye, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { useProducts } from "@/components/shared/line-items";
import { PageHeader, RequirePermission } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchOptions, useBrandOptions, useCategoryOptions, useCustomerGroupOptions, useUnits } from "@/hooks/use-lookups";
import { getErrorMessage } from "@/lib/api/errors";
import { formatDateTime, formatUsd } from "@/lib/format";
import { type BulkPriceInput, pricingApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { BulkPricePreviewRow, PriceHistoryEntry, ProductPrice } from "@/types";

const schema = z.object({
  productId: z.string().min(1, "Select a product."), unitId: z.string().min(1, "Select a unit."), scope: z.enum(["RETAIL", "WHOLESALE", "BRANCH", "GROUP"]), branchId: z.string(), customerGroupId: z.string(),
  price: z.number({ error: "Enter a price." }).min(0, "Price must not be negative."), effectiveFrom: z.string().min(1, "Choose a start time."), effectiveTo: z.string(),
});
type V = z.infer<typeof schema>;

export default function PricingPage() {
  const can = useCan();
  const canEdit = can("pricing.edit");
  const { confirm } = useDialogs();
  const lists = useApiQuery(["price-lists"], pricingApi.lists);
  const prices = useApiQuery(["prices"], pricingApi.prices);
  const history = useApiQuery(["price-history"], pricingApi.history);
  const products = useProducts();
  const units = useUnits();
  const branches = useBranchOptions();
  const groups = useCustomerGroupOptions();
  const categories = useCategoryOptions();
  const brands = useBrandOptions();
  const [open, setOpen] = useState(false);
  const [bulk, setBulk] = useState<{ categoryId: string; brandId: string; mode: "PERCENT" | "AMOUNT"; value: string; effectiveFrom: string }>({ categoryId: "all", brandId: "all", mode: "PERCENT", value: "", effectiveFrom: "" });
  const [preview, setPreview] = useState<BulkPricePreviewRow[] | null>(null);

  const create = useApiMutation((v: V) => {
    const list = lists.data?.find((l) => l.type === (v.scope === "WHOLESALE" ? "WHOLESALE" : "RETAIL"));
    return pricingApi.create({ productId: v.productId, unitId: v.unitId, priceListId: v.scope === "BRANCH" || v.scope === "GROUP" ? null : (list?.id ?? null), branchId: v.scope === "BRANCH" ? v.branchId || null : null, customerGroupId: v.scope === "GROUP" ? v.customerGroupId || null : null, price: v.price, effectiveFrom: new Date(v.effectiveFrom).toISOString(), effectiveTo: v.effectiveTo ? new Date(v.effectiveTo).toISOString() : null });
  }, { success: "Price saved", silentError: true });
  const remove = useApiMutation((id: string) => pricingApi.remove(id), { success: "Scheduled price removed" });
  const toInput = (): BulkPriceInput => ({ categoryId: bulk.categoryId === "all" ? undefined : bulk.categoryId, brandId: bulk.brandId === "all" ? undefined : bulk.brandId, mode: bulk.mode, value: Number(bulk.value), effectiveFrom: bulk.effectiveFrom || undefined });
  const apply = useApiMutation(() => pricingApi.bulkApply(toInput()), { success: (r) => `${r.updated} prices ${r.scheduled ? "scheduled" : "updated"}`, onSuccess: () => setPreview(null) });

  const runPreview = async () => {
    if (!bulk.value || Number.isNaN(Number(bulk.value))) {
      toast.error("Enter a percentage or amount.");
      return;
    }
    try {
      setPreview(await pricingApi.bulkPreview(toInput()));
    } catch (e) {
      toast.error(getErrorMessage(e));
    }
  };

  const priceColumns: Column<ProductPrice>[] = [
    { id: "sku", header: "SKU", value: (p) => p.sku, cell: (p) => <span className="font-mono text-xs">{p.sku}</span> },
    { id: "product", header: "Product", value: (p) => p.productName },
    { id: "scope", header: "Scope", value: (p) => p.scopeLabel },
    { id: "price", header: "Price", value: (p) => p.price, cell: (p) => formatUsd(p.price), align: "right" },
    { id: "from", header: "Effective from", value: (p) => p.effectiveFrom, cell: (p) => formatDateTime(p.effectiveFrom), hideBelow: "md" },
    { id: "to", header: "Effective to", value: (p) => p.effectiveTo, cell: (p) => formatDateTime(p.effectiveTo), hideBelow: "lg" },
    { id: "by", header: "Created by", value: (p) => p.createdBy, hideBelow: "xl" },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, cell: (p) => (canEdit ? <Button variant="ghost" size="icon-sm" aria-label="Remove scheduled price" onClick={async () => { if (await confirm({ title: "Remove this price?", description: "Only prices that have not started can be removed.", confirmLabel: "Remove", destructive: true })) void remove.fire(p.id); }}><Trash2 /></Button> : null) },
  ];
  const historyColumns: Column<PriceHistoryEntry>[] = [
    { id: "at", header: "Changed", value: (h) => h.at, cell: (h) => formatDateTime(h.at) },
    { id: "product", header: "Product", value: (h) => h.productName },
    { id: "scope", header: "Scope", value: (h) => h.scope, hideBelow: "md" },
    { id: "old", header: "Old", value: (h) => h.oldPrice, cell: (h) => formatUsd(h.oldPrice), align: "right" },
    { id: "new", header: "New", value: (h) => h.newPrice, cell: (h) => formatUsd(h.newPrice), align: "right" },
    { id: "user", header: "User", value: (h) => h.userName, hideBelow: "lg" },
  ];
  const previewColumns: Column<BulkPricePreviewRow>[] = [
    { id: "sku", header: "SKU", value: (r) => r.sku, cell: (r) => <span className="font-mono text-xs">{r.sku}</span> },
    { id: "product", header: "Product", value: (r) => r.productName },
    { id: "cur", header: "Current", value: (r) => r.currentPrice, cell: (r) => formatUsd(r.currentPrice), align: "right" },
    { id: "new", header: "New", value: (r) => r.newPrice, cell: (r) => formatUsd(r.newPrice), align: "right" },
    { id: "margin", header: "Margin", value: (r) => r.marginPct, cell: (r) => (r.marginPct === null ? "—" : `${r.marginPct}%`), align: "right" },
    { id: "flag", header: "Check", value: (r) => (r.belowMin ? "Below minimum" : "OK"), cell: (r) => (r.belowMin ? <span className="inline-flex items-center gap-1 text-warning"><AlertTriangle className="size-3.5" />Below minimum</span> : "OK") },
  ];

  return (
    <RequirePermission anyOf={["pricing.view"]}>
      <PageHeader title="Pricing" description="Resolved in order: override, promotion, customer group, branch, standard or wholesale" />
      <Tabs defaultValue="rules">
        <TabsList><TabsTrigger value="rules">Price rules</TabsTrigger>{canEdit ? <TabsTrigger value="bulk">Bulk update</TabsTrigger> : null}<TabsTrigger value="history">History</TabsTrigger></TabsList>
        <TabsContent value="rules">
          <DataTable data={prices.data} columns={priceColumns} getRowId={(p) => p.id} isLoading={prices.isLoading} error={prices.error} onRetry={() => void prices.refetch()} exportName="prices" emptyTitle="No special prices yet" emptyDescription="Products use their standard retail price until you add a branch, group or scheduled price." toolbar={canEdit ? <Button size="sm" onClick={() => setOpen(true)}><Plus />New price</Button> : undefined} />
        </TabsContent>
        {canEdit ? (
          <TabsContent value="bulk" className="space-y-3">
            <Card className="gap-3 rounded-lg p-4 shadow-none">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                <div className="space-y-1"><Label>Category</Label><Select value={bulk.categoryId} onValueChange={(v) => setBulk((b) => ({ ...b, categoryId: v }))}><SelectTrigger className="w-full" aria-label="Category"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All categories</SelectItem>{categories.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent></Select></div>
                <div className="space-y-1"><Label>Brand</Label><Select value={bulk.brandId} onValueChange={(v) => setBulk((b) => ({ ...b, brandId: v }))}><SelectTrigger className="w-full" aria-label="Brand"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All brands</SelectItem>{brands.map((c) => <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>)}</SelectContent></Select></div>
                <div className="space-y-1"><Label>Change by</Label><Select value={bulk.mode} onValueChange={(v) => setBulk((b) => ({ ...b, mode: v as "PERCENT" | "AMOUNT" }))}><SelectTrigger className="w-full" aria-label="Change by"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="PERCENT">Percent</SelectItem><SelectItem value="AMOUNT">Amount (USD)</SelectItem></SelectContent></Select></div>
                <div className="space-y-1"><Label htmlFor="bulk-value">Value</Label><Input id="bulk-value" type="number" step="any" placeholder="5 or -5" value={bulk.value} onChange={(e) => setBulk((b) => ({ ...b, value: e.target.value }))} /></div>
                <div className="space-y-1"><Label htmlFor="bulk-date">Effective (blank = now)</Label><Input id="bulk-date" type="datetime-local" value={bulk.effectiveFrom} onChange={(e) => setBulk((b) => ({ ...b, effectiveFrom: e.target.value }))} /></div>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => void runPreview()}><Eye />Preview</Button>
                <Button disabled={!preview?.length || apply.isPending} onClick={async () => { if (await confirm({ title: `Update ${preview?.length} prices?`, description: "Completed sales keep their original prices. Held sales re-price when resumed.", confirmLabel: "Apply" })) void apply.fire(undefined); }}>Apply changes</Button>
              </div>
            </Card>
            {preview ? <DataTable data={preview} columns={previewColumns} getRowId={(r) => r.productId} exportName="price-preview" /> : null}
          </TabsContent>
        ) : null}
        <TabsContent value="history"><DataTable data={history.data} columns={historyColumns} getRowId={(h) => h.id} isLoading={history.isLoading} error={history.error} exportName="price-history" emptyTitle="No price changes yet" /></TabsContent>
      </Tabs>
      <FormDialog<V> open={open} onOpenChange={setOpen} title="New price" description="Overlapping prices for the same scope are rejected." schema={schema} wide submitLabel="Save price" onSubmit={(v) => create.run(v)}
        defaultValues={{ productId: "", unitId: "", scope: "BRANCH", branchId: "", customerGroupId: "", price: 0, effectiveFrom: "", effectiveTo: "" }}
        fields={[
          { name: "productId", label: "Product", type: "select", required: true, full: true, options: products.map((p) => ({ value: p.id, label: `${p.sku} - ${p.nameEn}` })) },
          { name: "unitId", label: "Unit", type: "select", required: true, options: units.map((u) => ({ value: u.id, label: u.code })) },
          { name: "scope", label: "Scope", type: "select", options: [{ value: "RETAIL", label: "Standard retail" }, { value: "WHOLESALE", label: "Wholesale" }, { value: "BRANCH", label: "Branch" }, { value: "GROUP", label: "Customer group" }] },
          { name: "branchId", label: "Branch", type: "select", options: branches, visible: (v) => v.scope === "BRANCH" },
          { name: "customerGroupId", label: "Customer group", type: "select", options: groups, visible: (v) => v.scope === "GROUP" },
          { name: "price", label: "Price (USD)", type: "number", required: true },
          { name: "effectiveFrom", label: "Effective from", type: "datetime-local", required: true },
          { name: "effectiveTo", label: "Effective to (optional)", type: "datetime-local" },
        ]}
      />
    </RequirePermission>
  );
}
