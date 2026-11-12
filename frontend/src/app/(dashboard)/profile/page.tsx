"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { FormDialog, FormFields } from "@/components/shared/form-dialog";
import { Fields, PageHeader, SectionTitle } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { formatDateTime } from "@/lib/format";
import { authApi, usersApi } from "@/services";
import { useAuthStore } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";

const schema = z.object({ fullName: z.string().min(1, "Name is required."), phone: z.string(), language: z.enum(["en", "km"]) });
type V = z.infer<typeof schema>;
const passwordSchema = z.object({ currentPassword: z.string().min(1, "Enter your current password."), newPassword: z.string().min(12, "Password must be at least 12 characters.") });
type P = z.infer<typeof passwordSchema>;
const pinSchema = z.object({ pin: z.string().regex(/^\d{4,6}$/, "PIN must be 4 to 6 digits.") });
type Q = z.infer<typeof pinSchema>;

export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const setLanguage = useUiStore((s) => s.setLanguage);
  const sessions = useApiQuery(["sessions"], authApi.sessions);
  const [dialog, setDialog] = useState<"password" | "pin" | null>(null);
  const form = useForm<V>({ resolver: zodResolver(schema) as never, defaultValues: { fullName: user?.fullName ?? "", phone: user?.phone ?? "", language: user?.language ?? "en" } });
  const save = useApiMutation((v: V) => authApi.updateMe(v), { success: "Profile saved", onSuccess: (u) => { setUser(u); setLanguage(u.language); } });
  const password = useApiMutation((v: P) => authApi.changePassword(v.currentPassword, v.newPassword), { success: "Password changed", silentError: true });
  const pin = useApiMutation((v: Q) => usersApi.setPin(user?.id ?? "", v.pin), { success: "PIN changed", silentError: true });
  const revoke = useApiMutation((id: string) => authApi.revokeSession(id), { success: "Session revoked" });
  if (!user) return null;
  return (
    <>
      <PageHeader title="Profile" description={user.roles.map((r) => r.name).join(", ")} />
      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="gap-3 rounded-lg p-4 shadow-none">
          <SectionTitle>Details</SectionTitle>
          <form onSubmit={form.handleSubmit((v) => void save.fire(v))} className="space-y-3">
            <FormFields form={form as never} idPrefix="profile" fields={[{ name: "fullName", label: "Full name", required: true }, { name: "phone", label: "Phone", type: "tel" }, { name: "language", label: "Language", type: "select", options: [{ value: "en", label: "English" }, { value: "km", label: "Khmer" }] }] as never} />
            <Button type="submit" size="sm" disabled={save.isPending}>Save</Button>
          </form>
          <Fields items={[["Username", user.username], ["Email", user.email], ["Last sign-in", formatDateTime(user.lastLoginAt)]]} />
          <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setDialog("password")}>Change password</Button><Button size="sm" variant="outline" onClick={() => setDialog("pin")}>Change PIN</Button></div>
        </Card>
        <Card className="gap-2 rounded-lg p-4 shadow-none">
          <SectionTitle>Active sessions</SectionTitle>
          <ul className="divide-y">{(sessions.data ?? []).filter((s) => s.userId === user.id).map((s) => <li key={s.id} className="flex items-center justify-between gap-2 py-2 text-sm"><span className="min-w-0"><span className="block truncate">{s.device}</span><span className="block text-xs text-muted-foreground">Started {formatDateTime(s.createdAt)}</span></span><Button size="sm" variant="ghost" onClick={() => void revoke.fire(s.id)}>Revoke</Button></li>)}</ul>
        </Card>
      </div>
      <FormDialog<P> open={dialog === "password"} onOpenChange={(o) => !o && setDialog(null)} title="Change password" schema={passwordSchema} defaultValues={{ currentPassword: "", newPassword: "" }} fields={[{ name: "currentPassword", label: "Current password", type: "password", required: true, full: true }, { name: "newPassword", label: "New password", type: "password", required: true, full: true, help: "At least 12 characters." }]} onSubmit={(v) => password.run(v)} />
      <FormDialog<Q> open={dialog === "pin"} onOpenChange={(o) => !o && setDialog(null)} title="Change POS PIN" schema={pinSchema} defaultValues={{ pin: "" }} fields={[{ name: "pin", label: "New PIN", type: "password", required: true, full: true, help: "4 to 6 digits, not sequential." }]} onSubmit={(v) => pin.run(v)} />
    </>
  );
}
