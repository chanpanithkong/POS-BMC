"use client";

import { Plus, Printer, Sparkles } from "lucide-react";
import { useState } from "react";
import { z } from "zod";
import { BarcodeLabelDialog, type LabelItem } from "@/components/products/barcode-labels";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { FormDialog } from "@/components/shared/form-dialog";
import { useProducts } from "@/components/shared/line-items";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useUnits } from "@/hooks/use-lookups";
import { detectSymbology } from "@/lib/barcode";
import { formatDate } from "@/lib/format";
import { productsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { BarcodeRow, BarcodeSymbology } from "@/types";

const schema = z.object({ productId: z.string().min(1, "Select a product."), barcode: z.string().min(1, "Barcode is required."), unitId: z.string().min(1, "Select a unit.") });
type V = z.infer<typeof schema>;

export default function BarcodesPage() {
  const can = useCan();
  const canEdit = can("products.edit");
  const query = useApiQuery(["barcodes"], productsApi.barcodes);
  const products = useProducts();
  const units = useUnits();
  const { confirm } = useDialogs();
  const [open, setOpen] = useState(false);
  const [preset, setPreset] = useState("");
  const [labels, setLabels] = useState<LabelItem[] | null>(null);

  const add = useApiMutation(async (v: V) => {
    const product = await productsApi.get(v.productId);
    return productsApi.update(v.productId, { barcodes: [...product.barcodes, { id: "", barcode: v.barcode, symbology: detectSymbology(v.barcode) as BarcodeSymbology, unitId: v.unitId, active: true, createdAt: "" }] });
  }, { success: "Barcode added", silentError: true });
  const deactivate = useApiMutation(async (row: BarcodeRow) => {
    const product = await productsApi.get(row.productId);
    return productsApi.update(row.productId, { barcodes: product.barcodes.map((b) => (b.id === row.id ? { ...b, active: false } : b)) });
  }, { success: "Barcode deactivated" });
  const generate = useApiMutation(() => productsApi.generateBarcode(), { onSuccess: (r) => { setPreset(r.barcode); setOpen(true); } });

  const columns: Column<BarcodeRow>[] = [
    { id: "barcode", header: "Barcode", value: (b) => b.barcode, cell: (b) => <span className="font-mono text-xs">{b.barcode}</span> },
    { id: "symbology", header: "Symbology", value: (b) => b.symbology, hideBelow: "md" },
    { id: "product", header: "Product", value: (b) => b.productName },
    { id: "unit", header: "Unit", value: (b) => b.unitCode },
    { id: "active", header: "Active", value: (b) => (b.active ? "ACTIVE" : "INACTIVE"), cell: (b) => <StatusBadge status={b.active ? "ACTIVE" : "INACTIVE"} /> },
    { id: "created", header: "Created", value: (b) => b.createdAt, cell: (b) => formatDate(b.createdAt), hideBelow: "lg" },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (b) => (
      <div className="flex justify-end gap-1">
        <Button variant="ghost" size="sm" onClick={() => setLabels([{ barcode: b.barcode, symbology: b.symbology, name: b.productName, price: products.find((p) => p.id === b.productId)?.retailPrice ?? 0 }])}><Printer />Label</Button>
        {canEdit && b.active ? <Button variant="ghost" size="sm" onClick={async () => { if (await confirm({ title: "Deactivate this barcode?", description: `${b.barcode} will stop scanning. It stays in history.`, confirmLabel: "Deactivate" })) void deactivate.fire(b); }}>Deactivate</Button> : null}
      </div>
    ) },
  ];

  return (
    <RequirePermission anyOf={["products.view"]}>
      <PageHeader title="Barcodes" description="One product can hold several barcodes, each linked to a unit" />
      <DataTable
        data={query.data} columns={columns} getRowId={(b) => b.id} isLoading={query.isLoading} error={query.error} onRetry={() => void query.refetch()} exportName="barcodes" searchPlaceholder="Barcode or product"
        filters={[{ id: "active", label: "Status", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }], value: (b) => (b.active ? "ACTIVE" : "INACTIVE") }, { id: "sym", label: "Symbologies", options: ["EAN13", "EAN8", "UPCA", "CODE128"].map((value) => ({ value, label: value })), value: (b) => b.symbology }]}
        toolbar={canEdit ? <><Button size="sm" variant="outline" onClick={() => void generate.fire(undefined)}><Sparkles />Generate</Button><Button size="sm" onClick={() => { setPreset(""); setOpen(true); }}><Plus />Add</Button></> : undefined}
      />
      <FormDialog open={open} onOpenChange={setOpen} title="Add barcode" schema={schema} defaultValues={{ productId: "", barcode: preset, unitId: "" }} submitLabel="Add barcode" onSubmit={(v) => add.run(v)}
        fields={[{ name: "productId", label: "Product", type: "select", required: true, full: true, options: products.map((p) => ({ value: p.id, label: `${p.sku} - ${p.nameEn}` })) }, { name: "barcode", label: "Barcode", required: true }, { name: "unitId", label: "Unit", type: "select", required: true, options: units.map((u) => ({ value: u.id, label: u.code })) }]}
      />
      <BarcodeLabelDialog open={labels !== null} onOpenChange={(o) => !o && setLabels(null)} items={labels ?? []} />
    </RequirePermission>
  );
}
