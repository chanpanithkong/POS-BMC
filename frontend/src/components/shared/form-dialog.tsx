"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Controller, type FieldValues, type Path, useForm, type UseFormReturn } from "react-hook-form";
import type { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, getErrorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

export interface Option {
  value: string;
  label: string;
}

export interface FieldDef<T extends FieldValues> {
  name: Path<T>;
  label: string;
  type?: "text" | "number" | "email" | "password" | "tel" | "textarea" | "select" | "switch" | "date" | "datetime-local" | "time" | "file";
  options?: Option[];
  placeholder?: string;
  help?: string;
  full?: boolean;
  disabled?: boolean;
  step?: string;
  allowNone?: string;
  required?: boolean;
  visible?: (values: T) => boolean;
}

const NONE = "__none";

function readAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function FormFields<T extends FieldValues>({ form, fields, idPrefix = "field" }: { form: UseFormReturn<T>; fields: FieldDef<T>[]; idPrefix?: string }) {
  const values = form.watch();
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {fields.filter((f) => !f.visible || f.visible(values)).map((field) => {
        const id = `${idPrefix}-${field.name}`;
        const message = form.formState.errors[field.name]?.message;
        const errorText = typeof message === "string" ? message : undefined;
        const describedBy = errorText ? `${id}-error` : field.help ? `${id}-help` : undefined;
        const type = field.type ?? "text";
        return (
          <div key={field.name} className={cn("min-w-0 space-y-1.5", field.full && "sm:col-span-2", type === "switch" && "flex items-center justify-between gap-3 space-y-0 rounded-md border p-2.5")}>
            <Label htmlFor={id} className="leading-snug">
              {field.label}
              {field.required ? <span className="text-destructive" aria-hidden> *</span> : null}
            </Label>
            {type === "select" ? (
              <Controller
                control={form.control}
                name={field.name}
                render={({ field: control }) => (
                  <Select value={control.value ? String(control.value) : field.allowNone ? NONE : ""} onValueChange={(v) => control.onChange(v === NONE ? "" : v)} disabled={field.disabled}>
                    <SelectTrigger id={id} className="w-full" aria-invalid={Boolean(errorText)} aria-describedby={describedBy}><SelectValue placeholder={field.placeholder ?? "Select"} /></SelectTrigger>
                    <SelectContent>
                      {field.allowNone ? <SelectItem value={NONE}>{field.allowNone}</SelectItem> : null}
                      {field.options?.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                )}
              />
            ) : type === "switch" ? (
              <Controller control={form.control} name={field.name} render={({ field: control }) => <Switch id={id} checked={Boolean(control.value)} onCheckedChange={control.onChange} disabled={field.disabled} />} />
            ) : type === "textarea" ? (
              <Textarea id={id} rows={3} placeholder={field.placeholder} disabled={field.disabled} aria-invalid={Boolean(errorText)} aria-describedby={describedBy} {...form.register(field.name)} />
            ) : type === "file" ? (
              <Controller
                control={form.control}
                name={field.name}
                render={({ field: control }) => (
                  <div className="space-y-1">
                    <Input
                      id={id}
                      type="file"
                      accept="image/jpeg,image/png,image/webp,application/pdf"
                      aria-describedby={describedBy}
                      onChange={async (e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        if (file.size > 2 * 1024 * 1024) {
                          form.setError(field.name, { message: "File must be 2 MB or smaller." });
                          return;
                        }
                        form.clearErrors(field.name);
                        control.onChange(await readAsDataUrl(file));
                      }}
                    />
                    {control.value ? <p className="text-xs text-muted-foreground">File attached</p> : null}
                  </div>
                )}
              />
            ) : (
              <Input
                id={id}
                type={type}
                step={type === "number" ? (field.step ?? "any") : undefined}
                placeholder={field.placeholder}
                disabled={field.disabled}
                aria-invalid={Boolean(errorText)}
                aria-describedby={describedBy}
                {...form.register(field.name, type === "number" ? { setValueAs: (v) => (v === "" || v === null || v === undefined ? undefined : Number(v)) } : undefined)}
              />
            )}
            {field.help && !errorText && type !== "switch" ? <p id={`${id}-help`} className="text-xs text-muted-foreground">{field.help}</p> : null}
            {errorText ? <p id={`${id}-error`} className="text-xs text-destructive">{errorText}</p> : null}
          </div>
        );
      })}
    </div>
  );
}

/** Maps server field errors onto the form so messages appear beside the input. */
export function applyServerErrors<T extends FieldValues>(form: UseFormReturn<T>, error: unknown, names: string[]) {
  if (!(error instanceof ApiError)) return false;
  let matched = false;
  for (const detail of error.details) {
    if (detail.field && names.includes(detail.field)) {
      form.setError(detail.field as Path<T>, { message: detail.message });
      matched = true;
    }
  }
  return matched;
}

interface FormDialogProps<T extends FieldValues> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  schema: z.ZodType<T, FieldValues>;
  defaultValues: T;
  fields: FieldDef<T>[];
  submitLabel?: string;
  onSubmit: (values: T) => Promise<unknown>;
  wide?: boolean;
  extra?: ReactNode;
}

export function FormDialog<T extends FieldValues>({ open, onOpenChange, title, description, schema, defaultValues, fields, submitLabel = "Save", onSubmit, wide, extra }: FormDialogProps<T>) {
  const form = useForm<T>({ resolver: zodResolver(schema) as never, defaultValues: defaultValues as never });
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (open) form.reset(defaultValues as never);
    // Reset only when the dialog opens; defaultValues is rebuilt by callers each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const submit = form.handleSubmit(async (values) => {
    setFormError(null);
    try {
      await onSubmit(values as T);
      setFormError(null);
      onOpenChange(false);
    } catch (error) {
      if (!applyServerErrors(form as never, error, fields.map((f) => f.name))) setFormError(getErrorMessage(error));
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) setFormError(null); onOpenChange(next); }}>
      <DialogContent className={cn("max-h-[90vh] overflow-y-auto", wide ? "sm:max-w-2xl" : "sm:max-w-lg")}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className={description ? undefined : "sr-only"}>{description ?? title}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} noValidate className="space-y-4">
          <FormFields form={form as never} fields={fields as never} />
          {extra}
          {formError ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{formError}</p> : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? <Loader2 className="animate-spin" /> : null}{submitLabel}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
