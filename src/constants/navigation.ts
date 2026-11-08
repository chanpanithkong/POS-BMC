import {
  ArrowLeftRight, Banknote, Boxes, ClipboardList, LayoutDashboard, type LucideIcon, Megaphone, PackageSearch, Receipt, Settings, ShoppingCart, Store, Truck, UserCog, Users, Wallet, BarChart3,
} from "lucide-react";
import type { Permission } from "@/types";

export interface NavChild {
  label: string;
  href: string;
  permission?: Permission[];
}

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  permission?: Permission[];
  children?: NavChild[];
}

/** Sidebar source of truth; visibility follows SRS 14.2 through permissions. */
export const NAVIGATION: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, permission: ["dashboard.view"] },
  { label: "POS", href: "/pos", icon: Store, permission: ["pos.sell", "pos.hold"] },
  {
    label: "Products", href: "/products", icon: PackageSearch, permission: ["products.view"],
    children: [
      { label: "Catalogue", href: "/products" },
      { label: "Categories", href: "/products/categories" },
      { label: "Brands", href: "/products/brands" },
      { label: "Units", href: "/products/units" },
      { label: "Barcodes", href: "/products/barcodes" },
      { label: "Pricing", href: "/products/pricing", permission: ["pricing.view"] },
    ],
  },
  {
    label: "Inventory", href: "/inventory", icon: Boxes, permission: ["inventory.view"],
    children: [
      { label: "Overview", href: "/inventory" },
      { label: "Movements", href: "/inventory/movements" },
      { label: "Adjustments", href: "/inventory/adjustments" },
      { label: "Transfers", href: "/inventory/transfers" },
      { label: "Stocktaking", href: "/inventory/stocktakes" },
      { label: "Expiring", href: "/inventory/expiring" },
      { label: "Alerts", href: "/inventory/alerts", permission: ["alerts.view"] },
    ],
  },
  {
    label: "Purchases", href: "/purchases", icon: Truck, permission: ["purchasing.view", "receiving.create"],
    children: [
      { label: "Purchase orders", href: "/purchases", permission: ["purchasing.view"] },
      { label: "Goods receiving", href: "/purchases/receiving", permission: ["receiving.create", "purchasing.view"] },
      { label: "Supplier invoices", href: "/purchases/invoices", permission: ["purchasing.view"] },
      { label: "Purchase returns", href: "/purchases/returns", permission: ["purchasing.view"] },
    ],
  },
  {
    label: "Sales", href: "/sales", icon: Receipt, permission: ["sales.view"],
    children: [
      { label: "Sales history", href: "/sales" },
      { label: "Held sales", href: "/sales/held" },
      { label: "Returns and refunds", href: "/sales/returns", permission: ["returns.create", "sales.view"] },
      { label: "Payment reconciliation", href: "/sales/payments", permission: ["reports.cash"] },
    ],
  },
  {
    label: "Customers", href: "/customers", icon: Users, permission: ["customers.view"],
    children: [
      { label: "Customer list", href: "/customers" },
      { label: "Customer groups", href: "/customers/groups" },
    ],
  },
  { label: "Suppliers", href: "/suppliers", icon: ArrowLeftRight, permission: ["suppliers.view"] },
  { label: "Promotions", href: "/promotions", icon: Megaphone, permission: ["promotions.view"] },
  { label: "Cashier sessions", href: "/cashier-sessions", icon: Banknote, permission: ["cash.session.view", "cash.session.view_all"] },
  {
    label: "Expenses", href: "/expenses", icon: Wallet, permission: ["expenses.view"],
    children: [
      { label: "Expense records", href: "/expenses" },
      { label: "Expense categories", href: "/expenses/categories" },
    ],
  },
  { label: "Reports", href: "/reports", icon: BarChart3, permission: ["reports.sales", "reports.inventory", "reports.purchasing", "reports.cash", "reports.business", "reports.exceptions", "reports.tax"] },
  {
    label: "User management", href: "/users", icon: UserCog, permission: ["users.view"],
    children: [
      { label: "Users", href: "/users" },
      { label: "Roles and permissions", href: "/users/roles" },
      { label: "Employees", href: "/users/employees" },
      { label: "Activity logs", href: "/users/activity", permission: ["audit.view"] },
    ],
  },
  {
    label: "Settings", href: "/settings", icon: Settings, permission: ["settings.view", "imports.manage"],
    children: [
      { label: "Settings", href: "/settings", permission: ["settings.view"] },
      { label: "Import wizard", href: "/settings/import", permission: ["imports.manage"] },
    ],
  },
];

const EXTRA_CRUMBS: Record<string, string> = {
  "/notifications": "Notifications",
  "/profile": "Profile",
};

export interface Crumb {
  label: string;
  href: string;
}

export function breadcrumbsFor(pathname: string): Crumb[] {
  if (EXTRA_CRUMBS[pathname]) return [{ label: EXTRA_CRUMBS[pathname], href: pathname }];
  for (const item of NAVIGATION) {
    const child = item.children?.find((c) => c.href === pathname && c.href !== item.href);
    if (child) return [{ label: item.label, href: item.href }, { label: child.label, href: child.href }];
    if (item.href === pathname) return [{ label: item.label, href: item.href }];
    if (pathname.startsWith(`${item.href}/`)) {
      const nested = item.children?.find((c) => c.href !== item.href && pathname.startsWith(`${c.href}/`));
      return [{ label: item.label, href: item.href }, ...(nested ? [{ label: nested.label, href: nested.href }] : []), { label: "Details", href: pathname }];
    }
  }
  return [];
}

export const NAV_ICON_FALLBACK: LucideIcon = ClipboardList;
export const POS_ICON: LucideIcon = ShoppingCart;
