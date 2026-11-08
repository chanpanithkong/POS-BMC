"use client";

import { z } from "zod";
import { CrudPanel } from "@/components/shared/crud-panel";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { useBranchOptions } from "@/hooks/use-lookups";
import { employeesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { Employee } from "@/types";

const schema = z.object({ code: z.string().min(1, "Code is required."), nameEn: z.string().min(1, "Name is required."), nameKm: z.string(), position: z.string(), branchId: z.string().min(1, "Select a branch."), phone: z.string(), status: z.enum(["ACTIVE", "INACTIVE"]) });
type V = z.infer<typeof schema>;

export default function EmployeesPage() {
  const can = useCan();
  const branches = useBranchOptions();
  return (
    <RequirePermission anyOf={["users.view"]}>
      <PageHeader title="Employees" description="Employee profiles are separate from user accounts" />
      <CrudPanel<Employee, V, Partial<Employee>>
        queryKey="employees" singular="Employee" api={employeesApi} canManage={can("users.manage")} exportName="employees" schema={schema} empty={{ code: "", nameEn: "", nameKm: "", position: "", branchId: "", phone: "", status: "ACTIVE" }}
        columns={[{ id: "code", header: "Code", value: (e) => e.code, cell: (e) => <span className="font-mono text-xs">{e.code}</span> }, { id: "name", header: "Name", value: (e) => e.nameEn }, { id: "position", header: "Position", value: (e) => e.position, hideBelow: "sm" }, { id: "branch", header: "Branch", value: (e) => branches.find((b) => b.value === e.branchId)?.label, hideBelow: "md" }, { id: "phone", header: "Phone", value: (e) => e.phone, hideBelow: "lg" }, { id: "status", header: "Status", value: (e) => e.status, cell: (e) => <StatusBadge status={e.status} /> }]}
        fields={[{ name: "code", label: "Code", required: true }, { name: "nameEn", label: "Name (English)", required: true }, { name: "nameKm", label: "Name (Khmer)" }, { name: "position", label: "Position" }, { name: "branchId", label: "Branch", type: "select", required: true, options: branches }, { name: "phone", label: "Phone", type: "tel" }, { name: "status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] }]}
        toForm={(e) => ({ code: e.code, nameEn: e.nameEn, nameKm: e.nameKm, position: e.position, branchId: e.branchId, phone: e.phone, status: e.status })} toPayload={(v) => v}
      />
    </RequirePermission>
  );
}
