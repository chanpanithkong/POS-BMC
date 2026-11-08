"use client";

import { z } from "zod";
import { CrudPanel } from "@/components/shared/crud-panel";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { useApiQuery } from "@/hooks/use-api";
import { customerGroupsApi, pricingApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { CustomerGroup } from "@/types";

const schema = z.object({ code: z.string().min(1, "Code is required."), name: z.string().min(1, "Name is required."), priceListId: z.string(), discountPct: z.number({ error: "Enter a number." }).min(0).max(100), status: z.enum(["ACTIVE", "INACTIVE"]) });
type V = z.infer<typeof schema>;

export default function CustomerGroupsPage() {
  const can = useCan();
  const lists = useApiQuery(["price-lists"], pricingApi.lists, { enabled: can("pricing.view") });
  return (
    <RequirePermission anyOf={["customers.view"]}>
      <PageHeader title="Customer groups" description="Link groups to a price list or a standing discount" />
      <CrudPanel<CustomerGroup, V, Partial<CustomerGroup>>
        queryKey="customer-groups" singular="Group" api={customerGroupsApi} canManage={can("customers.manage")} exportName="customer-groups" schema={schema} empty={{ code: "", name: "", priceListId: "", discountPct: 0, status: "ACTIVE" }}
        columns={[{ id: "code", header: "Code", value: (g) => g.code, cell: (g) => <span className="font-mono text-xs">{g.code}</span> }, { id: "name", header: "Name", value: (g) => g.name }, { id: "list", header: "Price list", value: (g) => lists.data?.find((l) => l.id === g.priceListId)?.name ?? "Standard" }, { id: "disc", header: "Discount", value: (g) => g.discountPct, cell: (g) => `${g.discountPct}%`, align: "right" }, { id: "status", header: "Status", value: (g) => g.status, cell: (g) => <StatusBadge status={g.status} /> }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "priceListId", label: "Price list", type: "select", allowNone: "Standard", options: (lists.data ?? []).map((l) => ({ value: l.id, label: l.name })) }, { name: "discountPct", label: "Discount %", type: "number" }, { name: "status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] }]}
        toForm={(g) => ({ code: g.code, name: g.name, priceListId: g.priceListId ?? "", discountPct: g.discountPct, status: g.status })} toPayload={(v) => ({ ...v, priceListId: v.priceListId || null })}
      />
    </RequirePermission>
  );
}
