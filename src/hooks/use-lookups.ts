"use client";

import { useMemo } from "react";
import { useApiQuery } from "@/hooks/use-api";
import { branchesApi, brandsApi, categoriesApi, customerGroupsApi, locationsApi, suppliersApi, taxCodesApi, unitsApi, warehousesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";

const toOption = <T extends { id: string }>(rows: T[] | undefined, label: (row: T) => string) => (rows ?? []).map((r) => ({ value: r.id, label: label(r) }));

export function useBranchParam() {
  return useUiStore((s) => s.branchId);
}

export function useBranchOptions() {
  const q = useApiQuery(["branches"], () => branchesApi.list());
  return useMemo(() => toOption(q.data, (b) => b.nameEn), [q.data]);
}

export function useWarehouses() {
  const q = useApiQuery(["warehouses"], () => warehousesApi.list());
  return useMemo(() => (q.data ?? []).filter((w) => w.status === "ACTIVE" && w.code !== "WH-SYS"), [q.data]);
}

export function useWarehouseOptions() {
  const rows = useWarehouses();
  return useMemo(() => toOption(rows, (w) => w.name), [rows]);
}

export function useLocations() {
  const q = useApiQuery(["locations"], () => locationsApi.list());
  return q.data ?? [];
}

export function useCategories() {
  const q = useApiQuery(["categories"], () => categoriesApi.list());
  return q.data ?? [];
}

export function useCategoryOptions() {
  const rows = useCategories();
  return useMemo(() => toOption(rows, (c) => c.nameEn), [rows]);
}

export function useBrandOptions() {
  const q = useApiQuery(["brands"], () => brandsApi.list());
  return useMemo(() => toOption(q.data, (b) => b.name), [q.data]);
}

export function useUnits() {
  const q = useApiQuery(["units"], () => unitsApi.list());
  return q.data ?? [];
}

export function useUnitOptions() {
  const rows = useUnits();
  return useMemo(() => toOption(rows, (u) => `${u.code} - ${u.nameEn}`), [rows]);
}

export function useTaxOptions() {
  const q = useApiQuery(["tax-codes"], () => taxCodesApi.list());
  return useMemo(() => toOption(q.data, (t) => `${t.code} (${t.rate}%)`), [q.data]);
}

export function useSupplierOptions() {
  const can = useCan();
  const q = useApiQuery(["suppliers"], () => suppliersApi.list(), { enabled: can("suppliers.view", "purchasing.view") });
  return useMemo(() => toOption(q.data?.filter((s) => s.status === "ACTIVE"), (s) => s.nameEn), [q.data]);
}

export function useCustomerGroupOptions() {
  const q = useApiQuery(["customer-groups"], () => customerGroupsApi.list());
  return useMemo(() => toOption(q.data, (g) => g.name), [q.data]);
}
