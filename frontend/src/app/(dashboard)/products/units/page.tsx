"use client";

import { z } from "zod";
import { CrudPanel } from "@/components/shared/crud-panel";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { titleCase } from "@/lib/format";
import { unitsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Unit } from "@/types";

const schema = z.object({ code: z.string().min(1, "Code is required."), nameEn: z.string().min(1, "Name is required."), nameKm: z.string(), dimension: z.enum(["COUNT", "MASS", "VOLUME", "LENGTH"]), precision: z.number({ error: "Enter a number." }).int().min(0).max(4), status: z.enum(["ACTIVE", "INACTIVE"]) });
type V = z.infer<typeof schema>;

export default function UnitsPage() {
  const can = useCan();
  return (
    <RequirePermission anyOf={["products.view"]}>
      <PageHeader title="Units of measure" description="Product-specific conversions, such as carton to bottles, are set on each product" />
      <CrudPanel<Unit, V, Partial<Unit>>
        queryKey="units" singular="Unit" api={unitsApi} canManage={can("products.create", "products.edit")} exportName="units" schema={schema} empty={{ code: "", nameEn: "", nameKm: "", dimension: "COUNT", precision: 0, status: "ACTIVE" }}
        columns={[{ id: "code", header: "Code", value: (u) => u.code, cell: (u) => <span className="font-mono text-xs">{u.code}</span> }, { id: "name", header: "Name", value: (u) => u.nameEn }, { id: "km", header: "Khmer", value: (u) => u.nameKm, hideBelow: "sm" }, { id: "dim", header: "Dimension", value: (u) => titleCase(u.dimension) }, { id: "prec", header: "Decimals", value: (u) => u.precision, align: "right" }, { id: "status", header: "Status", value: (u) => u.status, cell: (u) => <StatusBadge status={u.status} /> }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "nameEn", label: "Name (English)", required: true }, { name: "nameKm", label: "Name (Khmer)" }, { name: "dimension", label: "Dimension", type: "select", options: ["COUNT", "MASS", "VOLUME", "LENGTH"].map((value) => ({ value, label: titleCase(value) })) }, { name: "precision", label: "Decimal precision", type: "number" }, { name: "status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] }]}
        toForm={(u) => ({ code: u.code, nameEn: u.nameEn, nameKm: u.nameKm, dimension: u.dimension, precision: u.precision, status: u.status })} toPayload={(v) => v}
      />
    </RequirePermission>
  );
}
