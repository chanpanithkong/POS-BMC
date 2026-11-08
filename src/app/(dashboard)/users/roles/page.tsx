"use client";

import { AlertTriangle, Plus, Save, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { z } from "zod";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { NumberCell } from "@/components/shared/line-items";
import { PageHeader, RequirePermission } from "@/components/shared/page";
import { ErrorState, PageSkeleton } from "@/components/shared/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { PERMISSION_GROUPS, SOD_CONFLICTS } from "@/constants/roles";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { cn } from "@/lib/utils";
import { rolesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import { PERMISSIONS, type Permission, type Role, type RoleLimits } from "@/types";

const schema = z.object({ name: z.string().min(1, "Name is required."), description: z.string() });
type V = z.infer<typeof schema>;
const LIMIT_LABELS: [keyof RoleLimits, string][] = [["discountPct", "Discount %"], ["overrideAmount", "Price override (USD)"], ["refundAmount", "Refund (USD)"], ["adjustmentValue", "Adjustment value (USD)"], ["poApprovalLimit", "PO approval (USD)"]];

export default function RolesPage() {
  const can = useCan();
  const manage = can("roles.manage");
  const { confirm } = useDialogs();
  const query = useApiQuery(["roles"], () => rolesApi.list());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, { permissions: Permission[]; limits: RoleLimits }>>({});
  const [creating, setCreating] = useState(false);
  const role = query.data?.find((r) => r.id === (selectedId ?? query.data?.[0]?.id));
  const current = role ? (edits[role.id] ?? { permissions: role.permissions, limits: role.limits }) : null;
  const dirty = Boolean(role && edits[role.id]);

  const save = useApiMutation((r: Role) => rolesApi.update(r.id, edits[r.id]), { success: "Role saved", onSuccess: (r) => setEdits(({ [r.id]: _dropped, ...rest }) => { void _dropped; return rest; }) });
  const create = useApiMutation((v: V) => rolesApi.create({ ...v, code: "CUSTOM", system: false, permissions: [], limits: { discountPct: 0, overrideAmount: 0, refundAmount: 0, adjustmentValue: 0, poApprovalLimit: 0 } }), { success: "Role created", silentError: true, onSuccess: (r) => setSelectedId(r.id) });
  const remove = useApiMutation((id: string) => rolesApi.remove(id), { success: "Role deleted", onSuccess: () => setSelectedId(null) });

  const granted = current?.permissions;
  const sod = useMemo(() => SOD_CONFLICTS.filter((c) => granted?.includes(c.a) && granted.includes(c.b)), [granted]);
  const toggle = (permission: Permission, on: boolean) => {
    if (!role || !current) return;
    setEdits((e) => ({ ...e, [role.id]: { ...current, permissions: on ? [...current.permissions, permission] : current.permissions.filter((p) => p !== permission) } }));
  };

  return (
    <RequirePermission anyOf={["users.view", "roles.manage"]}>
      <PageHeader title="Roles and permissions" description="Default roles follow the proposed SRS matrix, pending approval (D-12)" actions={manage ? <Button size="sm" onClick={() => setCreating(true)}><Plus />New role</Button> : undefined} />
      {query.error ? <Card className="rounded-lg shadow-none"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></Card> : !query.data || !role || !current ? <PageSkeleton /> : (
        <div className="grid min-w-0 gap-3 lg:grid-cols-[15rem_1fr]">
          <Card className="gap-0.5 rounded-lg p-2 shadow-none">
            {query.data.map((r) => <button key={r.id} type="button" onClick={() => setSelectedId(r.id)} aria-current={r.id === role.id} className={cn("flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm", r.id === role.id ? "bg-accent font-medium text-accent-foreground" : "hover:bg-muted")}><span className="truncate">{r.name}</span>{edits[r.id] ? <Badge variant="outline">Edited</Badge> : null}</button>)}
          </Card>
          <Card className="min-w-0 gap-3 rounded-lg p-4 shadow-none">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0"><h2 className="font-medium">{role.name}</h2><p className="text-sm text-muted-foreground">{role.description}</p></div>
              {manage ? <div className="flex gap-2">{!role.system ? <Button variant="outline" size="sm" onClick={async () => { if (await confirm({ title: `Delete ${role.name}?`, confirmLabel: "Delete", destructive: true })) void remove.fire(role.id); }}><Trash2 />Delete</Button> : null}<Button size="sm" disabled={!dirty || save.isPending} onClick={() => void save.fire(role)}><Save />Save</Button></div> : null}
            </div>
            {sod.map((c) => <p key={c.label} className="flex items-center gap-1.5 rounded-md bg-warning/10 p-2 text-sm text-warning"><AlertTriangle className="size-4 shrink-0" />SoD conflict: {c.label}</p>)}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
              {LIMIT_LABELS.map(([key, label]) => <div key={key} className="space-y-1"><Label className="text-xs">{label}</Label><NumberCell label={label} disabled={!manage} className="w-full" value={current.limits[key]} onChange={(v) => setEdits((e) => ({ ...e, [role.id]: { ...current, limits: { ...current.limits, [key]: v } } }))} /></div>)}
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {PERMISSION_GROUPS.map((group) => (
                <fieldset key={group.label} className="space-y-1 rounded-md border p-2.5">
                  <legend className="px-1 text-sm font-medium">{group.label}</legend>
                  {PERMISSIONS.filter((p) => group.prefix.some((x) => p.startsWith(x))).map((p) => <div key={p} className="flex items-center gap-2"><Checkbox id={p} disabled={!manage} checked={current.permissions.includes(p)} onCheckedChange={(c) => toggle(p, Boolean(c))} /><Label htmlFor={p} className="min-w-0 truncate font-mono text-xs font-normal">{p}</Label></div>)}
                </fieldset>
              ))}
            </div>
          </Card>
        </div>
      )}
      <FormDialog<V> open={creating} onOpenChange={setCreating} title="New custom role" schema={schema} defaultValues={{ name: "", description: "" }} fields={[{ name: "name", label: "Name", required: true, full: true }, { name: "description", label: "Description", full: true }]} onSubmit={(v) => create.run(v)} />
    </RequirePermission>
  );
}
