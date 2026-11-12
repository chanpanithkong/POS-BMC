"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Delete, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { LanguageToggle, ThemeToggle } from "@/components/layout/app-shell";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { isMockMode } from "@/lib/api/config";
import { getErrorMessage } from "@/lib/api/errors";
import { authApi } from "@/services";
import { useAuthStore } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";
import type { AuthResponse } from "@/types";

const schema = z.object({
  username: z.string().min(1, "Enter your username or email."),
  password: z.string().min(1, "Enter your password."),
});
type Values = z.infer<typeof schema>;

const DEMO_ACCOUNTS: [string, string][] = [
  ["owner", "Business Owner"], ["manager", "Store Manager"], ["branch", "Branch Manager"], ["cashier", "Cashier"], ["inventory", "Inventory Manager"], ["purchasing", "Purchasing Officer"], ["warehouse", "Warehouse Staff"], ["accountant", "Accountant"], ["auditor", "Auditor"], ["admin", "System Administrator"], ["sales", "Salesperson"], ["viewer", "Read-only User"],
];
const DEMO_TERMINALS = [["term-tk1", "Toul Kork Counter 1"], ["term-tk2", "Toul Kork Counter 2"], ["term-bk1", "BKK1 Counter 1"], ["term-sr1", "Siem Reap Counter 1"]];

export default function LoginPage() {
  const router = useRouter();
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const applyAuth = useAuthStore((s) => s.applyAuth);
  const setTerminal = useUiStore((s) => s.setTerminal);
  const savedTerminal = useUiStore((s) => s.terminalId);
  const { prompt } = useDialogs();
  const [mode, setMode] = useState<"password" | "pin">("password");
  const [error, setError] = useState<string | null>(null);
  const [pin, setPin] = useState("");
  const [pickedTerminal, setTerminalLocal] = useState<string | null>(null);
  // Live API: terminals cannot be listed before sign-in, so PIN sign-in uses the terminal this device chose at the POS.
  const terminal = pickedTerminal ?? savedTerminal ?? (isMockMode ? "term-tk1" : "");
  const [busy, setBusy] = useState(false);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { username: "", password: "" } });

  useEffect(() => {
    if (status === "authenticated" && user) router.replace(user.homePath);
  }, [router, status, user]);

  const finish = (auth: AuthResponse) => {
    applyAuth(auth);
    router.replace(auth.user.homePath);
  };

  const submit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      finish(await authApi.login(values.username, values.password));
    } catch (e) {
      setError(getErrorMessage(e));
    }
  });

  const submitPin = async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      setTerminal(terminal);
      finish(await authApi.pin(value, terminal));
    } catch (e) {
      setError(getErrorMessage(e));
      setPin("");
    } finally {
      setBusy(false);
    }
  };

  const press = (digit: string) => {
    const next = `${pin}${digit}`.slice(0, 6);
    setPin(next);
  };

  const forgot = async () => {
    const email = await prompt({ title: "Reset your password", description: "We will send a single-use link valid for 30 minutes.", label: "Email", confirmLabel: "Send link" });
    if (!email) return;
    try {
      toast.success((await authApi.forgotPassword(email)).message);
    } catch (e) {
      toast.error(getErrorMessage(e));
    }
  };

  const quick = (username: string) => {
    form.setValue("username", username);
    form.setValue("password", "demo-password");
    void submit();
  };

  return (
    <main className="relative grid min-h-svh place-items-center bg-background p-4">
      <div className="absolute top-3 right-3 flex items-center gap-1"><LanguageToggle /><ThemeToggle /></div>
      <div className="w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-md bg-primary text-sm font-bold text-primary-foreground">AB</span>
          <div>
            <p className="font-semibold leading-tight">ABC Mart</p>
            <p className="text-xs text-muted-foreground">POS and Inventory Management</p>
          </div>
        </div>
        <Card className="gap-4 rounded-lg p-5 shadow-none">
          <h1 className="text-lg font-semibold">{mode === "password" ? "Sign in" : "Cashier PIN sign-in"}</h1>
          {mode === "password" ? (
            <form onSubmit={submit} noValidate className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="username">Username or email</Label>
                <Input id="username" autoComplete="username" autoFocus aria-invalid={Boolean(form.formState.errors.username)} {...form.register("username")} />
                {form.formState.errors.username ? <p className="text-xs text-destructive">{form.formState.errors.username.message}</p> : null}
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="password">Password</Label>
                  <button type="button" onClick={() => void forgot()} className="text-xs text-primary hover:underline">Forgot password?</button>
                </div>
                <Input id="password" type="password" autoComplete="current-password" aria-invalid={Boolean(form.formState.errors.password)} {...form.register("password")} />
                {form.formState.errors.password ? <p className="text-xs text-destructive">{form.formState.errors.password.message}</p> : null}
              </div>
              {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
              <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <Loader2 className="animate-spin" /> : null}Sign in</Button>
              <Button type="button" variant="outline" className="w-full" onClick={() => { setError(null); setMode("pin"); }}>Switch to PIN</Button>
            </form>
          ) : (
            <div className="space-y-3">
              {isMockMode ? (
                <div className="space-y-1.5">
                  <Label htmlFor="terminal">Registered terminal</Label>
                  <Select value={terminal} onValueChange={setTerminalLocal}>
                    <SelectTrigger id="terminal" className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>{DEMO_TERMINALS.map(([id, name]) => <SelectItem key={id} value={id}>{name}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              ) : savedTerminal ? (
                <p className="text-sm text-muted-foreground">This device is registered as a POS terminal.</p>
              ) : (
                <p className="rounded-md bg-muted p-2 text-sm text-muted-foreground">To use PIN sign-in, sign in once with a password and choose this device&apos;s terminal on the POS screen.</p>
              )}
              <Input readOnly type="password" value={pin} aria-label="PIN" className="h-12 text-center text-xl tracking-[0.4em]" />
              <div className="grid grid-cols-3 gap-2">
                {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => <Button key={d} type="button" variant="outline" className="h-12 text-lg" onClick={() => press(d)}>{d}</Button>)}
                <Button type="button" variant="outline" className="h-12" aria-label="Delete digit" onClick={() => setPin((p) => p.slice(0, -1))}><Delete /></Button>
                <Button type="button" variant="outline" className="h-12 text-lg" onClick={() => press("0")}>0</Button>
                <Button type="button" className="h-12" disabled={pin.length < 4 || busy || !terminal} onClick={() => void submitPin(pin)}>{busy ? <Loader2 className="animate-spin" /> : "Enter"}</Button>
              </div>
              {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
              <Button type="button" variant="ghost" className="w-full" onClick={() => { setError(null); setMode("password"); }}>Use password instead</Button>
            </div>
          )}
        </Card>
        {isMockMode ? (
          <Card className="gap-2 rounded-lg border-warning/40 bg-warning/5 p-4 text-xs shadow-none">
            <p className="font-medium">Demo mode. Sign-in is simulated in this browser and is not production security.</p>
            <p className="text-muted-foreground">Password for every account: <code className="font-mono">demo-password</code>. Cashier PIN: <code className="font-mono">1593</code>.</p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {DEMO_ACCOUNTS.map(([username, label]) => <Button key={username} type="button" variant="outline" size="xs" onClick={() => quick(username)}>{label}</Button>)}
            </div>
          </Card>
        ) : null}
      </div>
    </main>
  );
}
