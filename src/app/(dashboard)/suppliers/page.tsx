"use client";

import { Eye } from "lucide-react";
import Link from "next/link";
import { CrudPanel } from "@/components/shared/crud-panel";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { supplierFields, supplierSchema, emptySupplier, type SupplierForm, toSupplierForm } from "@/components/suppliers/supplier-form";
import { Button } from "@/components/ui/button";
import { formatUsd } from "@/lib/format";
import { suppliersApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Supplier } from "@/types";

export default function SuppliersPage() {
  const can = useCan();
  return (
    <RequirePermission anyOf={["suppliers.view"]}>
      <PageHeader title="Suppliers" description="Shared across branches, with purchase history and performance" />
      <CrudPanel<Supplier, SupplierForm, Partial<Supplier>>
        queryKey="suppliers" singular="Supplier" api={suppliersApi} canManage={can("suppliers.manage")} exportName="suppliers" schema={supplierSchema} empty={emptySupplier} wide searchPlaceholder="Code, name or phone"
        filters={[{ id: "status", label: "Statuses", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }], value: (s) => s.status }]}
        columns={[
          { id: "code", header: "Code", value: (s) => s.code, cell: (s) => <span className="font-mono text-xs">{s.code}</span> },
          { id: "name", header: "Name", value: (s) => s.nameEn, cell: (s) => <Link className="hover:underline" href={`/suppliers/${s.id}`}>{s.nameEn}</Link>, className: "max-w-64 truncate" },
          { id: "phone", header: "Phone", value: (s) => s.phone, hideBelow: "md" },
          { id: "terms", header: "Terms", value: (s) => s.paymentTerms, hideBelow: "lg" },
          { id: "open", header: "Open POs", value: (s) => s.openPoCount, align: "right", hideBelow: "md" },
          { id: "ontime", header: "On-time", value: (s) => s.onTimeRate, cell: (s) => (s.onTimeRate === null || s.onTimeRate === undefined ? "—" : `${s.onTimeRate}%`), align: "right", hideBelow: "lg" },
          { id: "owed", header: "Outstanding", value: (s) => s.outstandingBalance, cell: (s) => formatUsd(s.outstandingBalance), align: "right", hideBelow: "lg" },
          { id: "status", header: "Status", value: (s) => s.status, cell: (s) => <StatusBadge status={s.status} /> },
        ]}
        rowActions={(s) => <Button asChild variant="ghost" size="icon-sm"><Link href={`/suppliers/${s.id}`} aria-label={`View ${s.nameEn}`}><Eye /></Link></Button>}
        fields={supplierFields} toForm={toSupplierForm} toPayload={(v) => v}
      />
    </RequirePermission>
  );
}
