"use client";

import { z } from "zod";
import { CrudPanel } from "@/components/shared/crud-panel";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { brandsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Brand } from "@/types";

const schema = z.object({ code: z.string().min(1, "Code is required."), name: z.string().min(1, "Name is required."), status: z.enum(["ACTIVE", "INACTIVE"]) });
type V = z.infer<typeof schema>;

export default function BrandsPage() {
  const can = useCan();
  return (
    <RequirePermission anyOf={["products.view"]}>
      <PageHeader title="Brands" />
      <CrudPanel<Brand, V, Partial<Brand>>
        queryKey="brands" singular="Brand" api={brandsApi} canManage={can("products.create", "products.edit")} exportName="brands" schema={schema} empty={{ code: "", name: "", status: "ACTIVE" }}
        columns={[{ id: "code", header: "Code", value: (b) => b.code, cell: (b) => <span className="font-mono text-xs">{b.code}</span> }, { id: "name", header: "Name", value: (b) => b.name }, { id: "status", header: "Status", value: (b) => b.status, cell: (b) => <StatusBadge status={b.status} /> }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] }]}
        toForm={(b) => ({ code: b.code, name: b.name, status: b.status })} toPayload={(v) => v}
      />
    </RequirePermission>
  );
}
