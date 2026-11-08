"use client";

import { AlertTriangle, KeyRound, LockOpen, MoreHorizontal, Pencil, Plus, Power } from "lucide-react";
import { useMemo, useState } from "react";
import { z } from "zod";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { SOD_CONFLICTS } from "@/constants/roles";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchOptions } from "@/hooks/use-lookups";
import { formatDateTime } from "@/lib/format";
import { rolesApi, usersApi } from "@/services";
import { useAuthStore, useCan } from "@/stores/auth-store";
import type { Role, User } from "@/types";

const schema = z.object({ fullName: z.string().min(1, "Name is required."), username: z.string().min(1, "Username is required."), email: z.email("Enter a valid email."), phone: z.string(), language: z.enum(["en", "km"]) });
type V = z.infer<typeof schema>;

function CheckList({ title, options, value, onChange }: { title: string; options: { value: string; label: string }[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <fieldset className="space-y-1.5 rounded-md border p-2.5">
      <legend className="px-1 text-sm font-medium">{title}</legend>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {options.map((o) => <div key={o.value} className="flex items-center gap-2"><Checkbox id={`${title}-${o.value}`} checked={value.includes(o.value)} onCheckedChange={(c) => onChange(c ? [...value, o.value] : value.filter((x) => x !== o.value))} /><Label htmlFor={`${title}-${o.value}`} className="font-normal">{o.label}</Label></div>)}
      </div>
    </fieldset>
  );
}

export default function UsersPage() {
  const can = useCan();
  const me = useAuthStore((s) => s.user);
  const manage = can("users.manage");
  const { confirm, prompt } = useDialogs();
  const query = useApiQuery(["users"], () => usersApi.list());
  const roles = useApiQuery(["roles"], () => rolesApi.list());
  const branches = useBranchOptions();
  const [editing, setEditing] = useState<User | null>(null);
  const [open, setOpen] = useState(false);
  const [roleIds, setRoleIds] = useState<string[]>([]);
  const [branchIds, setBranchIds] = useState<string[]>([]);

  const save = useApiMutation((v: V) => (editing ? usersApi.update(editing.id, { ...v, roleIds, branchIds }) : usersApi.create({ ...v, roleIds, branchIds })), { success: "User saved", silentError: true });
  const setStatus = useApiMutation(({ id, status }: { id: string; status: User["status"] }) => usersApi.setStatus(id, status), { success: "User updated" });
  const unlock = useApiMutation((id: string) => usersApi.unlock(id), { success: "User unlocked" });
  const setPin = useApiMutation(({ id, pin }: { id: string; pin: string }) => usersApi.setPin(id, pin), { success: "PIN updated" });

  const roleName = (id: string) => roles.data?.find((r: Role) => r.id === id)?.name ?? id;
  const sod = useMemo(() => {
    const perms = new Set((roles.data ?? []).filter((r) => roleIds.includes(r.id)).flatMap((r) => r.permissions));
    return SOD_CONFLICTS.filter((c) => perms.has(c.a) && perms.has(c.b));
  }, [roleIds, roles.data]);

  const start = (user: User | null) => {
    setEditing(user);
    setRoleIds(user?.roleIds ?? []);
    setBranchIds(user?.branchIds ?? []);
    setOpen(true);
  };

  const columns: Column<User>[] = [
    { id: "name", header: "Name", value: (u) => u.fullName },
    { id: "username", header: "Username", value: (u) => u.username, hideBelow: "md" },
    { id: "email", header: "Email", value: (u) => u.email, hideBelow: "lg" },
    { id: "roles", header: "Roles", value: (u) => u.roleIds.map(roleName).join(", ") },
    { id: "branches", header: "Branches", value: (u) => (u.branchIds.length ? `${u.branchIds.length} assigned` : "All"), hideBelow: "lg" },
    { id: "last", header: "Last sign-in", value: (u) => u.lastLoginAt, cell: (u) => formatDateTime(u.lastLoginAt), hideBelow: "xl" },
    { id: "status", header: "Status", value: (u) => u.status, cell: (u) => <StatusBadge status={u.lockedUntil && u.lockedUntil > new Date().toISOString() ? "REJECTED" : u.status} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (u) => manage ? (
      <DropdownMenu>
        <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`Actions for ${u.fullName}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => start(u)}><Pencil />Edit</DropdownMenuItem>
          <DropdownMenuItem onClick={async () => { const pin = await prompt({ title: `Reset PIN for ${u.fullName}`, description: "4 to 6 digits, unique within the branch, not sequential.", label: "New PIN", confirmLabel: "Save PIN" }); if (pin) void setPin.fire({ id: u.id, pin }); }}><KeyRound />Reset PIN</DropdownMenuItem>
          {u.lockedUntil ? <DropdownMenuItem onClick={() => void unlock.fire(u.id)}><LockOpen />Unlock</DropdownMenuItem> : null}
          {u.id !== me?.id ? <DropdownMenuItem variant={u.status === "ACTIVE" ? "destructive" : "default"} onClick={async () => { const next = u.status === "ACTIVE" ? "INACTIVE" : "ACTIVE"; if (next === "ACTIVE" || (await confirm({ title: `Deactivate ${u.fullName}?`, description: "Their sessions are revoked immediately. History is kept.", confirmLabel: "Deactivate", destructive: true }))) void setStatus.fire({ id: u.id, status: next }); }}><Power />{u.status === "ACTIVE" ? "Deactivate" : "Activate"}</DropdownMenuItem> : null}
        </DropdownMenuContent>
      </DropdownMenu>
    ) : null },
  ];

  return (
    <RequirePermission anyOf={["users.view"]}>
      <PageHeader title="Users" description="Access is scoped by role and branch. Nobody can change their own permissions." />
      <DataTable data={query.data} columns={columns} getRowId={(u) => u.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="users" searchPlaceholder="Name, username or role" filters={[{ id: "status", label: "Statuses", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }], value: (u) => u.status }]} toolbar={manage ? <Button size="sm" onClick={() => start(null)}><Plus />New user</Button> : undefined} />
      <FormDialog<V> open={open} onOpenChange={setOpen} title={editing ? "Edit user" : "New user"} description={editing ? undefined : "In demo mode new users sign in with demo-password."} schema={schema} wide onSubmit={(v) => save.run(v)}
        defaultValues={editing ? { fullName: editing.fullName, username: editing.username, email: editing.email, phone: editing.phone, language: editing.language } : { fullName: "", username: "", email: "", phone: "", language: "en" }}
        fields={[{ name: "fullName", label: "Full name", required: true }, { name: "username", label: "Username", required: true }, { name: "email", label: "Email", type: "email", required: true }, { name: "phone", label: "Phone", type: "tel" }, { name: "language", label: "Language", type: "select", options: [{ value: "en", label: "English" }, { value: "km", label: "Khmer" }] }]}
        extra={
          <div className="space-y-2">
            <CheckList title="Roles" options={(roles.data ?? []).map((r) => ({ value: r.id, label: r.name }))} value={roleIds} onChange={setRoleIds} />
            <CheckList title="Branches (none selected = all)" options={branches} value={branchIds} onChange={setBranchIds} />
            {sod.map((c) => <p key={c.label} className="flex items-center gap-1.5 rounded-md bg-warning/10 p-2 text-sm text-warning"><AlertTriangle className="size-4 shrink-0" />SoD conflict: {c.label}</p>)}
          </div>
        } />
    </RequirePermission>
  );
}
