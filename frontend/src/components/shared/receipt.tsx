"use client";

import { Printer } from "lucide-react";
import { useRef } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApiQuery } from "@/hooks/use-api";
import { printElement } from "@/lib/export";
import { formatDateTime, formatKhr, formatMoney, formatNumber, formatUsd, titleCase } from "@/lib/format";
import { branchesApi, companyApi, receiptTemplatesApi, settingsApi } from "@/services";
import type { Sale, SalesReturn } from "@/types";

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return <div className={`flex justify-between gap-2 ${strong ? "font-bold" : ""}`}><span>{label}</span><span className="tabular">{value}</span></div>;
}

const Divider = () => <div className="my-1.5 border-t border-dashed border-black/40 dark:border-white/30" />;

/** Rendered from the stored sale snapshot, so reprints match the original (BR-DOC-002). */
export function ReceiptBody({ sale, copy }: { sale: Sale; copy: boolean }) {
  const company = useApiQuery(["company"], companyApi.get);
  const templates = useApiQuery(["receipt-templates"], () => receiptTemplatesApi.list());
  const branches = useApiQuery(["branches"], () => branchesApi.list());
  const settings = useApiQuery(["settings"], settingsApi.get);
  const template = templates.data?.find((t) => t.branchId === sale.branchId) ?? templates.data?.find((t) => !t.branchId);
  const branch = branches.data?.find((b) => b.id === sale.branchId);
  const bilingual = template?.language !== "EN";
  const payments = sale.payments.filter((p) => !["FAILED", "CANCELLED"].includes(p.status));
  return (
    <div className="font-mono text-[11px] leading-snug">
      <div className="text-center">
        {bilingual ? <p>{company.data?.tradingNameKm}</p> : null}
        <p className="text-sm font-bold">{company.data?.tradingNameEn}</p>
        <p>{branch?.nameEn}{bilingual && branch ? ` / ${branch.nameKm}` : ""}</p>
        <p>{branch?.address}</p>
        <p>Tel {branch?.phone}</p>
        {template?.showTaxId && company.data?.taxId ? <p>Tax ID: {company.data.taxId}</p> : null}
      </div>
      {copy ? <p className="my-1 border border-black text-center font-bold dark:border-white">COPY / ច្បាប់ចម្លង · Reprint {sale.reprintCount}</p> : null}
      {sale.status === "VOIDED" ? <p className="my-1 border border-black text-center font-bold dark:border-white">VOIDED</p> : null}
      <Divider />
      <p>Receipt: {sale.receiptNo}</p>
      <p>Date: {formatDateTime(sale.finalizedAt ?? sale.createdAt)}</p>
      <p>Terminal: {sale.terminalName}</p>
      <p>Cashier: {sale.cashierName}</p>
      {sale.customerName ? <p>Customer: {sale.customerName}</p> : null}
      <Divider />
      {sale.lines.map((line) => (
        <div key={line.id} className="mb-1">
          {bilingual && line.nameKm ? <p>{line.nameKm}</p> : null}
          <p>{line.nameEn}</p>
          <Row label={`${formatNumber(line.quantity)} ${line.unitCode} x ${line.unitPrice.toFixed(2)}`} value={(line.grossAmount * (settings.data?.taxInclusive ? 1 + line.taxRate / 100 : 1)).toFixed(2)} />
          {line.discountAmount > 0 ? <Row label={`  Discount${line.promotionName ? ` (${line.promotionName})` : ""}`} value={`-${line.discountAmount.toFixed(2)}`} /> : null}
        </div>
      ))}
      <Divider />
      <Row label="Subtotal" value={sale.subtotal.toFixed(2)} />
      <Row label="Discount" value={sale.discountTotal.toFixed(2)} />
      <Row label="Tax (illustrative)" value={sale.taxTotal.toFixed(2)} />
      <Row label="TOTAL USD" value={sale.grandTotal.toFixed(2)} strong />
      <Row label={`TOTAL KHR (rate ${sale.exchangeRate.toLocaleString()})`} value={formatNumber(sale.grandTotalKhr)} strong />
      <Divider />
      {payments.map((p) => (
        <div key={p.id}>
          <Row label={`${titleCase(p.method)} ${p.currency}${p.reference ? ` ${p.reference}` : ""}`} value={p.currency === "KHR" ? formatNumber(p.amountTendered) : p.amountTendered.toFixed(2)} />
          {p.changeAmount > 0 ? <Row label={`Change ${p.changeCurrency}`} value={p.changeCurrency === "KHR" ? formatNumber(p.changeAmount) : p.changeAmount.toFixed(2)} /> : null}
        </div>
      ))}
      <Divider />
      <div className="text-center">
        <p>{template?.header}</p>
        <p>{template?.footer}</p>
        {sale.loyaltyEarned ? <p>Points earned: {sale.loyaltyEarned}</p> : null}
      </div>
    </div>
  );
}

export function ReceiptDialog({ sale, copy, onClose }: { sale: Sale | null; copy: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <Dialog open={sale !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{copy ? "Receipt copy" : "Receipt preview"}</DialogTitle>
          <DialogDescription>{sale?.receiptNo}</DialogDescription>
        </DialogHeader>
        <div ref={ref} className="rounded-md border p-3">{sale ? <ReceiptBody sale={sale} copy={copy} /> : null}</div>
        <p className="text-xs text-muted-foreground">Prints through the browser dialog. Thermal printing through the local print agent arrives with the backend.</p>
        <DialogFooter><Button onClick={() => printElement(ref.current, "receipt-80")}><Printer />Print</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ReturnReceiptDialog({ record, onClose }: { record: SalesReturn | null; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const company = useApiQuery(["company"], companyApi.get);
  return (
    <Dialog open={record !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Return receipt</DialogTitle>
          <DialogDescription>{record?.returnNo}</DialogDescription>
        </DialogHeader>
        <div ref={ref} className="rounded-md border p-3 font-mono text-[11px] leading-snug">
          {record ? (
            <>
              <p className="text-center text-sm font-bold">{company.data?.tradingNameEn}</p>
              <p className="text-center font-bold">{record.type === "EXCHANGE" ? "EXCHANGE RECEIPT" : "RETURN RECEIPT"}</p>
              <Divider />
              <p>Return: {record.returnNo}</p>
              <p>Original receipt: {record.originalReceiptNo}</p>
              <p>Date: {formatDateTime(record.createdAt)}</p>
              <p>Processed by: {record.createdBy}</p>
              {record.approvedBy ? <p>Approved by: {record.approvedBy}</p> : null}
              <Divider />
              {record.lines.map((l) => <div key={l.saleLineId}><p>{l.name}</p><Row label={`${l.quantity} x ${titleCase(l.condition)}`} value={l.refundAmount.toFixed(2)} /></div>)}
              <Divider />
              <Row label="Refund total" value={formatUsd(record.refundTotal)} strong />
              <Row label="Method" value={titleCase(record.refundMethod)} />
              {record.differencePaid ? <Row label="Difference paid" value={formatMoney(record.differencePaid)} /> : null}
              <Row label="Status" value={titleCase(record.refundStatus)} />
              {record.reference ? <Row label="Reference" value={record.reference} /> : null}
            </>
          ) : null}
        </div>
        <DialogFooter><Button onClick={() => printElement(ref.current, "receipt-80")}><Printer />Print</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export { formatKhr };
