"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { type FieldValues, useForm } from "react-hook-form";
import { z } from "zod";
import { CrudPanel } from "@/components/shared/crud-panel";
import { type Column, DataTable } from "@/components/shared/data-table";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { type FieldDef, FormDialog, FormFields } from "@/components/shared/form-dialog";
import { PageHeader, RequirePermission, StatusBadge } from "@/components/shared/page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { useBranchOptions, useLocations, useWarehouses } from "@/hooks/use-lookups";
import { formatDateTime, titleCase } from "@/lib/format";
import { branchesApi, companyApi, locationsApi, paymentMethodsApi, ratesApi, receiptTemplatesApi, sequencesApi, settingsApi, taxCodesApi, terminalsApi, usersApi, warehousesApi } from "@/services";
import { useCan } from "@/stores/auth-store";
import { type Branch, type DocumentSequence, type ExchangeRate, LOCATION_TYPES, type PaymentMethodConfig, type ReceiptTemplate, type StockLocation, type TaxCode, type Terminal, type Warehouse } from "@/types";

const STATUS = [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }];
const statusEnum = z.enum(["ACTIVE", "INACTIVE"]);
const code = z.string().min(1, "Code is required.");
const name = z.string().min(1, "Name is required.");
const statusColumn = <T extends { status: string }>(): Column<T> => ({ id: "status", header: "Status", value: (r) => r.status, cell: (r) => <StatusBadge status={r.status} /> });
const codeColumn = <T extends { code: string }>(): Column<T> => ({ id: "code", header: "Code", value: (r) => r.code, cell: (r) => <span className="font-mono text-xs">{r.code}</span> });

function SettingsForm<T extends FieldValues>({ schema, values, fields, onSave, disabled }: { schema: z.ZodType<T, FieldValues>; values: T | undefined; fields: FieldDef<T>[]; onSave: (v: T) => Promise<unknown>; disabled: boolean }) {
  const form = useForm<T>({ resolver: zodResolver(schema) as never });
  useEffect(() => {
    if (values) form.reset(values as never);
    // Resets only when the saved record changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values]);
  return (
    <Card className="gap-3 rounded-lg p-4 shadow-none">
      <form onSubmit={form.handleSubmit((v) => onSave(v as T).catch(() => undefined))} noValidate className="space-y-3">
        <fieldset disabled={disabled} className="space-y-3"><FormFields form={form as never} fields={fields as never} /></fieldset>
        {disabled ? <p className="text-xs text-muted-foreground">Your role can view these settings but not change them.</p> : <Button type="submit" size="sm" disabled={form.formState.isSubmitting}>Save changes</Button>}
      </form>
    </Card>
  );
}

const companySchema = z.object({ legalNameEn: name, legalNameKm: z.string(), tradingNameEn: name, tradingNameKm: z.string(), address: z.string(), phone: z.string(), taxId: z.string(), baseCurrency: z.enum(["USD", "KHR"]), fiscalYearStartMonth: z.number({ error: "Enter a month." }).int().min(1).max(12) });
type CompanyForm = z.infer<typeof companySchema>;

const generalSchema = z.object({ skuMode: z.enum(["AUTO", "MANUAL"]), skuPrefix: z.string(), branchPricingEnabled: z.boolean(), reducedSodMode: z.boolean(), negativeStockAllowed: z.boolean(), posIdleLockMinutes: z.number({ error: "Enter a number." }).min(1), returnWindowDays: z.number({ error: "Enter a number." }).min(0), storeCreditEnabled: z.boolean(), overDeliveryTolerancePct: z.number({ error: "Enter a number." }).min(0), countVarianceRecountQty: z.number({ error: "Enter a number." }).min(0), adjustmentAlertValue: z.number({ error: "Enter a number." }).min(0), transferApprovalValue: z.number({ error: "Enter a number." }).min(0), slowMovingDays: z.number({ error: "Enter a number." }).min(1), expiryWarningDays: z.number({ error: "Enter a number." }).min(1) });
type GeneralForm = z.infer<typeof generalSchema>;

const financeSchema = z.object({ taxInclusive: z.boolean(), khrCashIncrement: z.number({ error: "Enter a number." }).positive(), sessionVarianceToleranceUsd: z.number({ error: "Enter a number." }).min(0), sessionVarianceToleranceKhr: z.number({ error: "Enter a number." }).min(0), cashMovementApprovalThreshold: z.number({ error: "Enter a number." }).min(0), refundCashApprovalThreshold: z.number({ error: "Enter a number." }).min(0), expenseApprovalThreshold: z.number({ error: "Enter a number." }).min(0), expenseAttachmentThreshold: z.number({ error: "Enter a number." }).min(0) });
type FinanceForm = z.infer<typeof financeSchema>;

const branchSchema = z.object({ code, nameEn: name, nameKm: z.string(), address: z.string(), phone: z.string(), receiptHeader: z.string(), openTime: z.string(), closeTime: z.string(), dayCutoff: z.string(), status: statusEnum });
type BranchForm = z.infer<typeof branchSchema>;
const warehouseSchema = z.object({ code, name, branchId: z.string(), status: statusEnum });
type WarehouseForm = z.infer<typeof warehouseSchema>;
const locationSchema = z.object({ code, name, warehouseId: z.string().min(1, "Select a warehouse."), type: z.enum(LOCATION_TYPES), availableToSell: z.boolean(), status: statusEnum });
type LocationForm = z.infer<typeof locationSchema>;
const terminalSchema = z.object({ code, name, branchId: z.string().min(1, "Select a branch."), defaultLocationId: z.string().min(1, "Select a location."), printerProfile: z.enum(["58mm", "80mm"]), cashDrawer: z.boolean(), status: statusEnum, cashierId: z.string() });
type TerminalForm = z.infer<typeof terminalSchema>;
const taxSchema = z.object({ code, name, rate: z.number({ error: "Enter a rate." }).min(0).max(100), status: statusEnum });
type TaxForm = z.infer<typeof taxSchema>;
const templateSchema = z.object({ name, branchId: z.string(), language: z.enum(["EN", "KM", "BILINGUAL"]), paperWidth: z.enum(["58mm", "80mm"]), header: z.string(), footer: z.string(), showLogo: z.boolean(), showTaxId: z.boolean(), showQr: z.boolean() });
type TemplateForm = z.infer<typeof templateSchema>;
const rateSchema = z.object({ rate: z.number({ error: "Enter a rate." }).positive("Rate must be greater than zero.") });
type RateForm = z.infer<typeof rateSchema>;
const sequenceSchema = z.object({ prefix: z.string().min(1, "Prefix is required."), nextValue: z.number({ error: "Enter a number." }).int().min(1), padding: z.number({ error: "Enter a number." }).int().min(1).max(10), includeBranch: z.boolean(), includeYear: z.boolean() });
type SequenceForm = z.infer<typeof sequenceSchema>;

export default function SettingsPage() {
  const can = useCan();
  const manage = can("settings.manage");
  const { confirm } = useDialogs();
  const company = useApiQuery(["company"], companyApi.get);
  const settings = useApiQuery(["settings"], settingsApi.get);
  const rates = useApiQuery(["rates"], ratesApi.list);
  const sequences = useApiQuery(["sequences"], sequencesApi.list);
  const methods = useApiQuery(["payment-methods"], () => paymentMethodsApi.list());
  const users = useApiQuery(["users"], () => usersApi.list(), { enabled: can("users.view") });
  const branches = useBranchOptions();
  const warehouses = useWarehouses();
  const locations = useLocations();
  const [rateOpen, setRateOpen] = useState(false);
  const [editingSeq, setEditingSeq] = useState<DocumentSequence | null>(null);

  const saveCompany = useApiMutation((v: CompanyForm) => companyApi.update(v), { success: "Company saved" });
  const saveSettings = useApiMutation((v: Partial<GeneralForm & FinanceForm>) => settingsApi.update(v), { success: "Settings saved" });
  const addRate = useApiMutation((v: RateForm) => ratesApi.create(v.rate), { success: "Exchange rate saved", silentError: true });
  const saveSeq = useApiMutation((v: SequenceForm) => sequencesApi.update(editingSeq?.id ?? "", v), { success: "Numbering saved", silentError: true });
  const toggleMethod = useApiMutation((m: PaymentMethodConfig) => paymentMethodsApi.update(m.id, { status: m.status === "ACTIVE" ? "INACTIVE" : "ACTIVE" }), { success: "Payment method updated" });

  const tabs = ["Company", "Branches", "Warehouses", "Locations", "Terminals", "Tax", "Currency", "Payment methods", "Numbering", "Receipts", "General", "Finance"];
  const whOptions = warehouses.map((w) => ({ value: w.id, label: w.name }));
  const cashierOptions = (users.data ?? []).map((u) => ({ value: u.id, label: u.fullName }));

  const rateColumns: Column<ExchangeRate>[] = [
    { id: "at", header: "Effective", value: (r) => r.effectiveAt, cell: (r) => formatDateTime(r.effectiveAt) },
    { id: "pair", header: "Pair", value: (r) => `${r.from}/${r.to}` },
    { id: "rate", header: "Rate", value: (r) => r.rate, align: "right" },
    { id: "by", header: "Set by", value: (r) => r.createdBy, hideBelow: "sm" },
  ];
  const seqColumns: Column<DocumentSequence>[] = [
    { id: "doc", header: "Document", value: (s) => titleCase(s.docType) },
    { id: "prefix", header: "Prefix", value: (s) => s.prefix, cell: (s) => <span className="font-mono text-xs">{s.prefix}</span> },
    { id: "scope", header: "Scope", value: (s) => `${s.includeBranch ? "Branch, " : ""}${s.includeYear ? "Year" : ""}` },
    { id: "padding", header: "Digits", value: (s) => s.padding, align: "right" },
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (s) => (manage ? <Button size="sm" variant="ghost" onClick={() => setEditingSeq(s)}>Edit</Button> : null) },
  ];
  const methodColumns: Column<PaymentMethodConfig>[] = [
    { id: "name", header: "Method", value: (m) => m.name },
    { id: "provider", header: "Provider", value: (m) => m.provider, hideBelow: "sm" },
    { id: "ref", header: "Reference", value: (m) => (m.requiresReference ? "Required" : "Not required"), hideBelow: "sm" },
    statusColumn<PaymentMethodConfig>(),
    { id: "actions", header: "", value: () => "", sortable: false, exportable: false, align: "right", cell: (m) => (manage ? <Button size="sm" variant="ghost" onClick={async () => { if (m.status === "INACTIVE" || (await confirm({ title: `Disable ${m.name}?`, description: "Cashiers can no longer select this method.", confirmLabel: "Disable" }))) void toggleMethod.fire(m); }}>{m.status === "ACTIVE" ? "Disable" : "Enable"}</Button> : null) },
  ];

  return (
    <RequirePermission anyOf={["settings.view"]}>
      <PageHeader title="Settings" description="Tax rates and receipt content are placeholders until confirmed (V-01, V-02)" />
      <Tabs defaultValue="Company">
        <TabsList className="h-auto max-w-full flex-wrap justify-start">{tabs.map((t) => <TabsTrigger key={t} value={t}>{t}</TabsTrigger>)}</TabsList>
        <TabsContent value="Company">
          <SettingsForm<CompanyForm> schema={companySchema} disabled={!manage} values={company.data ? { legalNameEn: company.data.legalNameEn, legalNameKm: company.data.legalNameKm, tradingNameEn: company.data.tradingNameEn, tradingNameKm: company.data.tradingNameKm, address: company.data.address, phone: company.data.phone, taxId: company.data.taxId, baseCurrency: company.data.baseCurrency, fiscalYearStartMonth: company.data.fiscalYearStartMonth } : undefined} onSave={(v) => saveCompany.run(v)}
            fields={[{ name: "legalNameEn", label: "Legal name (English)", required: true }, { name: "legalNameKm", label: "Legal name (Khmer)" }, { name: "tradingNameEn", label: "Trading name (English)", required: true }, { name: "tradingNameKm", label: "Trading name (Khmer)" }, { name: "address", label: "Address", full: true }, { name: "phone", label: "Phone" }, { name: "taxId", label: "Tax identifier" }, { name: "baseCurrency", label: "Base currency", type: "select", disabled: true, options: [{ value: "USD", label: "USD" }, { value: "KHR", label: "KHR" }] }, { name: "fiscalYearStartMonth", label: "Fiscal year start month", type: "number" }]} />
        </TabsContent>
        <TabsContent value="Branches">
          <CrudPanel<Branch, BranchForm, Partial<Branch>> queryKey="branches" singular="Branch" api={branchesApi} canManage={manage} schema={branchSchema} wide exportName="branches"
            empty={{ code: "", nameEn: "", nameKm: "", address: "", phone: "", receiptHeader: "", openTime: "07:00", closeTime: "22:00", dayCutoff: "02:00", status: "ACTIVE" }}
            columns={[codeColumn<Branch>(), { id: "name", header: "Name", value: (b) => b.nameEn }, { id: "address", header: "Address", value: (b) => b.address, hideBelow: "md" }, { id: "hours", header: "Hours", value: (b) => `${b.openTime} to ${b.closeTime}`, hideBelow: "lg" }, { id: "cut", header: "Day cut-off", value: (b) => b.dayCutoff, hideBelow: "lg" }, statusColumn<Branch>()]}
            fields={[{ name: "code", label: "Code", required: true }, { name: "nameEn", label: "Name (English)", required: true }, { name: "nameKm", label: "Name (Khmer)" }, { name: "phone", label: "Phone" }, { name: "address", label: "Address", full: true }, { name: "receiptHeader", label: "Receipt header", full: true }, { name: "openTime", label: "Opens", type: "time" }, { name: "closeTime", label: "Closes", type: "time" }, { name: "dayCutoff", label: "Business day cut-off", type: "time", help: "Sales before this time count on the previous day." }, { name: "status", label: "Status", type: "select", options: STATUS }]}
            toForm={(b) => ({ code: b.code, nameEn: b.nameEn, nameKm: b.nameKm, address: b.address, phone: b.phone, receiptHeader: b.receiptHeader, openTime: b.openTime, closeTime: b.closeTime, dayCutoff: b.dayCutoff, status: b.status })} toPayload={(v) => v} />
        </TabsContent>
        <TabsContent value="Warehouses">
          <CrudPanel<Warehouse, WarehouseForm, Partial<Warehouse>> queryKey="warehouses" singular="Warehouse" api={warehousesApi} canManage={manage} schema={warehouseSchema} exportName="warehouses" empty={{ code: "", name: "", branchId: "", status: "ACTIVE" }}
            columns={[codeColumn<Warehouse>(), { id: "name", header: "Name", value: (w) => w.name }, { id: "branch", header: "Branch", value: (w) => branches.find((b) => b.value === w.branchId)?.label ?? "Central" }, statusColumn<Warehouse>()]}
            fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "branchId", label: "Branch", type: "select", allowNone: "Central warehouse", options: branches }, { name: "status", label: "Status", type: "select", options: STATUS }]}
            toForm={(w) => ({ code: w.code, name: w.name, branchId: w.branchId ?? "", status: w.status })} toPayload={(v) => ({ ...v, branchId: v.branchId || null, isCentral: !v.branchId })} />
        </TabsContent>
        <TabsContent value="Locations">
          <CrudPanel<StockLocation, LocationForm, Partial<StockLocation>> queryKey="locations" singular="Location" api={locationsApi} canManage={manage} schema={locationSchema} exportName="locations" empty={{ code: "", name: "", warehouseId: "", type: "STORAGE", availableToSell: false, status: "ACTIVE" }}
            filters={[{ id: "wh", label: "Warehouses", options: whOptions, value: (l) => l.warehouseId }]} canDelete={(l) => l.type !== "IN_TRANSIT"}
            columns={[codeColumn<StockLocation>(), { id: "name", header: "Name", value: (l) => l.name }, { id: "wh", header: "Warehouse", value: (l) => warehouses.find((w) => w.id === l.warehouseId)?.name ?? "System" }, { id: "type", header: "Type", value: (l) => titleCase(l.type) }, { id: "ats", header: "Sellable", value: (l) => (l.availableToSell ? "Yes" : "No"), hideBelow: "md" }, statusColumn<StockLocation>()]}
            fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "warehouseId", label: "Warehouse", type: "select", required: true, options: whOptions }, { name: "type", label: "Type", type: "select", options: LOCATION_TYPES.filter((t) => t !== "IN_TRANSIT").map((value) => ({ value, label: titleCase(value) })) }, { name: "status", label: "Status", type: "select", options: STATUS }, { name: "availableToSell", label: "Counts as available to sell", type: "switch" }]}
            toForm={(l) => ({ code: l.code, name: l.name, warehouseId: l.warehouseId, type: l.type, availableToSell: l.availableToSell, status: l.status })} toPayload={(v) => v} />
        </TabsContent>
        <TabsContent value="Terminals">
          <CrudPanel<Terminal, TerminalForm, Partial<Terminal>> queryKey="terminals" singular="Terminal" api={terminalsApi} canManage={manage} schema={terminalSchema} wide exportName="terminals" empty={{ code: "", name: "", branchId: "", defaultLocationId: "", printerProfile: "80mm", cashDrawer: true, status: "ACTIVE", cashierId: "" }}
            columns={[codeColumn<Terminal>(), { id: "name", header: "Name", value: (t) => t.name }, { id: "branch", header: "Branch", value: (t) => branches.find((b) => b.value === t.branchId)?.label, hideBelow: "md" }, { id: "printer", header: "Printer", value: (t) => t.printerProfile, hideBelow: "lg" }, { id: "assigned", header: "Assigned cashiers", value: (t) => (t.assignedCashierIds.length || "Any"), hideBelow: "lg" }, statusColumn<Terminal>()]}
            fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "branchId", label: "Branch", type: "select", required: true, options: branches }, { name: "defaultLocationId", label: "Default sellable location", type: "select", required: true, options: locations.filter((l) => l.type === "SELLABLE").map((l) => ({ value: l.id, label: `${warehouses.find((w) => w.id === l.warehouseId)?.name} / ${l.name}` })) }, { name: "printerProfile", label: "Printer profile", type: "select", options: [{ value: "80mm", label: "80 mm" }, { value: "58mm", label: "58 mm" }] }, { name: "cashierId", label: "Restrict to cashier", type: "select", allowNone: "Any permitted cashier", options: cashierOptions }, { name: "status", label: "Status", type: "select", options: STATUS }, { name: "cashDrawer", label: "Cash drawer attached", type: "switch" }]}
            toForm={(t) => ({ code: t.code, name: t.name, branchId: t.branchId, defaultLocationId: t.defaultLocationId, printerProfile: t.printerProfile, cashDrawer: t.cashDrawer, status: t.status, cashierId: t.assignedCashierIds[0] ?? "" })}
            toPayload={({ cashierId, ...v }) => ({ ...v, assignedCashierIds: cashierId ? [cashierId] : [] })} />
        </TabsContent>
        <TabsContent value="Tax">
          <CrudPanel<TaxCode, TaxForm, Partial<TaxCode>> queryKey="tax-codes" singular="Tax code" api={taxCodesApi} canManage={manage} schema={taxSchema} exportName="tax-codes" empty={{ code: "", name: "", rate: 0, status: "ACTIVE" }}
            columns={[codeColumn<TaxCode>(), { id: "name", header: "Name", value: (t) => t.name }, { id: "rate", header: "Rate", value: (t) => t.rate, cell: (t) => `${t.rate}%`, align: "right" }, statusColumn<TaxCode>()]}
            fields={[{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "rate", label: "Rate %", type: "number", required: true, help: "Confirm rates with a tax professional (V-01)." }, { name: "status", label: "Status", type: "select", options: STATUS }]}
            toForm={(t) => ({ code: t.code, name: t.name, rate: t.rate, status: t.status })} toPayload={(v) => v} />
        </TabsContent>
        <TabsContent value="Currency"><DataTable data={rates.data} columns={rateColumns} getRowId={(r) => r.id} isLoading={rates.isLoading} error={rates.error} searchPlaceholder="Search rates" toolbar={manage ? <Button size="sm" onClick={() => setRateOpen(true)}><Plus />New rate</Button> : undefined} emptyTitle="No exchange rates" /></TabsContent>
        <TabsContent value="Payment methods"><DataTable data={methods.data} columns={methodColumns} getRowId={(m) => m.id} isLoading={methods.isLoading} error={methods.error} searchPlaceholder="Search methods" /></TabsContent>
        <TabsContent value="Numbering"><DataTable data={sequences.data} columns={seqColumns} getRowId={(s) => s.id} isLoading={sequences.isLoading} error={sequences.error} searchPlaceholder="Search documents" /></TabsContent>
        <TabsContent value="Receipts">
          <CrudPanel<ReceiptTemplate, TemplateForm, Partial<ReceiptTemplate>> queryKey="receipt-templates" singular="Template" api={receiptTemplatesApi} canManage={manage} schema={templateSchema} wide empty={{ name: "", branchId: "", language: "BILINGUAL", paperWidth: "80mm", header: "", footer: "", showLogo: true, showTaxId: false, showQr: true }}
            columns={[{ id: "name", header: "Name", value: (t) => t.name }, { id: "branch", header: "Branch", value: (t) => branches.find((b) => b.value === t.branchId)?.label ?? "All branches" }, { id: "lang", header: "Language", value: (t) => titleCase(t.language) }, { id: "width", header: "Paper", value: (t) => t.paperWidth }]}
            fields={[{ name: "name", label: "Name", required: true }, { name: "branchId", label: "Branch", type: "select", allowNone: "All branches", options: branches }, { name: "language", label: "Language", type: "select", options: [{ value: "EN", label: "English" }, { value: "KM", label: "Khmer" }, { value: "BILINGUAL", label: "Bilingual" }] }, { name: "paperWidth", label: "Paper width", type: "select", options: [{ value: "80mm", label: "80 mm" }, { value: "58mm", label: "58 mm" }] }, { name: "header", label: "Header text", full: true }, { name: "footer", label: "Footer text", full: true }, { name: "showLogo", label: "Show logo", type: "switch" }, { name: "showTaxId", label: "Show tax ID", type: "switch" }, { name: "showQr", label: "Show lookup QR", type: "switch" }]}
            toForm={(t) => ({ name: t.name, branchId: t.branchId ?? "", language: t.language, paperWidth: t.paperWidth, header: t.header, footer: t.footer, showLogo: t.showLogo, showTaxId: t.showTaxId, showQr: t.showQr })} toPayload={(v) => ({ ...v, branchId: v.branchId || null })} />
        </TabsContent>
        <TabsContent value="General">
          <SettingsForm<GeneralForm> schema={generalSchema} disabled={!manage} values={settings.data} onSave={(v) => saveSettings.run(v)}
            fields={[{ name: "skuMode", label: "SKU generation", type: "select", options: [{ value: "AUTO", label: "Automatic" }, { value: "MANUAL", label: "Manual" }] }, { name: "skuPrefix", label: "SKU prefix" }, { name: "posIdleLockMinutes", label: "POS idle lock (minutes)", type: "number" }, { name: "returnWindowDays", label: "Default return window (days)", type: "number" }, { name: "overDeliveryTolerancePct", label: "Over-delivery tolerance %", type: "number" }, { name: "countVarianceRecountQty", label: "Recount at variance of", type: "number" }, { name: "adjustmentAlertValue", label: "Unusual adjustment alert (USD)", type: "number" }, { name: "transferApprovalValue", label: "Transfer self-approval limit (USD)", type: "number" }, { name: "slowMovingDays", label: "Slow-moving period (days)", type: "number" }, { name: "expiryWarningDays", label: "Expiry warning (days)", type: "number" }, { name: "branchPricingEnabled", label: "Branch-specific pricing", type: "switch" }, { name: "storeCreditEnabled", label: "Store credit", type: "switch" }, { name: "negativeStockAllowed", label: "Allow negative stock (D-06)", type: "switch" }, { name: "reducedSodMode", label: "Reduced separation of duties (D-13)", type: "switch" }]} />
        </TabsContent>
        <TabsContent value="Finance">
          <SettingsForm<FinanceForm> schema={financeSchema} disabled={!manage} values={settings.data} onSave={(v) => saveSettings.run(v)}
            fields={[{ name: "khrCashIncrement", label: "KHR cash rounding increment", type: "number" }, { name: "sessionVarianceToleranceUsd", label: "Session tolerance (USD)", type: "number" }, { name: "sessionVarianceToleranceKhr", label: "Session tolerance (KHR)", type: "number" }, { name: "cashMovementApprovalThreshold", label: "Cash movement approval above (USD)", type: "number" }, { name: "refundCashApprovalThreshold", label: "Cash refund approval above (USD)", type: "number" }, { name: "expenseApprovalThreshold", label: "Expense approval above (USD)", type: "number" }, { name: "expenseAttachmentThreshold", label: "Expense document above (USD)", type: "number" }, { name: "taxInclusive", label: "Selling prices include tax", type: "switch", help: "Confirm with a tax professional (V-01)." }]} />
        </TabsContent>
      </Tabs>
      <FormDialog<RateForm> open={rateOpen} onOpenChange={setRateOpen} title="New USD/KHR rate" description="Applies to new payments. History is kept." schema={rateSchema} defaultValues={{ rate: rates.data?.[0]?.rate ?? 4100 }} fields={[{ name: "rate", label: "KHR per 1 USD", type: "number", required: true, full: true }]} onSubmit={(v) => addRate.run(v)} />
      <FormDialog<SequenceForm> open={editingSeq !== null} onOpenChange={(o) => !o && setEditingSeq(null)} title={`Numbering: ${editingSeq ? titleCase(editingSeq.docType) : ""}`} description="Numbers are never reused." schema={sequenceSchema} onSubmit={(v) => saveSeq.run(v)} defaultValues={{ prefix: editingSeq?.prefix ?? "", nextValue: editingSeq?.nextValue ?? 1, padding: editingSeq?.padding ?? 5, includeBranch: editingSeq?.includeBranch ?? false, includeYear: editingSeq?.includeYear ?? true }}
        fields={[{ name: "prefix", label: "Prefix", required: true }, { name: "padding", label: "Digits", type: "number" }, { name: "nextValue", label: "Next value", type: "number" }, { name: "includeBranch", label: "Include branch code", type: "switch" }, { name: "includeYear", label: "Include year", type: "switch" }]} />
    </RequirePermission>
  );
}
