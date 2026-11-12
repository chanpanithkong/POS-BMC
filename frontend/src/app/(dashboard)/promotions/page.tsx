"use client";

import { Check, Plus } from "lucide-react";
import { useState } from "react";
import { z } from "zod";
import { CrudPanel } from "@/components/shared/crud-panel";
import { type Column, DataTable } from "@/components/shared/data-table";
import { FormDialog } from "@/components/shared/form-dialog";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchOptions, useCategoryOptions } from "@/hooks/use-lookups";
import { formatDate, titleCase, todayIso, addDaysIso } from "@/lib/format";
import { useProducts } from "@/components/shared/line-items";
import { couponsApi, promotionsApi, settingsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Coupon, Promotion } from "@/types";

const promoSchema = z.object({
  code: z.string().min(1, "Code is required."), name: z.string().min(1, "Name is required."), type: z.enum(["PRODUCT", "CATEGORY", "BOGO", "ORDER", "TIME_BASED"]), discountPct: z.number({ error: "Enter a number." }).min(0).max(100), discountAmount: z.number({ error: "Enter a number." }).min(0),
  productId: z.string(), categoryId: z.string(), branchId: z.string(), startDate: z.string().min(1, "Enter a date."), endDate: z.string().min(1, "Enter a date."), startTime: z.string(), endTime: z.string(), priority: z.number({ error: "Enter a number." }).int(), combinable: z.boolean(), usageLimit: z.number().int().min(0).optional(),
}).refine((v) => v.endDate >= v.startDate, { path: ["endDate"], message: "End date must be on or after the start date." });
type PromoForm = z.infer<typeof promoSchema>;

const couponSchema = z.object({ code: z.string().min(1, "Code is required."), description: z.string(), discountPct: z.number({ error: "Enter a number." }).min(0).max(100), discountAmount: z.number({ error: "Enter a number." }).min(0), minSpend: z.number({ error: "Enter a number." }).min(0), startDate: z.string().min(1, "Enter a date."), endDate: z.string().min(1, "Enter a date."), usageLimit: z.number({ error: "Enter a number." }).int().min(1), perCustomerLimit: z.number({ error: "Enter a number." }).int().min(1), status: z.enum(["ACTIVE", "INACTIVE"]) });
type CouponForm = z.infer<typeof couponSchema>;

const loyaltySchema = z.object({ loyaltyEnabled: z.boolean(), loyaltyPointsPerUsd: z.number({ error: "Enter a number." }).min(0) });
type LoyaltyForm = z.infer<typeof loyaltySchema>;

const EMPTY: PromoForm = { code: "", name: "", type: "CATEGORY", discountPct: 10, discountAmount: 0, productId: "", categoryId: "", branchId: "", startDate: todayIso(), endDate: addDaysIso(todayIso(), 14), startTime: "", endTime: "", priority: 10, combinable: false, usageLimit: undefined };

export default function PromotionsPage() {
  const can = useCan();
  const manage = can("promotions.manage");
  const query = useApiQuery(["promotions"], () => promotionsApi.list());
  const settings = useApiQuery(["settings"], settingsApi.get);
  const categories = useCategoryOptions();
  const branches = useBranchOptions();
  const products = useProducts();
  const [open, setOpen] = useState(false);
  const [loyaltyOpen, setLoyaltyOpen] = useState(false);
  const toPayload = (v: PromoForm): Partial<Promotion> => ({ code: v.code, name: v.name, type: v.type, discountPct: v.discountPct, discountAmount: v.discountAmount, productIds: v.productId ? [v.productId] : [], categoryIds: v.categoryId ? [v.categoryId] : [], branchIds: v.branchId ? [v.branchId] : [], customerGroupIds: [], startDate: v.startDate, endDate: v.endDate, startTime: v.startTime || null, endTime: v.endTime || null, priority: v.priority, combinable: v.combinable, usageLimit: v.usageLimit ?? null });
  const create = useApiMutation((v: PromoForm) => promotionsApi.create(toPayload(v)), { success: "Promotion sent for approval", silentError: true });
  const approve = useApiMutation((id: string) => promotionsApi.approve(id), { success: "Promotion approved" });
  const disable = useApiMutation((id: string) => promotionsApi.disable(id), { success: "Promotion disabled" });
  const saveLoyalty = useApiMutation((v: LoyaltyForm) => settingsApi.update(v), { success: "Loyalty settings saved", silentError: true });

  const columns: Column<Promotion>[] = [
    { id: "code", header: "Code", value: (p) => p.code, cell: (p) => <span className="font-mono text-xs">{p.code}</span> },
    { id: "name", header: "Name", value: (p) => p.name },
    { id: "type", header: "Type", value: (p) => titleCase(p.type), hideBelow: "md" },
    { id: "value", header: "Value", value: (p) => (p.type === "BOGO" ? "Buy 1 get 1" : p.discountPct ? `${p.discountPct}%` : `$${p.discountAmount}`), hideBelow: "sm" },
    { id: "dates", header: "Dates", value: (p) => p.startDate, cell: (p) => `${formatDate(p.startDate)} to ${formatDate(p.endDate)}`, hideBelow: "lg" },
    { id: "priority", header: "Priority", value: (p) => p.priority, align: "right", hideBelow: "lg" },
    { id: "used", header: "Used", value: (p) => p.usageCount, align: "right", hideBelow: "md" },
    { id: "status", header: "Status", value: (p) => p.status, cell: (p) => <StatusBadge status={p.status} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (p) => manage ? <div className="flex justify-end gap-1">{p.status === "PENDING_APPROVAL" ? <Button size="sm" variant="outline" onClick={() => void approve.fire(p.id)}><Check />Approve</Button> : null}{p.status === "ACTIVE" ? <Button size="sm" variant="ghost" onClick={() => void disable.fire(p.id)}>Disable</Button> : null}</div> : null },
  ];

  return (
    <RequirePermission anyOf={["promotions.view"]}>
      <PageHeader title="Promotions and loyalty" description="One promotion per line, best for the customer unless priority says otherwise" />
      <Tabs defaultValue="promos">
        <TabsList><TabsTrigger value="promos">Promotions</TabsTrigger><TabsTrigger value="coupons">Coupons</TabsTrigger><TabsTrigger value="loyalty">Loyalty</TabsTrigger></TabsList>
        <TabsContent value="promos">
          <DataTable data={query.data} columns={columns} getRowId={(p) => p.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="promotions" searchPlaceholder="Code or name" emptyTitle="No promotions yet" filters={[{ id: "status", label: "Statuses", options: ["PENDING_APPROVAL", "ACTIVE", "EXPIRED", "DISABLED"].map((value) => ({ value, label: titleCase(value) })), value: (p) => p.status }]} toolbar={manage ? <Button size="sm" onClick={() => setOpen(true)}><Plus />New promotion</Button> : undefined} />
        </TabsContent>
        <TabsContent value="coupons">
          <CrudPanel<Coupon, CouponForm, Partial<Coupon>> queryKey="coupons" singular="Coupon" api={couponsApi} canManage={manage} schema={couponSchema} exportName="coupons" canDelete={(c) => c.usageCount === 0}
            empty={{ code: "", description: "", discountPct: 0, discountAmount: 1, minSpend: 0, startDate: todayIso(), endDate: addDaysIso(todayIso(), 30), usageLimit: 100, perCustomerLimit: 1, status: "ACTIVE" }}
            columns={[{ id: "code", header: "Code", value: (c) => c.code, cell: (c) => <span className="font-mono text-xs">{c.code}</span> }, { id: "desc", header: "Description", value: (c) => c.description, hideBelow: "md" }, { id: "used", header: "Used", value: (c) => c.usageCount, cell: (c) => `${c.usageCount} / ${c.usageLimit}`, align: "right" }, { id: "end", header: "Ends", value: (c) => c.endDate, cell: (c) => formatDate(c.endDate) }, { id: "status", header: "Status", value: (c) => c.status, cell: (c) => <StatusBadge status={c.status} /> }]}
            fields={[{ name: "code", label: "Code", required: true }, { name: "description", label: "Description" }, { name: "discountPct", label: "Discount %", type: "number" }, { name: "discountAmount", label: "Discount amount (USD)", type: "number" }, { name: "minSpend", label: "Minimum spend (USD)", type: "number" }, { name: "usageLimit", label: "Usage limit", type: "number" }, { name: "perCustomerLimit", label: "Limit per customer", type: "number" }, { name: "status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] }, { name: "startDate", label: "Start", type: "date" }, { name: "endDate", label: "End", type: "date" }]}
            toForm={(c) => ({ code: c.code, description: c.description, discountPct: c.discountPct, discountAmount: c.discountAmount, minSpend: c.minSpend, startDate: c.startDate, endDate: c.endDate, usageLimit: c.usageLimit, perCustomerLimit: c.perCustomerLimit, status: c.status })}
            toPayload={(v, row) => ({ ...v, usageCount: row?.usageCount ?? 0 })} />
        </TabsContent>
        <TabsContent value="loyalty">
          <Card className="max-w-lg gap-3 rounded-lg p-4 shadow-none">
            <p className="text-sm">Loyalty is <strong>{settings.data?.loyaltyEnabled ? "on" : "off"}</strong>. Customers earn {settings.data?.loyaltyPointsPerUsd} point per USD on finalized sales. Points reverse proportionally on returns.</p>
            <p className="text-xs text-muted-foreground">Tiers: Member, Silver from 500 points, Gold from 2,000 points.</p>
            {can("settings.manage") ? <div><Button size="sm" variant="outline" onClick={() => setLoyaltyOpen(true)}>Edit settings</Button></div> : null}
          </Card>
        </TabsContent>
      </Tabs>
      <FormDialog<PromoForm> open={open} onOpenChange={setOpen} title="New promotion" description="Promotions take effect after approval." schema={promoSchema} defaultValues={EMPTY} wide onSubmit={(v) => create.run(v)} submitLabel="Submit for approval"
        fields={[
          { name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true },
          { name: "type", label: "Type", type: "select", options: [{ value: "PRODUCT", label: "Product" }, { value: "CATEGORY", label: "Category" }, { value: "BOGO", label: "Buy one get one" }, { value: "ORDER", label: "Order level" }, { value: "TIME_BASED", label: "Time based" }] },
          { name: "branchId", label: "Branch", type: "select", allowNone: "All branches", options: branches },
          { name: "productId", label: "Product", type: "select", full: true, options: products.map((p) => ({ value: p.id, label: p.nameEn })), visible: (v) => v.type === "PRODUCT" || v.type === "BOGO" },
          { name: "categoryId", label: "Category", type: "select", options: categories, visible: (v) => v.type === "CATEGORY" },
          { name: "discountPct", label: "Discount %", type: "number", visible: (v) => v.type !== "BOGO" }, { name: "discountAmount", label: "Discount amount (USD)", type: "number", visible: (v) => v.type !== "BOGO" },
          { name: "startDate", label: "Start date", type: "date", required: true }, { name: "endDate", label: "End date", type: "date", required: true },
          { name: "startTime", label: "Start time", type: "time", visible: (v) => v.type === "TIME_BASED" }, { name: "endTime", label: "End time", type: "time", visible: (v) => v.type === "TIME_BASED" },
          { name: "priority", label: "Priority", type: "number" }, { name: "usageLimit", label: "Usage limit (blank = none)", type: "number" },
          { name: "combinable", label: "Can combine with manual discounts", type: "switch", full: true },
        ]} />
      <FormDialog<LoyaltyForm> open={loyaltyOpen} onOpenChange={setLoyaltyOpen} title="Loyalty settings" schema={loyaltySchema} onSubmit={(v) => saveLoyalty.run(v)}
        defaultValues={{ loyaltyEnabled: settings.data?.loyaltyEnabled ?? true, loyaltyPointsPerUsd: settings.data?.loyaltyPointsPerUsd ?? 1 }}
        fields={[{ name: "loyaltyEnabled", label: "Loyalty enabled", type: "switch", full: true }, { name: "loyaltyPointsPerUsd", label: "Points per USD", type: "number" }]} />
    </RequirePermission>
  );
}
