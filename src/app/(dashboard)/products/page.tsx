"use client";

import { Plus, Trash2, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { ProductVisual } from "@/components/shared/product-visual";
import { Button } from "@/components/ui/button";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBrandOptions, useBranchParam, useCategories, useCategoryOptions, useSupplierOptions } from "@/hooks/use-lookups";
import { formatNumber, formatUsd, titleCase } from "@/lib/format";
import { productsApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import type { ProductListItem } from "@/types";

const STATUS = ["DRAFT", "ACTIVE", "INACTIVE", "DISCONTINUED"].map((value) => ({ value, label: titleCase(value) }));

export default function ProductsPage() {
  const router = useRouter();
  const can = useCan();
  const branchId = useBranchParam();
  const { confirm } = useDialogs();
  const query = useApiQuery(["products", branchId], () => productsApi.list({ branchId }));
  const categories = useCategories();
  const categoryOptions = useCategoryOptions();
  const brandOptions = useBrandOptions();
  const supplierOptions = useSupplierOptions();
  const remove = useApiMutation((id: string) => productsApi.remove(id), { success: "Product deleted" });
  const showCost = can("costs.view");

  const columns = useMemo<Column<ProductListItem>[]>(() => [
    { id: "name", header: "Product", value: (p) => p.nameEn, cell: (p) => (
      <div className="flex min-w-48 items-center gap-2.5">
        <ProductVisual image={p.image} icon={categories.find((c) => c.id === p.categoryId)?.icon} name={p.nameEn} className="size-9 shrink-0" />
        <div className="min-w-0"><p className="truncate font-medium">{p.nameEn}</p><p className="truncate text-xs text-muted-foreground">{p.nameKm}</p></div>
      </div>
    ) },
    { id: "sku", header: "SKU", value: (p) => p.sku, cell: (p) => <span className="font-mono text-xs">{p.sku}</span> },
    { id: "category", header: "Category", value: (p) => p.categoryName, hideBelow: "md" },
    { id: "brand", header: "Brand", value: (p) => p.brandName, hideBelow: "xl" },
    { id: "unit", header: "Unit", value: (p) => p.unitCode, hideBelow: "lg" },
    { id: "price", header: "Price", value: (p) => p.retailPrice, cell: (p) => formatUsd(p.retailPrice), align: "right" },
    ...(showCost ? [{ id: "cost", header: "Avg cost", value: (p: ProductListItem) => p.avgCost ?? 0, cell: (p: ProductListItem) => formatUsd(p.avgCost), align: "right" as const, hideBelow: "lg" as const }] : []),
    { id: "available", header: "Available", value: (p) => (p.type === "SERVICE" || p.type === "VARIANT_PARENT" ? null : p.available), cell: (p) => (p.type === "SERVICE" || p.type === "VARIANT_PARENT" ? "—" : formatNumber(p.available)), align: "right" },
    { id: "status", header: "Status", value: (p) => p.status, cell: (p) => <StatusBadge status={p.status} /> },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (p) => p.status === "DRAFT" && !p.hasMovements && can("products.delete") ? (
      <Button variant="ghost" size="icon-sm" aria-label={`Delete ${p.nameEn}`} onClick={async (e) => { e.stopPropagation(); if (await confirm({ title: "Delete this draft product?", description: `${p.nameEn} will be removed. This cannot be undone.`, confirmLabel: "Delete", destructive: true })) void remove.fire(p.id); }}><Trash2 /></Button>
    ) : null },
    // `can` and `remove` are recreated per render; column identity follows the data it reads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [categories, showCost]);

  return (
    <RequirePermission anyOf={["products.view"]}>
      <PageHeader title="Products" description="Central catalogue shared by all branches" actions={
        <>
          {can("imports.manage") ? <Button asChild variant="outline" size="sm"><Link href="/settings/import"><Upload />Import</Link></Button> : null}
          {can("products.create") ? <Button asChild size="sm"><Link href="/products/new"><Plus />New product</Link></Button> : null}
        </>
      } />
      <DataTable
        data={query.data}
        columns={columns}
        getRowId={(p) => p.id}
        isLoading={query.isLoading}
        error={query.error}
        onRetry={() => void query.refetch()}
        searchPlaceholder="Name, SKU or barcode"
        searchText={(p) => `${p.nameKm} ${p.barcodes.map((b) => b.barcode).join(" ")}`}
        filters={[
          { id: "category", label: "Categories", options: categoryOptions, value: (p) => p.categoryId },
          { id: "brand", label: "Brands", options: brandOptions, value: (p) => p.brandId },
          { id: "status", label: "Statuses", options: STATUS, value: (p) => p.status },
          { id: "supplier", label: "Suppliers", options: supplierOptions, value: (p) => p.suppliers.find((s) => s.preferred)?.supplierId },
          { id: "tracking", label: "Tracking", options: [{ value: "expiry", label: "Expiry tracked" }, { value: "none", label: "Not tracked" }], value: (p) => (p.trackExpiry ? "expiry" : "none") },
        ]}
        onRowClick={(p) => router.push(`/products/${p.id}`)}
        exportName="products"
        emptyDescription="Create a product or import your catalogue."
      />
    </RequirePermission>
  );
}
