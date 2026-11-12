"use client";

import { z } from "zod";
import { CrudPanel } from "@/components/shared/crud-panel";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { useCategories, useTaxOptions } from "@/hooks/use-lookups";
import { categoriesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Category } from "@/types";

const schema = z.object({
  code: z.string().min(1, "Code is required."), nameEn: z.string().min(1, "Name is required."), nameKm: z.string(), parentId: z.string(), defaultTaxCodeId: z.string(),
  returnable: z.boolean(), returnWindowDays: z.number({ error: "Enter a number." }).int().min(0), allowNegativeStock: z.boolean(), expiryTrackingDefault: z.boolean(), minMarginPct: z.number({ error: "Enter a number." }).min(0), status: z.enum(["ACTIVE", "INACTIVE"]),
});
type V = z.infer<typeof schema>;
const empty: V = { code: "", nameEn: "", nameKm: "", parentId: "", defaultTaxCodeId: "", returnable: true, returnWindowDays: 7, allowNegativeStock: false, expiryTrackingDefault: false, minMarginPct: 0, status: "ACTIVE" };
const STATUS = [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }];

export default function CategoriesPage() {
  const can = useCan();
  const categories = useCategories();
  const taxOptions = useTaxOptions();
  const nameOf = (id: string | null) => categories.find((c) => c.id === id)?.nameEn ?? "";
  return (
    <RequirePermission anyOf={["products.view"]}>
      <PageHeader title="Categories" description="Hierarchical classification with tax, return and stock defaults" />
      <CrudPanel<Category, V, Partial<Category>>
        queryKey="categories" singular="Category" api={categoriesApi} canManage={can("products.create", "products.edit")} exportName="categories" schema={schema} empty={empty} wide
        canDelete={(c) => !categories.some((x) => x.parentId === c.id)}
        columns={[
          { id: "code", header: "Code", value: (c) => c.code, cell: (c) => <span className="font-mono text-xs">{c.code}</span> },
          { id: "name", header: "Name", value: (c) => c.nameEn },
          { id: "km", header: "Khmer", value: (c) => c.nameKm, hideBelow: "md" },
          { id: "parent", header: "Parent", value: (c) => nameOf(c.parentId), hideBelow: "md" },
          { id: "returns", header: "Returns", value: (c) => (c.returnable ? `${c.returnWindowDays} days` : "Not returnable"), hideBelow: "lg" },
          { id: "margin", header: "Min margin", value: (c) => c.minMarginPct, cell: (c) => `${c.minMarginPct}%`, align: "right", hideBelow: "lg" },
          { id: "status", header: "Status", value: (c) => c.status, cell: (c) => <StatusBadge status={c.status} /> },
        ]}
        fields={(row) => [
          { name: "code", label: "Code", required: true }, { name: "nameEn", label: "Name (English)", required: true }, { name: "nameKm", label: "Name (Khmer)" },
          { name: "parentId", label: "Parent category", type: "select", allowNone: "Top level", options: categories.filter((c) => c.id !== row?.id).map((c) => ({ value: c.id, label: c.nameEn })) },
          { name: "defaultTaxCodeId", label: "Default tax code", type: "select", allowNone: "Exempt", options: taxOptions },
          { name: "minMarginPct", label: "Minimum margin %", type: "number" },
          { name: "returnWindowDays", label: "Return window (days)", type: "number" },
          { name: "status", label: "Status", type: "select", options: STATUS },
          { name: "returnable", label: "Returnable", type: "switch" }, { name: "expiryTrackingDefault", label: "Track expiry by default", type: "switch" }, { name: "allowNegativeStock", label: "Allow negative stock", type: "switch" },
        ]}
        toForm={(c) => ({ code: c.code, nameEn: c.nameEn, nameKm: c.nameKm, parentId: c.parentId ?? "", defaultTaxCodeId: c.defaultTaxCodeId ?? "", returnable: c.returnable, returnWindowDays: c.returnWindowDays, allowNegativeStock: c.allowNegativeStock, expiryTrackingDefault: c.expiryTrackingDefault, minMarginPct: c.minMarginPct, status: c.status })}
        toPayload={(v, row) => ({ ...v, parentId: v.parentId || null, defaultTaxCodeId: v.defaultTaxCodeId || null, icon: row?.icon ?? "boxes" })}
      />
    </RequirePermission>
  );
}
