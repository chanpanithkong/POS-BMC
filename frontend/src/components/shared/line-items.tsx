"use client";

import { ScanBarcode, Trash2 } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApiQuery } from "@/hooks/use-api";
import { cn } from "@/lib/utils";
import { productsApi } from "@/services";
import type { ProductListItem } from "@/types";

export function useProducts(filter?: (p: ProductListItem) => boolean) {
  const query = useApiQuery(["products"], () => productsApi.list());
  return useMemo(() => (query.data ?? []).filter((p) => p.type !== "VARIANT_PARENT" && (!filter || filter(p))), [query.data, filter]);
}

export const isStocked = (p: ProductListItem) => p.type !== "SERVICE";

/** Search or scan to pick a product; a barcode followed by Enter adds it directly. */
export function ProductPicker({ products, onPick, placeholder = "Scan a barcode or search products" }: { products: ProductListItem[]; onPick: (p: ProductListItem, unitId?: string) => void; placeholder?: string }) {
  const [term, setTerm] = useState("");
  const value = term.trim().toLowerCase();
  const matches = value.length >= 2 ? products.filter((p) => `${p.nameEn} ${p.nameKm} ${p.sku} ${p.barcodes.map((b) => b.barcode).join(" ")}`.toLowerCase().includes(value)).slice(0, 8) : [];
  const pick = (p: ProductListItem, unitId?: string) => {
    onPick(p, unitId);
    setTerm("");
  };
  const onEnter = () => {
    const hit = products.flatMap((p) => p.barcodes.filter((b) => b.active && b.barcode === term.trim()).map((b) => ({ p, b })))[0];
    if (hit) pick(hit.p, hit.b.unitId);
    else if (matches.length === 1) pick(matches[0]);
    else if (value) toast.error("Barcode not found — search by name.");
  };
  return (
    <div className="relative">
      <ScanBarcode className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
      <Input value={term} onChange={(e) => setTerm(e.target.value)} placeholder={placeholder} aria-label="Add product" className="pl-8" onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onEnter(); } }} />
      {matches.length ? (
        <ul className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-md border bg-popover shadow-md">
          {matches.map((p) => (
            <li key={p.id}><button type="button" onClick={() => pick(p)} className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-muted"><span className="min-w-0 truncate">{p.nameEn}</span><span className="shrink-0 font-mono text-xs text-muted-foreground">{p.sku}</span></button></li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export interface LineColumn<L> {
  header: string;
  cell: (line: L, update: (patch: Partial<L>) => void, index: number) => ReactNode;
  align?: "right";
  className?: string;
}

/** Editable document lines shared by adjustments, transfers, purchase orders and receipts. */
export function LineItems<L>({ lines, onChange, columns, picker, removable = true, emptyText = "Add a product to begin." }: { lines: L[]; onChange: (lines: L[]) => void; columns: LineColumn<L>[]; picker?: ReactNode; removable?: boolean; emptyText?: string }) {
  const update = (index: number) => (patch: Partial<L>) => onChange(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  return (
    <div className="space-y-2">
      {picker}
      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader><TableRow className="hover:bg-transparent">{columns.map((c) => <TableHead key={c.header} className={cn("h-8 text-xs whitespace-nowrap", c.align === "right" && "text-right", c.className)}>{c.header}</TableHead>)}{removable ? <TableHead className="h-8 w-9" /> : null}</TableRow></TableHeader>
          <TableBody>
            {lines.map((line, i) => (
              <TableRow key={i}>
                {columns.map((c) => <TableCell key={c.header} className={cn("py-1.5", c.align === "right" && "text-right", c.className)}>{c.cell(line, update(i), i)}</TableCell>)}
                {removable ? <TableCell className="py-1.5"><Button type="button" variant="ghost" size="icon-sm" aria-label="Remove line" onClick={() => onChange(lines.filter((_, x) => x !== i))}><Trash2 /></Button></TableCell> : null}
              </TableRow>
            ))}
            {!lines.length ? <TableRow><TableCell colSpan={columns.length + 1} className="py-6 text-center text-sm text-muted-foreground">{emptyText}</TableCell></TableRow> : null}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export function NumberCell({ value, onChange, min = 0, label, className, disabled }: { value: number | ""; onChange: (value: number) => void; min?: number; label: string; className?: string; disabled?: boolean }) {
  return <Input type="number" min={min} step="any" aria-label={label} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))} className={cn("tabular h-8 w-22 text-right", className)} />;
}
