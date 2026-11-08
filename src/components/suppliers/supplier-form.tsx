import { z } from "zod";
import type { FieldDef } from "@/components/shared/form-dialog";
import type { Supplier } from "@/types";

export const supplierSchema = z.object({
  code: z.string().min(1, "Code is required."),
  nameEn: z.string().min(1, "Name is required."),
  nameKm: z.string(),
  taxId: z.string(),
  phone: z.string(),
  email: z.union([z.literal(""), z.email("Enter a valid email.")]),
  address: z.string(),
  paymentTerms: z.string().min(1, "Payment terms are required."),
  currency: z.enum(["USD", "KHR"]),
  leadTimeDays: z.number({ error: "Enter a number." }).int().min(0),
  status: z.enum(["ACTIVE", "INACTIVE"]),
});

export type SupplierForm = z.infer<typeof supplierSchema>;

export const emptySupplier: SupplierForm = { code: "", nameEn: "", nameKm: "", taxId: "", phone: "", email: "", address: "", paymentTerms: "Net 30", currency: "USD", leadTimeDays: 7, status: "ACTIVE" };

export const supplierFields: FieldDef<SupplierForm>[] = [
  { name: "code", label: "Code", required: true },
  { name: "nameEn", label: "Name (English)", required: true },
  { name: "nameKm", label: "Name (Khmer)" },
  { name: "taxId", label: "Tax identifier" },
  { name: "phone", label: "Phone", type: "tel" },
  { name: "email", label: "Email", type: "email" },
  { name: "address", label: "Address", full: true },
  { name: "paymentTerms", label: "Payment terms", required: true },
  { name: "currency", label: "Currency", type: "select", options: [{ value: "USD", label: "USD" }, { value: "KHR", label: "KHR" }] },
  { name: "leadTimeDays", label: "Lead time (days)", type: "number" },
  { name: "status", label: "Status", type: "select", options: [{ value: "ACTIVE", label: "Active" }, { value: "INACTIVE", label: "Inactive" }] },
];

export function toSupplierForm(s: Supplier): SupplierForm {
  return { code: s.code, nameEn: s.nameEn, nameKm: s.nameKm, taxId: s.taxId, phone: s.phone, email: s.email, address: s.address, paymentTerms: s.paymentTerms, currency: s.currency, leadTimeDays: s.leadTimeDays, status: s.status };
}
