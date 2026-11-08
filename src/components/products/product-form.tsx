"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Copy, Plus, Printer, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { applyServerErrors, type FieldDef, FormFields } from "@/components/shared/form-dialog";
import { LineItems, NumberCell } from "@/components/shared/line-items";
import { PageHeader, StatusBadge } from "@/components/shared/page";
import { ProductVisual } from "@/components/shared/product-visual";
import { BarcodeLabelDialog } from "@/components/products/barcode-labels";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBrandOptions, useCategories, useCategoryOptions, useSupplierOptions, useTaxOptions, useUnitOptions, useUnits, useWarehouses } from "@/hooks/use-lookups";
import { getErrorMessage } from "@/lib/api/errors";
import { detectSymbology, validateBarcode } from "@/lib/barcode";
import { formatDateTime, formatUsd } from "@/lib/format";
import { productsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { BarcodeSymbology, Product, ProductBarcode, ProductListItem, ProductSupplierLink, StockSettings, UnitConversion } from "@/types";

const schema = z.object({
  type: z.enum(["STANDARD", "WEIGHED", "VARIANT_PARENT", "SERVICE"]),
  sku: z.string(),
  nameEn: z.string().min(1, "English name is required."),
  nameKm: z.string(),
  description: z.string(),
  categoryId: z.string().min(1, "Category is required."),
  brandId: z.string(),
  baseUnitId: z.string().min(1, "Base unit is required."),
  taxCodeId: z.string(),
  allowFraction: z.boolean(),
  precision: z.number({ error: "Enter a number." }).int().min(0).max(4),
  retailPrice: z.number({ error: "Enter a price." }).min(0, "Price must not be negative."),
  wholesalePrice: z.number({ error: "Enter a price." }).min(0, "Price must not be negative."),
  minSellingPrice: z.number().min(0).optional(),
  trackExpiry: z.boolean(),
  isFavourite: z.boolean(),
  image: z.string(),
});
type Values = z.infer<typeof schema>;

const EMPTY: Values = { type: "STANDARD", sku: "", nameEn: "", nameKm: "", description: "", categoryId: "", brandId: "", baseUnitId: "", taxCodeId: "", allowFraction: false, precision: 0, retailPrice: 0, wholesalePrice: 0, minSellingPrice: undefined, trackExpiry: false, isFavourite: false, image: "" };
const NO_SETTINGS: StockSettings = { reorderLevel: 0, minLevel: 0, maxLevel: 0, reorderQty: 0 };

function toValues(p: ProductListItem): Values {
  return { type: p.type, sku: p.sku, nameEn: p.nameEn, nameKm: p.nameKm, description: p.description, categoryId: p.categoryId, brandId: p.brandId ?? "", baseUnitId: p.baseUnitId, taxCodeId: p.taxCodeId ?? "", allowFraction: p.allowFraction, precision: p.precision, retailPrice: p.retailPrice, wholesalePrice: p.wholesalePrice, minSellingPrice: p.minSellingPrice ?? undefined, trackExpiry: p.trackExpiry, isFavourite: p.isFavourite, image: p.image ?? "" };
}

export function ProductForm({ productId }: { productId?: string }) {
  const router = useRouter();
  const can = useCan();
  const showCost = can("costs.view");
  const canEdit = can(productId ? "products.edit" : "products.create");
  const { confirm } = useDialogs();
  const product = useApiQuery(["products", productId], () => productsApi.get(productId as string), { enabled: Boolean(productId) });
  const history = useApiQuery(["product-history", productId], () => productsApi.history(productId as string), { enabled: Boolean(productId) });
  const categories = useCategories();
  const categoryOptions = useCategoryOptions();
  const brandOptions = useBrandOptions();
  const unitOptions = useUnitOptions();
  const units = useUnits();
  const taxOptions = useTaxOptions();
  const supplierOptions = useSupplierOptions();
  const warehouses = useWarehouses();

  const form = useForm<Values>({ resolver: zodResolver(schema) as never, defaultValues: EMPTY });
  const [conversions, setConversions] = useState<UnitConversion[]>([]);
  const [barcodes, setBarcodes] = useState<ProductBarcode[]>([]);
  const [settings, setSettings] = useState<StockSettings>(NO_SETTINGS);
  const [warehouseSettings, setWarehouseSettings] = useState<Record<string, StockSettings>>({});
  const [suppliers, setSuppliers] = useState<ProductSupplierLink[]>([]);
  const [variantAttrs, setVariantAttrs] = useState({ sizes: "", colours: "" });
  const [labelsOpen, setLabelsOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    if (product.data) {
      form.reset(toValues(product.data));
      // Copies the fetched record into the editable drafts below.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setConversions(product.data.conversions);
      setBarcodes(product.data.barcodes);
      setSettings(product.data.stockSettings);
      setWarehouseSettings(product.data.warehouseSettings);
      setSuppliers(product.data.suppliers);
    }
    // Resets only when the server record changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [product.data]);

  const values = useWatch({ control: form.control }) as Values;
  const generated = useMemo(() => {
    if (values.type !== "VARIANT_PARENT") return [];
    const sizes = variantAttrs.sizes.split(",").map((s) => s.trim()).filter(Boolean);
    const colours = variantAttrs.colours.split(",").map((s) => s.trim()).filter(Boolean);
    const a = sizes.length ? sizes : [""];
    const b = colours.length ? colours : [""];
    if (!sizes.length && !colours.length) return [];
    return b.flatMap((colour) => a.map((size) => ({ attrs: { ...(colour ? { Colour: colour } : {}), ...(size ? { Size: size } : {}) }, sku: `${values.sku || "SKU"}-${colour.slice(0, 3).toUpperCase()}${size.toUpperCase()}` })));
  }, [values.sku, values.type, variantAttrs]);

  const unitOptionsForProduct = useMemo(() => {
    const ids = new Set([values.baseUnitId, ...conversions.map((c) => c.unitId)]);
    return units.filter((u) => ids.has(u.id));
  }, [conversions, units, values.baseUnitId]);

  const generateBarcode = useApiMutation(() => productsApi.generateBarcode(), {
    success: "Internal barcode generated",
    onSuccess: (res) => setBarcodes((b) => [...b, { id: "", barcode: res.barcode, symbology: "EAN13", unitId: values.baseUnitId, active: true, createdAt: "" }]),
  });
  const duplicate = useApiMutation(() => productsApi.duplicate(productId as string), { success: "Product duplicated", onSuccess: (p) => router.push(`/products/${p.id}`) });

  const submit = (status: Product["status"]) =>
    form.handleSubmit(async (v) => {
      setBanner(null);
      for (const b of barcodes.filter((x) => x.active)) {
        const message = validateBarcode(b.barcode, b.symbology);
        if (message) {
          setBanner(`${b.barcode}: ${message}`);
          return;
        }
      }
      setSaving(true);
      try {
        const payload: Partial<Product> & { variants?: typeof generated } = {
          ...v, sku: v.sku.trim(), brandId: v.brandId || null, taxCodeId: v.taxCodeId || null, minSellingPrice: v.minSellingPrice ?? null, image: v.image || null,
          allowFraction: v.type === "WEIGHED" ? true : v.allowFraction, status, conversions, barcodes, stockSettings: settings, warehouseSettings, suppliers,
          ...(productId ? {} : { variants: generated }),
        };
        const saved = productId ? await productsApi.update(productId, payload) : await productsApi.create(payload);
        toast.success("Product saved");
        await product.refetch?.();
        if (!productId) router.replace(`/products/${saved.id}`);
      } catch (error) {
        if (!applyServerErrors(form as never, error, ["sku", "nameEn", "categoryId", "baseUnitId"])) setBanner(getErrorMessage(error));
      } finally {
        setSaving(false);
      }
    })();

  const uploadImage = (file: File | undefined) => {
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 2 * 1024 * 1024) {
      toast.error("Use a JPEG, PNG or WebP image of 2 MB or less.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => form.setValue("image", String(reader.result));
    reader.readAsDataURL(file);
  };

  const fields: FieldDef<Values>[] = [
    { name: "type", label: "Product type", type: "select", disabled: Boolean(productId), options: [{ value: "STANDARD", label: "Standard" }, { value: "WEIGHED", label: "Sold by weight or volume" }, { value: "VARIANT_PARENT", label: "With variants (size, colour)" }, { value: "SERVICE", label: "Non-stock service" }] },
    { name: "sku", label: "SKU", placeholder: "Blank to generate automatically" },
    { name: "nameEn", label: "Name (English)", required: true },
    { name: "nameKm", label: "Name (Khmer)" },
    { name: "description", label: "Description", type: "textarea", full: true },
    { name: "categoryId", label: "Category", type: "select", required: true, options: categoryOptions },
    { name: "brandId", label: "Brand", type: "select", options: brandOptions, allowNone: "No brand" },
    { name: "baseUnitId", label: "Base unit", type: "select", required: true, options: unitOptions, disabled: Boolean(product.data?.hasMovements), help: product.data?.hasMovements ? "Base unit cannot change after stock movements" : undefined },
    { name: "taxCodeId", label: "Tax code", type: "select", options: taxOptions, allowNone: "Exempt" },
    { name: "isFavourite", label: "Show in POS favourites", type: "switch" },
  ];

  const priceFields: FieldDef<Values>[] = [
    { name: "retailPrice", label: "Retail price (USD)", type: "number", required: true },
    { name: "wholesalePrice", label: "Wholesale price (USD)", type: "number" },
    { name: "minSellingPrice", label: "Minimum selling price (USD)", type: "number", help: "Sales below this need manager approval." },
  ];

  if (productId && product.isLoading) return <p className="p-8 text-center text-sm text-muted-foreground">Loading product...</p>;
  const margin = showCost && product.data?.avgCost && values.retailPrice ? ((values.retailPrice - product.data.avgCost) / values.retailPrice) * 100 : null;

  return (
    <>
      <PageHeader
        title={product.data?.nameEn ?? "New product"}
        description={product.data ? product.data.sku : "Create a catalogue item"}
        actions={
          <>
            {product.data ? <StatusBadge status={product.data.status} /> : null}
            {product.data && can("products.create") ? <Button variant="outline" size="sm" onClick={() => void duplicate.fire(undefined)}><Copy />Duplicate</Button> : null}
            {product.data?.barcodes.length ? <Button variant="outline" size="sm" onClick={() => setLabelsOpen(true)}><Printer />Print labels</Button> : null}
            {canEdit ? (
              <>
                <Button variant="outline" size="sm" disabled={saving} onClick={() => void submit(product.data?.status === "ACTIVE" ? "ACTIVE" : product.data?.status ?? "DRAFT")}>{productId ? "Save" : "Save draft"}</Button>
                {product.data?.status === "ACTIVE" ? (
                  <Button variant="outline" size="sm" disabled={saving} onClick={async () => { if (await confirm({ title: "Deactivate this product?", description: "It will be hidden from the POS. Stock and history are kept.", confirmLabel: "Deactivate" })) void submit("INACTIVE"); }}>Deactivate</Button>
                ) : <Button size="sm" disabled={saving} onClick={() => void submit("ACTIVE")}>Activate</Button>}
              </>
            ) : null}
          </>
        }
      />
      {banner ? <p className="mb-3 rounded-md bg-destructive/10 p-2 text-sm text-destructive" role="alert">{banner}</p> : null}
      <Card className="rounded-lg p-4 shadow-none">
        <Tabs defaultValue="general">
          <TabsList className="h-auto max-w-full flex-wrap justify-start">
            {["General", "Units and barcodes", "Prices", "Inventory", "Suppliers", "Tracking", ...(productId ? ["History"] : [])].map((t) => <TabsTrigger key={t} value={t === "General" ? "general" : t}>{t}</TabsTrigger>)}
          </TabsList>
          <TabsContent value="general" className="space-y-4 pt-3">
            <div className="flex items-center gap-3">
              <ProductVisual image={values.image || null} icon={categories.find((c) => c.id === values.categoryId)?.icon} name={values.nameEn} className="size-16" />
              <div className="space-y-1">
                <Label htmlFor="product-image">Product image</Label>
                <Input id="product-image" type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => uploadImage(e.target.files?.[0])} className="max-w-64" />
                <p className="text-xs text-muted-foreground">JPEG, PNG or WebP, up to 2 MB.</p>
              </div>
            </div>
            <FormFields form={form as never} fields={fields as never} idPrefix="product" />
            {values.type === "VARIANT_PARENT" && !productId ? (
              <div className="space-y-2 rounded-md border p-3">
                <p className="text-sm font-medium">Variants</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  <div className="space-y-1"><Label htmlFor="sizes">Sizes (comma-separated)</Label><Input id="sizes" placeholder="S, M, L" value={variantAttrs.sizes} onChange={(e) => setVariantAttrs((a) => ({ ...a, sizes: e.target.value }))} /></div>
                  <div className="space-y-1"><Label htmlFor="colours">Colours (comma-separated)</Label><Input id="colours" placeholder="Navy, White" value={variantAttrs.colours} onChange={(e) => setVariantAttrs((a) => ({ ...a, colours: e.target.value }))} /></div>
                </div>
                {generated.length ? <p className="text-xs text-muted-foreground">{generated.length} variants will be created: {generated.map((g) => g.sku).join(", ")}</p> : null}
              </div>
            ) : null}
          </TabsContent>
          <TabsContent value="Units and barcodes" className="space-y-5 pt-3">
            <section className="space-y-2">
              <div className="flex items-center justify-between"><h3 className="text-sm font-medium">Unit conversions</h3><Button type="button" variant="outline" size="sm" disabled={!canEdit} onClick={() => setConversions((c) => [...c, { id: crypto.randomUUID(), unitId: "", factor: 1, isPurchaseDefault: false, isSalesDefault: false }])}><Plus />Add unit</Button></div>
              <LineItems lines={conversions} onChange={setConversions} emptyText="This product uses only its base unit." columns={[
                { header: "Unit", cell: (l, u) => <Select value={l.unitId} onValueChange={(v) => u({ unitId: v })}><SelectTrigger size="sm" className="w-44" aria-label="Unit"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{unitOptions.filter((o) => o.value !== values.baseUnitId).map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent></Select> },
                { header: "Base units per unit", cell: (l, u) => <NumberCell label="Conversion factor" value={l.factor} onChange={(factor) => u({ factor })} /> },
                { header: "Purchase default", cell: (l, u) => <Switch aria-label="Purchase default" checked={l.isPurchaseDefault} onCheckedChange={(c) => u({ isPurchaseDefault: c })} /> },
                { header: "Sales default", cell: (l, u) => <Switch aria-label="Sales default" checked={l.isSalesDefault} onCheckedChange={(c) => u({ isSalesDefault: c })} /> },
              ]} />
            </section>
            <section className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-medium">Barcodes</h3>
                <div className="flex gap-2">
                  <Button type="button" variant="outline" size="sm" disabled={!canEdit || !values.baseUnitId} onClick={() => void generateBarcode.fire(undefined)}><Sparkles />Generate internal</Button>
                  <Button type="button" variant="outline" size="sm" disabled={!canEdit} onClick={() => setBarcodes((b) => [...b, { id: "", barcode: "", symbology: "EAN13", unitId: values.baseUnitId, active: true, createdAt: "" }])}><Plus />Add</Button>
                </div>
              </div>
              <LineItems lines={barcodes} onChange={setBarcodes} emptyText="No barcodes yet." columns={[
                { header: "Barcode", cell: (l, u) => <Input aria-label="Barcode" className="h-8 w-44 font-mono" value={l.barcode} onChange={(e) => u({ barcode: e.target.value, symbology: detectSymbology(e.target.value) })} /> },
                { header: "Symbology", cell: (l, u) => <Select value={l.symbology} onValueChange={(v) => u({ symbology: v as BarcodeSymbology })}><SelectTrigger size="sm" className="w-28" aria-label="Symbology"><SelectValue /></SelectTrigger><SelectContent>{["EAN13", "EAN8", "UPCA", "CODE128"].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent></Select> },
                { header: "Unit", cell: (l, u) => <Select value={l.unitId} onValueChange={(v) => u({ unitId: v })}><SelectTrigger size="sm" className="w-24" aria-label="Unit"><SelectValue /></SelectTrigger><SelectContent>{unitOptionsForProduct.map((x) => <SelectItem key={x.id} value={x.id}>{x.code}</SelectItem>)}</SelectContent></Select> },
                { header: "Active", cell: (l, u) => <Switch aria-label="Active" checked={l.active} onCheckedChange={(c) => u({ active: c })} /> },
              ]} />
            </section>
          </TabsContent>
          <TabsContent value="Prices" className="space-y-3 pt-3">
            <FormFields form={form as never} fields={priceFields as never} idPrefix="price" />
            {showCost && product.data ? (
              <div className="grid grid-cols-3 gap-3 rounded-md border p-3 text-sm">
                <div><p className="text-xs text-muted-foreground">Average cost (valuation)</p><p className="tabular font-medium">{formatUsd(product.data.avgCost)}</p></div>
                <div><p className="text-xs text-muted-foreground">Last purchase cost</p><p className="tabular font-medium">{formatUsd(product.data.lastPurchaseCost)}</p></div>
                <div><p className="text-xs text-muted-foreground">Margin at retail</p><p className="tabular font-medium">{margin === null ? "—" : `${margin.toFixed(1)}%`}</p></div>
              </div>
            ) : null}
            <p className="text-xs text-muted-foreground">Costs come from goods receipts and are separate from selling prices. Branch, group and scheduled prices are managed in <Link className="text-primary hover:underline" href="/products/pricing">Pricing</Link>.</p>
          </TabsContent>
          <TabsContent value="Inventory" className="space-y-3 pt-3">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {([["reorderLevel", "Reorder level"], ["minLevel", "Minimum"], ["maxLevel", "Maximum"], ["reorderQty", "Reorder quantity"]] as const).map(([key, label]) => (
                <div key={key} className="space-y-1"><Label htmlFor={key}>{label}</Label><Input id={key} type="number" min={0} value={settings[key]} onChange={(e) => setSettings((s) => ({ ...s, [key]: Number(e.target.value) }))} /></div>
              ))}
            </div>
            <h3 className="pt-2 text-sm font-medium">Warehouse overrides</h3>
            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader><TableRow><TableHead className="h-8">Warehouse</TableHead><TableHead className="h-8">Override</TableHead><TableHead className="h-8 text-right">Reorder</TableHead><TableHead className="h-8 text-right">Max</TableHead></TableRow></TableHeader>
                <TableBody>
                  {warehouses.map((w) => {
                    const own = warehouseSettings[w.id];
                    return (
                      <TableRow key={w.id}>
                        <TableCell className="py-1.5 whitespace-nowrap">{w.name}</TableCell>
                        <TableCell className="py-1.5"><Switch aria-label={`Override ${w.name}`} checked={Boolean(own)} onCheckedChange={(c) => setWarehouseSettings((all) => { const next = { ...all }; if (c) next[w.id] = { ...settings }; else delete next[w.id]; return next; })} /></TableCell>
                        <TableCell className="py-1.5 text-right"><NumberCell label="Reorder level" disabled={!own} value={own?.reorderLevel ?? settings.reorderLevel} onChange={(reorderLevel) => setWarehouseSettings((all) => ({ ...all, [w.id]: { ...all[w.id], reorderLevel } }))} /></TableCell>
                        <TableCell className="py-1.5 text-right"><NumberCell label="Maximum" disabled={!own} value={own?.maxLevel ?? settings.maxLevel} onChange={(maxLevel) => setWarehouseSettings((all) => ({ ...all, [w.id]: { ...all[w.id], maxLevel } }))} /></TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
          <TabsContent value="Suppliers" className="space-y-2 pt-3">
            {!showCost ? <p className="text-sm text-muted-foreground">Supplier costs need cost visibility.</p> : (
              <>
                <div className="flex justify-end"><Button type="button" variant="outline" size="sm" disabled={!canEdit} onClick={() => setSuppliers((s) => [...s, { supplierId: "", supplierSku: "", purchaseUnitId: values.baseUnitId, cost: 0, leadTimeDays: 7, preferred: !s.length }])}><Plus />Link supplier</Button></div>
                <LineItems lines={suppliers} onChange={setSuppliers} emptyText="No suppliers linked." columns={[
                  { header: "Supplier", cell: (l, u) => <Select value={l.supplierId} onValueChange={(v) => u({ supplierId: v })}><SelectTrigger size="sm" className="w-52" aria-label="Supplier"><SelectValue placeholder="Select" /></SelectTrigger><SelectContent>{supplierOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent></Select> },
                  { header: "Supplier SKU", cell: (l, u) => <Input aria-label="Supplier SKU" className="h-8 w-32" value={l.supplierSku} onChange={(e) => u({ supplierSku: e.target.value })} /> },
                  { header: "Cost (USD)", cell: (l, u) => <NumberCell label="Cost" value={l.cost} onChange={(cost) => u({ cost })} /> },
                  { header: "Lead days", cell: (l, u) => <NumberCell label="Lead time" value={l.leadTimeDays} onChange={(leadTimeDays) => u({ leadTimeDays })} /> },
                  { header: "Preferred", cell: (l, u) => <Switch aria-label="Preferred" checked={l.preferred} onCheckedChange={(c) => u({ preferred: c })} /> },
                ]} />
              </>
            )}
          </TabsContent>
          <TabsContent value="Tracking" className="space-y-3 pt-3">
            <FormFields form={form as never} fields={[{ name: "trackExpiry", label: "Track batch and expiry (FEFO)", type: "switch" }, { name: "allowFraction", label: "Allow fractional quantities", type: "switch", disabled: values.type === "WEIGHED" }, { name: "precision", label: "Quantity decimals", type: "number" }] as never} idPrefix="tracking" />
            <p className="text-xs text-muted-foreground">Serial-number tracking and bundles are planned for SRS roadmap phase 7.</p>
          </TabsContent>
          {productId ? (
            <TabsContent value="History" className="pt-3">
              <div className="overflow-x-auto rounded-md border">
                <Table>
                  <TableHeader><TableRow><TableHead className="h-8">When</TableHead><TableHead className="h-8">User</TableHead><TableHead className="h-8">Field</TableHead><TableHead className="h-8">Before</TableHead><TableHead className="h-8">After</TableHead></TableRow></TableHeader>
                  <TableBody>
                    {(history.data ?? []).slice(0, 50).map((h) => <TableRow key={h.id}><TableCell className="py-1.5 whitespace-nowrap">{formatDateTime(h.at)}</TableCell><TableCell className="py-1.5">{h.userName}</TableCell><TableCell className="py-1.5">{h.field}</TableCell><TableCell className="max-w-40 truncate py-1.5" title={h.before}>{h.before}</TableCell><TableCell className="max-w-40 truncate py-1.5" title={h.after}>{h.after}</TableCell></TableRow>)}
                    {history.data && !history.data.length ? <TableRow><TableCell colSpan={5} className="py-6 text-center text-sm text-muted-foreground">No changes recorded yet.</TableCell></TableRow> : null}
                  </TableBody>
                </Table>
              </div>
            </TabsContent>
          ) : null}
        </Tabs>
      </Card>
      {product.data ? <BarcodeLabelDialog open={labelsOpen} onOpenChange={setLabelsOpen} items={product.data.barcodes.filter((b) => b.active).map((b) => ({ barcode: b.barcode, symbology: b.symbology, name: product.data!.nameEn, price: product.data!.retailPrice }))} /> : null}
    </>
  );
}
