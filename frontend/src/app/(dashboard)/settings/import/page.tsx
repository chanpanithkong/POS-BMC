"use client";

import { Download, Undo2, Upload } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { getErrorMessage } from "@/lib/api/errors";
import { exportCsv, parseCsv, parseXlsx, sha256 } from "@/lib/export";
import { formatDateTime, titleCase } from "@/lib/format";
import { importsApi } from "@/services";
import type { ImportBatch, ImportError, ImportPreview, ImportType } from "@/types";

const TYPES: ImportType[] = ["PRODUCTS", "BARCODES", "SUPPLIERS", "CUSTOMERS", "OPENING_STOCK", "PRICES", "STOCK_COUNT"];
const STEPS = ["Type and template", "Upload", "Preview", "Done"];

const ERROR_COLUMNS: Column<ImportError & { i: number }>[] = [
  { id: "row", header: "Row", value: (e) => e.row, align: "right" },
  { id: "field", header: "Field", value: (e) => e.field },
  { id: "value", header: "Value", value: (e) => e.value },
  { id: "message", header: "Problem", value: (e) => e.message },
];

export default function ImportWizardPage() {
  const { confirm } = useDialogs();
  const history = useApiQuery(["imports"], importsApi.list);
  const [type, setType] = useState<ImportType>("PRODUCTS");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [done, setDone] = useState<ImportBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const commit = useApiMutation((token: string) => importsApi.commit(token), { success: (b) => `${b.importedRows} rows imported`, onSuccess: (b) => { setDone(b); setPreview(null); } });
  const rollback = useApiMutation((id: string) => importsApi.rollback(id), { success: "Import rolled back" });
  const step = done ? 3 : preview ? 2 : 0;

  const template = async () => {
    const { columns } = await importsApi.template(type);
    exportCsv(`template-${type.toLowerCase()}`, columns.map((c) => ({ header: c, key: c })), []);
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    setDone(null);
    if (!/\.(csv|xlsx)$/i.test(file.name)) return setError("Use a .csv or .xlsx file.");
    if (file.size > 20 * 1024 * 1024) return setError("The file exceeds 20 MB.");
    setBusy(true);
    try {
      const buffer = await file.arrayBuffer();
      const rows = /\.csv$/i.test(file.name) ? parseCsv(new TextDecoder().decode(buffer)) : parseXlsx(buffer);
      setPreview(await importsApi.preview({ type, fileName: file.name, fileHash: await sha256(buffer), rows }));
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const downloadErrors = () => {
    if (!preview) return;
    exportCsv("import-errors", ["row", "field", "value", "message"].map((c) => ({ header: c, key: c })), preview.errors.map((e) => ({ ...e })));
    toast.success("Error report downloaded");
  };

  const historyColumns: Column<ImportBatch>[] = [
    { id: "at", header: "When", value: (b) => b.at, cell: (b) => formatDateTime(b.at) },
    { id: "type", header: "Type", value: (b) => titleCase(b.type) },
    { id: "file", header: "File", value: (b) => b.fileName, hideBelow: "md" },
    { id: "hash", header: "Hash", value: (b) => b.fileHash.slice(0, 10), cell: (b) => <span className="font-mono text-xs">{b.fileHash.slice(0, 10)}</span>, hideBelow: "lg" },
    { id: "rows", header: "Rows", value: (b) => b.importedRows, align: "right" },
    { id: "user", header: "User", value: (b) => b.userName, hideBelow: "lg" },
    { id: "status", header: "Status", value: (b) => b.status, cell: (b) => <StatusBadge status={b.status} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (b) => (b.status === "COMMITTED" && b.canRollback ? <Button size="sm" variant="ghost" onClick={async () => { if (await confirm({ title: "Roll back this import?", description: "Created records are removed if nothing depends on them.", confirmLabel: "Roll back", destructive: true })) void rollback.fire(b.id); }}><Undo2 />Roll back</Button> : null) },
  ];

  return (
    <RequirePermission anyOf={["imports.manage"]}>
      <PageHeader title="Import wizard" description="Files are validated in full before anything is saved" />
      <ol className="mb-3 flex flex-wrap gap-2 text-xs">{STEPS.map((s, i) => <li key={s} aria-current={i === step ? "step" : undefined} className={`rounded-full border px-2.5 py-1 ${i === step ? "border-primary bg-accent font-medium text-accent-foreground" : "text-muted-foreground"}`}>{i + 1}. {s}</li>)}</ol>
      <Card className="mb-3 gap-3 rounded-lg p-4 shadow-none">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="space-y-1"><Label>Data type</Label><Select value={type} onValueChange={(v) => { setType(v as ImportType); setPreview(null); setDone(null); setError(null); }}><SelectTrigger className="w-full sm:w-52" aria-label="Data type"><SelectValue /></SelectTrigger><SelectContent>{TYPES.map((t) => <SelectItem key={t} value={t}>{titleCase(t)}</SelectItem>)}</SelectContent></Select></div>
          <Button variant="outline" onClick={() => void template()}><Download />Download template</Button>
          <div className="space-y-1"><Label htmlFor="import-file">File (.csv or .xlsx, up to 20 MB)</Label><Input id="import-file" type="file" accept=".csv,.xlsx" disabled={busy} onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = ""; }} /></div>
        </div>
        {error ? <p className="rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{error}</p> : null}
        {done ? <p className="rounded-md bg-success/10 p-2 text-sm text-success">{done.importedRows} rows imported from {done.fileName}.</p> : null}
      </Card>
      {preview ? (
        <Card className="mb-3 gap-3 rounded-lg p-4 shadow-none">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm"><strong>{preview.fileName}</strong>: {preview.totalRows} rows, {preview.validRows} valid, {preview.errors.length} problem{preview.errors.length === 1 ? "" : "s"}.</p>
            <div className="flex gap-2">
              {preview.errors.length ? <Button size="sm" variant="outline" onClick={downloadErrors}><Download />Error report</Button> : null}
              <Button size="sm" disabled={preview.errors.length > 0 || commit.isPending} onClick={() => void commit.fire(preview.token)}><Upload />Commit import</Button>
            </div>
          </div>
          {preview.errors.length ? <p className="text-sm text-destructive">Any blocking error rejects the whole file. Fix the rows and upload again.</p> : null}
          {preview.errors.length ? <DataTable data={preview.errors.map((e, i) => ({ ...e, i }))} columns={ERROR_COLUMNS} getRowId={(e) => String(e.i)} searchPlaceholder="Search problems" pageSize={10} /> : (
            <div className="overflow-x-auto rounded-md border"><table className="w-full text-sm"><thead><tr className="border-b">{preview.columns.map((c) => <th key={c} className="p-2 text-left text-xs font-medium whitespace-nowrap text-muted-foreground">{c}</th>)}</tr></thead><tbody>{preview.sample.map((row, i) => <tr key={i} className="border-b last:border-0">{preview.columns.map((c) => <td key={c} className="p-2 whitespace-nowrap">{row[c]}</td>)}</tr>)}</tbody></table></div>
          )}
        </Card>
      ) : null}
      <h2 className="mb-2 text-sm font-medium">Import history</h2>
      <DataTable data={history.data} columns={historyColumns} getRowId={(b) => b.id} isLoading={history.isLoading} error={history.error} searchPlaceholder="File or type" emptyTitle="No imports yet" />
    </RequirePermission>
  );
}
