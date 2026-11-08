"use client";

import { createColumnHelper, createPaginatedRowModel, createSortedRowModel, rowPaginationFeature, rowSortingFeature, tableFeatures, useTable, type PaginationState, type RowData, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ChevronsUpDown, Download, FileSpreadsheet, Printer, Search, X } from "lucide-react";
import { type ReactNode, useId, useMemo, useState } from "react";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/shared/states";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { exportCsv, exportXlsx, printTable, type ExportRow } from "@/lib/export";
import { cn } from "@/lib/utils";
import { exportsApi } from "@/services";

export type CellValue = string | number | null | undefined;

export interface Column<T extends RowData> {
  id: string;
  header: string;
  value: (row: T) => CellValue;
  cell?: (row: T) => ReactNode;
  align?: "left" | "right" | "center";
  sortable?: boolean;
  /** Hides the column below this breakpoint; it stays in exports. */
  hideBelow?: "sm" | "md" | "lg" | "xl";
  exportable?: boolean;
  className?: string;
}

export interface TableFilter<T extends RowData> {
  id: string;
  label: string;
  options: { value: string; label: string }[];
  value: (row: T) => string | null | undefined;
}

interface DataTableProps<T extends RowData> {
  data: T[] | undefined;
  columns: Column<T>[];
  getRowId: (row: T) => string;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  searchPlaceholder?: string;
  filters?: TableFilter<T>[];
  dateFilter?: { label: string; value: (row: T) => string | null | undefined };
  toolbar?: ReactNode;
  onRowClick?: (row: T) => void;
  exportName?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  pageSize?: number;
  initialSort?: { id: string; desc: boolean };
  /** Extra text to match in search that is not a visible column. */
  searchText?: (row: T) => string;
  initialSearch?: string;
}

const HIDE: Record<NonNullable<Column<RowData>["hideBelow"]>, string> = {
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell",
  xl: "hidden xl:table-cell",
};

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  rowPaginationFeature,
  paginatedRowModel: createPaginatedRowModel(),
});

function compare(a: CellValue, b: CellValue) {
  if (a === b) return 0;
  if (a === null || a === undefined || a === "") return 1;
  if (b === null || b === undefined || b === "") return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function DataTable<T extends RowData>({
  data, columns, getRowId, isLoading, error, onRetry, searchPlaceholder = "Search...", filters = [], dateFilter, toolbar, onRowClick, exportName, emptyTitle = "No records found", emptyDescription, pageSize = 15, initialSort, searchText, initialSearch = "",
}: DataTableProps<T>) {
  const [search, setSearch] = useState(initialSearch);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [sorting, setSorting] = useState<SortingState>(initialSort ? [initialSort] : []);
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize });
  const baseId = useId();

  const visible = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (data ?? []).filter((row) => {
      if (term) {
        const haystack = `${columns.map((c) => c.value(row) ?? "").join(" ")} ${searchText?.(row) ?? ""}`.toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      for (const filter of filters) {
        const chosen = selected[filter.id];
        if (chosen && chosen !== "__all" && filter.value(row) !== chosen) return false;
      }
      if (dateFilter && (from || to)) {
        const date = dateFilter.value(row)?.slice(0, 10);
        if (!date || (from && date < from) || (to && date > to)) return false;
      }
      return true;
    });
    // `filters` is rebuilt each render by callers; the chosen values are what matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, search, selected, from, to, columns]);

  const toFirstPage = () => setPagination((p) => (p.pageIndex === 0 ? p : { ...p, pageIndex: 0 }));

  const tableColumns = useMemo(() => {
    const helper = createColumnHelper<typeof features, T>();
    return helper.columns(
      columns.map((column) =>
        helper.accessor((row: T) => column.value(row), {
          id: column.id,
          header: column.header,
          enableSorting: column.sortable !== false,
          sortFn: (a, b, id) => compare(a.getValue(id) as CellValue, b.getValue(id) as CellValue),
          sortUndefined: "last",
        }),
      ),
    );
  }, [columns]);

  const table = useTable({
    features,
    columns: tableColumns,
    data: visible,
    getRowId,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
  });

  const rows = table.getRowModel().rows;
  const pageCount = Math.max(1, Math.ceil(visible.length / pagination.pageSize));
  const activeFilters = Boolean(search || from || to || Object.values(selected).some((v) => v && v !== "__all"));
  const byId = useMemo(() => new Map(columns.map((c) => [c.id, c])), [columns]);

  const runExport = (format: "csv" | "xlsx") => {
    const exported = columns.filter((c) => c.exportable !== false);
    const exportRows: ExportRow[] = visible.map((row) => Object.fromEntries(exported.map((c) => [c.id, c.value(row)])));
    const cols = exported.map((c) => ({ header: c.header, key: c.id }));
    if (format === "csv") exportCsv(exportName ?? "export", cols, exportRows);
    else exportXlsx(exportName ?? "export", cols, exportRows);
    void exportsApi.audit(exportName ?? "export", format, exportRows.length).catch(() => undefined);
  };

  const runPrint = () => {
    const exported = columns.filter((c) => c.exportable !== false);
    printTable(
      exportName ?? "Export",
      exported.map((c) => ({ header: c.header, key: c.id })),
      visible.map((row) => Object.fromEntries(exported.map((c) => [c.id, c.value(row)]))),
    );
    void exportsApi.audit(exportName ?? "export", "pdf", visible.length).catch(() => undefined);
  };

  const clear = () => {
    setSearch("");
    setSelected({});
    setFrom("");
    setTo("");
    toFirstPage();
  };

  return (
    <div className="min-w-0 overflow-hidden rounded-lg border bg-card">
      <div className="no-print flex flex-col gap-2 border-b p-3 lg:flex-row lg:flex-wrap lg:items-center">
        <div className="relative min-w-0 lg:w-64">
          <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); toFirstPage(); }} placeholder={searchPlaceholder} className="pl-8" aria-label="Search table" />
        </div>
        {filters.map((filter) => (
          <Select key={filter.id} value={selected[filter.id] ?? "__all"} onValueChange={(v) => { setSelected((s) => ({ ...s, [filter.id]: v })); toFirstPage(); }}>
            <SelectTrigger className="w-full lg:w-40" aria-label={filter.label}>
              <SelectValue placeholder={filter.label} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">{`All ${filter.label.toLowerCase()}`}</SelectItem>
              {filter.options.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        ))}
        {dateFilter ? (
          <div className="flex items-center gap-1.5">
            <label htmlFor={`${baseId}-from`} className="sr-only">{`${dateFilter.label} from`}</label>
            <Input id={`${baseId}-from`} type="date" value={from} max={to || undefined} onChange={(e) => { setFrom(e.target.value); toFirstPage(); }} className="min-w-0 flex-1 lg:w-38 lg:flex-none" />
            <span className="text-xs text-muted-foreground">to</span>
            <label htmlFor={`${baseId}-to`} className="sr-only">{`${dateFilter.label} to`}</label>
            <Input id={`${baseId}-to`} type="date" value={to} min={from || undefined} onChange={(e) => { setTo(e.target.value); toFirstPage(); }} className="min-w-0 flex-1 lg:w-38 lg:flex-none" />
          </div>
        ) : null}
        {activeFilters ? <Button variant="ghost" size="sm" onClick={clear}><X />Clear</Button> : null}
        <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
          {exportName ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild><Button variant="outline" size="sm"><Download />Export</Button></DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => runExport("xlsx")}><FileSpreadsheet />Excel (.xlsx)</DropdownMenuItem>
                <DropdownMenuItem onClick={() => runExport("csv")}><Download />CSV</DropdownMenuItem>
                <DropdownMenuItem onClick={runPrint}><Printer />Print or save as PDF</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
          {toolbar}
        </div>
      </div>

      {error ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : isLoading ? (
        <TableSkeleton />
      ) : !visible.length ? (
        <EmptyState title={activeFilters ? "No records match these filters" : emptyTitle} description={activeFilters ? "Try a different search or clear the filters." : emptyDescription} action={activeFilters ? <Button variant="outline" size="sm" onClick={clear}>Clear filters</Button> : undefined} />
      ) : (
        <>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  {table.getHeaderGroups()[0].headers.map((header) => {
                    const column = byId.get(header.column.id)!;
                    const sort = header.column.getIsSorted();
                    const align = column.align === "right" ? "text-right" : column.align === "center" ? "text-center" : "text-left";
                    return (
                      <TableHead key={header.id} className={cn("h-9 text-xs whitespace-nowrap text-muted-foreground", align, column.hideBelow && HIDE[column.hideBelow])} aria-sort={sort === "asc" ? "ascending" : sort === "desc" ? "descending" : "none"}>
                        {header.column.getCanSort() ? (
                          <button type="button" onClick={header.column.getToggleSortingHandler()} className={cn("inline-flex items-center gap-1 rounded hover:text-foreground", column.align === "right" && "flex-row-reverse")}>
                            {column.header}
                            {sort === "asc" ? <ArrowUp className="size-3" /> : sort === "desc" ? <ArrowDown className="size-3" /> : <ChevronsUpDown className="size-3 opacity-40" />}
                          </button>
                        ) : column.header}
                      </TableHead>
                    );
                  })}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow
                    key={row.id}
                    onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                    onKeyDown={onRowClick ? (e) => { if (e.key === "Enter" && e.target === e.currentTarget) onRowClick(row.original); } : undefined}
                    tabIndex={onRowClick ? 0 : undefined}
                    className={cn(onRowClick && "cursor-pointer")}
                  >
                    {row.getAllCells().map((cell) => {
                      const column = byId.get(cell.column.id)!;
                      return (
                        <TableCell key={cell.id} className={cn("py-2 text-sm", column.align === "right" && "text-right tabular", column.align === "center" && "text-center", column.hideBelow && HIDE[column.hideBelow], column.className)}>
                          {column.cell ? column.cell(row.original) : (column.value(row.original) ?? "—")}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="no-print flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2 text-sm text-muted-foreground">
            <span>{visible.length.toLocaleString()} record{visible.length === 1 ? "" : "s"}</span>
            <div className="flex items-center gap-2">
              <Select value={String(pagination.pageSize)} onValueChange={(v) => setPagination({ pageIndex: 0, pageSize: Number(v) })}>
                <SelectTrigger size="sm" className="w-22" aria-label="Rows per page"><SelectValue /></SelectTrigger>
                <SelectContent>{[10, 15, 25, 50, 100].map((n) => <SelectItem key={n} value={String(n)}>{n} rows</SelectItem>)}</SelectContent>
              </Select>
              <span className="tabular whitespace-nowrap">Page {pagination.pageIndex + 1} of {pageCount}</span>
              <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={pagination.pageIndex === 0} onClick={() => setPagination((p) => ({ ...p, pageIndex: p.pageIndex - 1 }))}><ChevronLeft /></Button>
              <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={pagination.pageIndex >= pageCount - 1} onClick={() => setPagination((p) => ({ ...p, pageIndex: p.pageIndex + 1 }))}><ChevronRight /></Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
