"use client";

import { useRouter } from "next/navigation";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { NAVIGATION } from "@/constants/navigation";
import { useApiQuery } from "@/hooks/use-api";
import { useT } from "@/lib/i18n";
import { customersApi, productsApi, salesApi } from "@/services";
import { useCan } from "@/stores/auth-store";

export function GlobalSearch({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const can = useCan();
  const t = useT();
  const products = useApiQuery(["products"], () => productsApi.list(), { enabled: open && can("products.view") });
  const customers = useApiQuery(["customers"], () => customersApi.list(), { enabled: open && can("customers.view") });
  const sales = useApiQuery(["sales", "search"], () => salesApi.list(), { enabled: open && can("sales.view") });

  const go = (href: string) => {
    onOpenChange(false);
    router.push(href);
  };
  const pages = NAVIGATION.flatMap((item) => (item.children?.length ? item.children.filter((c) => !c.permission || can(...c.permission)).map((c) => ({ label: t(c.label), href: c.href, parent: t(item.label) })) : [{ label: t(item.label), href: item.href, parent: "" }]).filter(() => !item.permission || can(...item.permission)));

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Search" description="Search pages, products, customers and receipts">
      <CommandInput placeholder="Search pages, products, customers, receipts..." />
      <CommandList>
        <CommandEmpty>No results.</CommandEmpty>
        <CommandGroup heading="Pages">
          {pages.map((p) => <CommandItem key={p.href} value={`page ${p.parent} ${p.label}`} onSelect={() => go(p.href)}>{p.parent ? `${p.parent} / ` : ""}{p.label}</CommandItem>)}
        </CommandGroup>
        <CommandGroup heading="Products">
          {products.data?.slice(0, 200).map((p) => <CommandItem key={p.id} value={`product ${p.nameEn} ${p.nameKm} ${p.sku} ${p.barcodes.map((b) => b.barcode).join(" ")}`} onSelect={() => go(`/products/${p.id}`)}><span className="font-mono text-xs text-muted-foreground">{p.sku}</span>{p.nameEn}</CommandItem>)}
        </CommandGroup>
        <CommandGroup heading="Customers">
          {customers.data?.slice(0, 200).map((c) => <CommandItem key={c.id} value={`customer ${c.name} ${c.phone} ${c.code}`} onSelect={() => go(`/customers/${c.id}`)}>{c.name}<span className="text-xs text-muted-foreground">{c.phone}</span></CommandItem>)}
        </CommandGroup>
        <CommandGroup heading="Receipts">
          {sales.data?.slice(0, 150).map((s) => <CommandItem key={s.id} value={`receipt ${s.receiptNo}`} onSelect={() => go(`/sales?q=${s.receiptNo}`)}><span className="font-mono text-xs">{s.receiptNo}</span>{s.customerName ?? "Walk-in"}</CommandItem>)}
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
