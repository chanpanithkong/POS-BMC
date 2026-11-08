import { z } from "zod";
import type { FieldDef, Option } from "@/components/shared/form-dialog";
import type { Customer } from "@/types";

export const customerSchema = z.object({
  code: z.string(),
  name: z.string().min(1, "Name is required."),
  phone: z.string().regex(/^(\+855|0)[\d\s]{8,11}$/, "Enter a phone number in +855 or local format."),
  email: z.union([z.literal(""), z.email("Enter a valid email.")]),
  address: z.string(),
  groupId: z.string(),
  notes: z.string(),
  consentMarketing: z.boolean(),
});

export type CustomerForm = z.infer<typeof customerSchema>;

export const emptyCustomer: CustomerForm = { code: "", name: "", phone: "", email: "", address: "", groupId: "", notes: "", consentMarketing: false };

export function customerFields(groups: Option[]): FieldDef<CustomerForm>[] {
  return [
    { name: "name", label: "Name", required: true },
    { name: "phone", label: "Phone", type: "tel", required: true, placeholder: "012 345 678" },
    { name: "code", label: "Customer code", placeholder: "Blank to generate" },
    { name: "groupId", label: "Group", type: "select", allowNone: "No group", options: groups },
    { name: "email", label: "Email", type: "email" },
    { name: "address", label: "Address" },
    { name: "notes", label: "Notes", type: "textarea", full: true },
    { name: "consentMarketing", label: "Consents to marketing messages", type: "switch", full: true },
  ];
}

export function toCustomerPayload(v: CustomerForm): Partial<Customer> {
  return { ...v, code: v.code || undefined, groupId: v.groupId || null };
}
