"use client";

import { ShieldCheck } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useMemo, useRef, useState } from "react";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getErrorMessage } from "@/lib/api/errors";
import { isMockMode } from "@/lib/api/config";
import { authApi } from "@/services";
import type { ApprovalAction } from "@/types";

interface ConfirmOptions {
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
}

interface PromptOptions {
  title: string;
  description?: string;
  label: string;
  placeholder?: string;
  confirmLabel?: string;
  required?: boolean;
  multiline?: boolean;
  defaultValue?: string;
}

interface ApproveOptions {
  action: ApprovalAction;
  message: string;
  amount?: number;
}

interface DialogsApi {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  prompt: (options: PromptOptions) => Promise<string | null>;
  approve: (options: ApproveOptions) => Promise<string | null>;
}

const DialogsContext = createContext<DialogsApi | null>(null);

export function useDialogs() {
  const value = useContext(DialogsContext);
  if (!value) throw new Error("useDialogs must be used within DialogsProvider");
  return value;
}

export function DialogsProvider({ children }: { children: ReactNode }) {
  const [confirmState, setConfirmState] = useState<ConfirmOptions | null>(null);
  const [promptState, setPromptState] = useState<PromptOptions | null>(null);
  const [approveState, setApproveState] = useState<ApproveOptions | null>(null);
  const [text, setText] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const resolver = useRef<((value: never) => void) | null>(null);

  const settle = useCallback((value: unknown) => {
    (resolver.current as ((v: unknown) => void) | null)?.(value);
    resolver.current = null;
    setConfirmState(null);
    setPromptState(null);
    setApproveState(null);
  }, []);

  const api = useMemo<DialogsApi>(
    () => ({
      confirm: (options) => new Promise((resolve) => {
        resolver.current = resolve as never;
        setConfirmState(options);
      }),
      prompt: (options) => new Promise((resolve) => {
        resolver.current = resolve as never;
        setText(options.defaultValue ?? "");
        setError(null);
        setPromptState(options);
      }),
      approve: (options) => new Promise((resolve) => {
        resolver.current = resolve as never;
        setPin("");
        setError(null);
        setApproveState(options);
      }),
    }),
    [],
  );

  const submitPrompt = () => {
    if (promptState?.required !== false && !text.trim()) {
      setError(`${promptState?.label} is required.`);
      return;
    }
    settle(text.trim());
  };

  const submitPin = async () => {
    if (!approveState) return;
    setBusy(true);
    setError(null);
    try {
      const grant = await authApi.verifyApproval(pin, approveState.action, approveState.amount ?? 0);
      settle(grant.token);
    } catch (e) {
      setError(getErrorMessage(e));
      setPin("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogsContext.Provider value={api}>
      {children}
      <AlertDialog open={confirmState !== null} onOpenChange={(open) => !open && settle(false)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmState?.title}</AlertDialogTitle>
            {confirmState?.description ? <AlertDialogDescription asChild><div>{confirmState.description}</div></AlertDialogDescription> : <AlertDialogDescription className="sr-only">Confirm this action</AlertDialogDescription>}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => settle(false)}>Go back</AlertDialogCancel>
            <AlertDialogAction className={confirmState?.destructive ? "bg-destructive text-white hover:bg-destructive/90" : undefined} onClick={() => settle(true)}>
              {confirmState?.confirmLabel ?? "Confirm"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={promptState !== null} onOpenChange={(open) => !open && settle(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{promptState?.title}</DialogTitle>
            <DialogDescription className={promptState?.description ? undefined : "sr-only"}>{promptState?.description ?? "Enter a value"}</DialogDescription>
          </DialogHeader>
          <form onSubmit={(e) => { e.preventDefault(); submitPrompt(); }} className="space-y-2">
            <Label htmlFor="prompt-value">{promptState?.label}</Label>
            {promptState?.multiline ? (
              <Textarea id="prompt-value" autoFocus value={text} placeholder={promptState?.placeholder} onChange={(e) => setText(e.target.value)} aria-invalid={Boolean(error)} />
            ) : (
              <Input id="prompt-value" autoFocus value={text} placeholder={promptState?.placeholder} onChange={(e) => setText(e.target.value)} aria-invalid={Boolean(error)} />
            )}
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            <DialogFooter className="pt-2">
              <Button type="button" variant="outline" onClick={() => settle(null)}>Go back</Button>
              <Button type="submit">{promptState?.confirmLabel ?? "Confirm"}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={approveState !== null} onOpenChange={(open) => !open && settle(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><ShieldCheck className="size-5 text-primary" />Manager approval</DialogTitle>
            <DialogDescription>{approveState?.message}</DialogDescription>
          </DialogHeader>
          <form onSubmit={(e) => { e.preventDefault(); void submitPin(); }} className="space-y-2">
            <Label htmlFor="approval-pin">Supervisor PIN</Label>
            <Input id="approval-pin" autoFocus type="password" inputMode="numeric" autoComplete="off" value={pin} onChange={(e) => setPin(e.target.value)} className="h-12 text-center text-xl tracking-[0.4em]" aria-invalid={Boolean(error)} />
            {error ? <p className="text-sm text-destructive">{error}</p> : null}
            {isMockMode ? <p className="text-xs text-muted-foreground">Demo PINs: Store Manager 2580, Branch Manager 3914, Owner 7391.</p> : null}
            <DialogFooter className="pt-2">
              <Button type="button" variant="outline" onClick={() => settle(null)}>Go back</Button>
              <Button type="submit" disabled={busy || pin.length < 4}>Approve</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </DialogsContext.Provider>
  );
}
