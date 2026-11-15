"use client";

import { Bell, ChevronDown, ChevronRight, Menu, PanelLeft, Search, Store } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { GlobalSearch } from "@/components/layout/global-search";
import { AppearanceMenu, FullscreenToggle, LanguageMenu, UserMenu } from "@/components/layout/header-controls";
import { PageSkeleton } from "@/components/shared/states";
import { Breadcrumb, BreadcrumbItem, BreadcrumbLink, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { breadcrumbsFor, NAVIGATION, type NavItem } from "@/constants/navigation";
import { useApiMutation, useApiQuery } from "@/hooks/use-api";
import { isMockMode } from "@/lib/api/config";
import { formatDateTime } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { branchesApi, notificationsApi } from "@/services";
import { useAuthStore, useCan } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";

function useVisibleNav() {
  const can = useCan();
  return useMemo(
    () =>
      NAVIGATION.filter((item) => !item.permission || can(...item.permission)).map((item) => ({
        ...item,
        children: item.children?.filter((c) => !c.permission || can(...c.permission)),
      })),
    [can],
  );
}

function NavEntry({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const t = useT();
  const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
  const [toggled, setOpen] = useState<boolean | null>(null);
  const open = toggled ?? active;
  const hasChildren = Boolean(item.children && item.children.length > 1);
  const base = "flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 text-sm font-medium transition-colors hover:bg-sidebar-accent/70";
  const label = t(item.label);

  if (collapsed) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Link href={item.href} aria-label={label} className={cn(base, "justify-center px-0", active && "bg-sidebar-accent text-sidebar-accent-foreground")}><item.icon className="size-4.5" /></Link>
        </TooltipTrigger>
        <TooltipContent side="right">{label}</TooltipContent>
      </Tooltip>
    );
  }
  if (!hasChildren) {
    return <Link href={item.href} onClick={onNavigate} aria-current={active ? "page" : undefined} className={cn(base, active && "bg-sidebar-accent text-sidebar-accent-foreground")}><item.icon className="size-4.5 shrink-0" /><span className="truncate">{label}</span></Link>;
  }
  return (
    <div>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className={cn(base, active && "text-sidebar-accent-foreground")}>
        <item.icon className="size-4.5 shrink-0" />
        <span className="truncate">{label}</span>
        <ChevronDown className={cn("ml-auto size-3.5 transition-transform", !open && "-rotate-90")} />
      </button>
      {open ? (
        <div className="mt-0.5 ml-4.5 space-y-0.5 border-l pl-2.5">
          {item.children?.map((child) => {
            const childActive = pathname === child.href || (child.href !== item.href && pathname.startsWith(`${child.href}/`));
            return <Link key={child.href} href={child.href} onClick={onNavigate} aria-current={childActive ? "page" : undefined} className={cn("block truncate rounded-md px-2.5 py-1.5 text-sm hover:bg-sidebar-accent/70", childActive ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground" : "text-sidebar-foreground/80")}>{t(child.label)}</Link>;
          })}
        </div>
      ) : null}
    </div>
  );
}

function Brand({ collapsed }: { collapsed: boolean }) {
  return (
    <Link href="/dashboard" className="flex h-13 items-center gap-2 border-b px-3.5">
      <span className="grid size-7 shrink-0 place-items-center rounded-md bg-primary text-xs font-bold text-primary-foreground">AB</span>
      {collapsed ? null : <span className="truncate text-sm font-semibold">ABC Mart</span>}
    </Link>
  );
}

function SidebarBody({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const items = useVisibleNav();
  return <nav className="flex-1 space-y-0.5 overflow-y-auto p-2" aria-label="Main">{items.map((item) => <NavEntry key={item.href} item={item} collapsed={collapsed} onNavigate={onNavigate} />)}</nav>;
}

function Notifications() {
  const can = useCan();
  const { data } = useApiQuery(["notifications"], notificationsApi.list, { refetchInterval: 60_000 });
  const markAll = useApiMutation(() => notificationsApi.markRead());
  const unread = data?.filter((n) => !n.read).length ?? 0;
  const router = useRouter();
  void can;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="relative h-8 w-8 rounded-full px-0 text-muted-foreground hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-accent-foreground" aria-label={`Notifications, ${unread} unread`}>
          <Bell className="size-4" />
          {unread ? <span className="tabular absolute -top-1 -right-1 grid h-4 min-w-4 place-items-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-white ring-2 ring-card">{unread > 99 ? "99+" : unread}</span> : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(22rem,calc(100vw-2rem))] p-0">
        <div className="flex items-center justify-between border-b p-2.5">
          <span className="text-sm font-medium">Notifications</span>
          <Button variant="ghost" size="xs" disabled={!unread} onClick={() => void markAll.fire(undefined)}>Mark all read</Button>
        </div>
        <div className="max-h-80 overflow-y-auto">
          {(data ?? []).slice(0, 8).map((n) => (
            <button key={n.id} type="button" onClick={() => n.link && router.push(n.link)} className={cn("block w-full border-b p-2.5 text-left last:border-0 hover:bg-muted/60", !n.read && "bg-accent/40")}>
              <p className="truncate text-sm font-medium">{n.title}</p>
              <p className="line-clamp-2 text-xs text-muted-foreground">{n.message}</p>
              <p className="mt-0.5 text-[11px] text-muted-foreground">{formatDateTime(n.createdAt)}</p>
            </button>
          ))}
          {data && !data.length ? <p className="p-6 text-center text-sm text-muted-foreground">No notifications</p> : null}
        </div>
        <Link href="/notifications" className="block border-t p-2 text-center text-sm font-medium text-primary hover:underline">View all</Link>
      </PopoverContent>
    </Popover>
  );
}

function BranchSelector() {
  const user = useAuthStore((s) => s.user);
  const branchId = useUiStore((s) => s.branchId);
  const setBranch = useUiStore((s) => s.setBranch);
  const can = useCan();
  const t = useT();
  const { data } = useApiQuery(["branches"], () => branchesApi.list());
  const branches = useMemo(() => data?.filter((b) => !user?.branchIds.length || user.branchIds.includes(b.id)) ?? [], [data, user]);
  const consolidated = can("reports.consolidated");
  useEffect(() => {
    if (!branches.length) return;
    if (branchId === "all" && !consolidated) setBranch(branches[0].id);
    if (branchId !== "all" && !branches.some((b) => b.id === branchId)) setBranch(consolidated ? "all" : branches[0].id);
  }, [branchId, branches, consolidated, setBranch]);
  return (
    <Select value={branchId} onValueChange={setBranch}>
      <SelectTrigger size="sm" className="w-full min-w-0 gap-1.5 overflow-hidden [&>span]:truncate" aria-label="Branch"><Store className="size-4 shrink-0 text-muted-foreground" /><SelectValue /></SelectTrigger>
      <SelectContent>
        {consolidated ? <SelectItem value="all">{t("All branches")}</SelectItem> : null}
        {branches.map((b) => <SelectItem key={b.id} value={b.id}>{b.nameEn}</SelectItem>)}
      </SelectContent>
    </Select>
  );
}

/** Kept under their old names: the sign-in page and the POS screen use them too. */
export { AppearanceMenu as ThemeToggle, LanguageMenu as LanguageToggle } from "@/components/layout/header-controls";

function Breadcrumbs() {
  const pathname = usePathname();
  const crumbs = breadcrumbsFor(pathname);
  const t = useT();
  if (!crumbs.length) return null;
  return (
    <Breadcrumb className="no-print mb-3">
      <BreadcrumbList>
        {crumbs.map((crumb, i) => (
          <span key={crumb.href} className="contents">
            {i > 0 ? <BreadcrumbSeparator><ChevronRight /></BreadcrumbSeparator> : null}
            <BreadcrumbItem>
              {i === crumbs.length - 1 ? <BreadcrumbPage>{t(crumb.label)}</BreadcrumbPage> : <BreadcrumbLink asChild><Link href={crumb.href}>{t(crumb.label)}</Link></BreadcrumbLink>}
            </BreadcrumbItem>
          </span>
        ))}
      </BreadcrumbList>
    </Breadcrumb>
  );
}

export function useRequireAuth() {
  const status = useAuthStore((s) => s.status);
  const router = useRouter();
  useEffect(() => {
    if (status === "anonymous") router.replace("/login");
  }, [router, status]);
  return status === "authenticated";
}

export function AppShell({ children }: { children: ReactNode }) {
  const ready = useRequireAuth();
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggle = useUiStore((s) => s.toggleSidebar);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  if (!ready) return <div className="p-6"><PageSkeleton /></div>;

  return (
    <div className="flex min-h-svh">
      <aside className={cn("no-print sticky top-0 hidden h-svh shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground md:flex", collapsed ? "w-14" : "w-14 lg:w-60")}>
        <div className="lg:hidden"><Brand collapsed /></div>
        <div className="hidden lg:block"><Brand collapsed={collapsed} /></div>
        <div className="flex min-h-0 flex-1 flex-col lg:hidden"><SidebarBody collapsed /></div>
        <div className="hidden min-h-0 flex-1 flex-col lg:flex"><SidebarBody collapsed={collapsed} /></div>
      </aside>

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="flex w-72 flex-col gap-0 p-0">
          <SheetHeader className="sr-only"><SheetTitle>Navigation</SheetTitle><SheetDescription>Main menu</SheetDescription></SheetHeader>
          <Brand collapsed={false} />
          <SidebarBody collapsed={false} onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print sticky top-0 z-30 flex h-13 items-center gap-2 border-b bg-card px-3 sm:px-4">
          <Button variant="ghost" size="icon-sm" className="md:hidden" aria-label="Open menu" onClick={() => setMobileOpen(true)}><Menu /></Button>
          <Button variant="ghost" size="icon-sm" className="hidden lg:inline-flex" aria-label="Collapse sidebar" onClick={toggle}><PanelLeft /></Button>
          <div className="w-36 min-w-0 shrink lg:w-44"><BranchSelector /></div>
          <Button variant="outline" size="sm" className="ml-1 hidden w-56 min-w-0 shrink justify-start overflow-hidden text-muted-foreground sm:inline-flex" onClick={() => setSearchOpen(true)}>
            <Search /><span className="truncate">Search</span><kbd className="ml-auto hidden text-[10px] lg:inline">Ctrl K</kbd>
          </Button>
          <Button variant="ghost" size="icon-sm" className="sm:hidden" aria-label="Search" onClick={() => setSearchOpen(true)}><Search /></Button>
          <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2">
            <div className="flex items-center gap-0.5 rounded-full border bg-muted/40 p-0.5">
              <FullscreenToggle />
              <LanguageMenu />
              <AppearanceMenu />
              <Notifications />
            </div>
            <UserMenu />
          </div>
        </header>
        {isMockMode ? <div className="no-print border-b bg-warning/10 px-4 py-1 text-center text-xs text-warning">Demo mode: sample data in this browser, with simulated sign-in. This is not production security.</div> : null}
        <main className="min-w-0 flex-1 p-3 sm:p-4 lg:p-5">
          <Breadcrumbs />
          {children}
        </main>
      </div>
      <GlobalSearch open={searchOpen} onOpenChange={setSearchOpen} />
    </div>
  );
}
