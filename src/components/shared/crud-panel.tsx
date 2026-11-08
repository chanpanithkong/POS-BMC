"use client";

import { MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { type ReactNode, useState } from "react";
import type { FieldValues } from "react-hook-form";
import type { z } from "zod";
import { type Column, DataTable, type TableFilter } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { type FieldDef, FormDialog } from "@/components/shared/form-dialog";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";

interface CrudApi<T, P> {
  list: () => Promise<T[]>;
  create: (input: P) => Promise<T>;
  update: (id: string, input: P) => Promise<T>;
  remove: (id: string) => Promise<unknown>;
}

interface CrudPanelProps<T extends { id: string }, V extends FieldValues, P> {
  queryKey: string;
  singular: string;
  api: CrudApi<T, P>;
  columns: Column<T>[];
  fields: FieldDef<V>[] | ((row: T | null) => FieldDef<V>[]);
  schema: z.ZodType<V, FieldValues>;
  empty: V;
  toForm: (row: T) => V;
  toPayload: (values: V, row: T | null) => P;
  canManage: boolean;
  canDelete?: (row: T) => boolean;
  filters?: TableFilter<T>[];
  exportName?: string;
  rowActions?: (row: T) => ReactNode;
  wide?: boolean;
  searchPlaceholder?: string;
}

/** Master-data list with create, edit and confirmed delete. */
export function CrudPanel<T extends { id: string }, V extends FieldValues, P>({ queryKey, singular, api, columns, fields, schema, empty, toForm, toPayload, canManage, canDelete, filters, exportName, rowActions, wide, searchPlaceholder }: CrudPanelProps<T, V, P>) {
  const query = useApiQuery([queryKey], api.list);
  const { confirm } = useDialogs();
  const [editing, setEditing] = useState<T | null>(null);
  const [open, setOpen] = useState(false);
  const save = useApiMutation((values: V) => (editing ? api.update(editing.id, toPayload(values, editing)) : api.create(toPayload(values, null))), { success: `${singular} saved`, silentError: true });
  const remove = useApiMutation((id: string) => api.remove(id), { success: `${singular} deleted` });

  const actionColumn: Column<T> = {
    id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right",
    cell: (row) => (
      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
        {rowActions?.(row)}
        {canManage ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={`Actions for ${singular}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => { setEditing(row); setOpen(true); }}><Pencil />Edit</DropdownMenuItem>
              {canDelete?.(row) !== false ? (
                <DropdownMenuItem
                  variant="destructive"
                  onClick={async () => {
                    if (await confirm({ title: `Delete this ${singular.toLowerCase()}?`, description: "This cannot be undone.", confirmLabel: "Delete", destructive: true })) void remove.fire(row.id);
                  }}
                ><Trash2 />Delete</DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
    ),
  };

  const resolvedFields = typeof fields === "function" ? fields(editing) : fields;

  return (
    <>
      <DataTable
        data={query.data}
        columns={canManage || rowActions ? [...columns, actionColumn] : columns}
        getRowId={(r) => r.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        filters={filters}
        exportName={exportName}
        searchPlaceholder={searchPlaceholder}
        emptyDescription={canManage ? `Add your first ${singular.toLowerCase()} to get started.` : undefined}
        toolbar={canManage ? <Button size="sm" onClick={() => { setEditing(null); setOpen(true); }}><Plus />New {singular.toLowerCase()}</Button> : undefined}
      />
      <FormDialog
        open={open}
        onOpenChange={setOpen}
        title={`${editing ? "Edit" : "New"} ${singular.toLowerCase()}`}
        schema={schema}
        defaultValues={editing ? toForm(editing) : empty}
        fields={resolvedFields}
        onSubmit={(values) => save.run(values)}
        wide={wide}
      />
    </>
  );
}
