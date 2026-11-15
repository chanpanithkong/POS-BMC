"use client";

import { Bell, Check, ChevronDown, Database, Languages, LogOut, Maximize2, Minimize2, Monitor, Moon, Palette, RotateCcw, ShieldCheck, Sun, UserRound } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";
import { useDialogs } from "@/components/shared/dialogs-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { isMockMode } from "@/lib/api/config";
import { ACCENTS, DEFAULT_ACCENT, DEFAULT_FONT_SIZE, FONT_SIZES } from "@/lib/appearance";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { useUiStore } from "@/stores/ui-store";

const LANGUAGES = [
  { id: "en", short: "EN", native: "English", english: "English" },
  { id: "km", short: "ខ្មែរ", native: "ភាសាខ្មែរ", english: "Khmer" },
] as const;

const subscribeNothing = () => () => {};

const subscribeFullscreen = (onChange: () => void) => {
  document.addEventListener("fullscreenchange", onChange);
  return () => document.removeEventListener("fullscreenchange", onChange);
};

/**
 * Full-screen toggle (the browser's own Fullscreen API, same as F11). Hidden where the browser
 * does not allow it, for example inside some embedded views. Esc also leaves full screen.
 */
export function FullscreenToggle() {
  const t = useT();
  const supported = useSyncExternalStore(subscribeNothing, () => Boolean(document.fullscreenEnabled), () => false);
  const active = useSyncExternalStore(subscribeFullscreen, () => Boolean(document.fullscreenElement), () => false);
  if (!supported) return null;
  const label = active ? t("Exit full screen") : t("Full screen");
  const toggle = () => {
    const request = active ? document.exitFullscreen() : document.documentElement.requestFullscreen({ navigationUI: "hide" });
    void request.catch(() => undefined); // refused by the browser (no user gesture or policy): nothing to undo
  };
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button variant="ghost" size="sm" className={cn(pill, "hidden w-8 px-0 sm:inline-flex", active && "bg-accent text-accent-foreground")} aria-label={label} aria-pressed={active} onClick={toggle}>
          {active ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">{label} <span className="ml-1 opacity-70">F11</span></TooltipContent>
    </Tooltip>
  );
}

/** Rounded ghost button used for every icon control in the header. */
const pill = "h-8 rounded-full px-2.5 text-muted-foreground hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-accent-foreground";

export function LanguageMenu() {
  const language = useUiStore((s) => s.language);
  const setLanguage = useUiStore((s) => s.setLanguage);
  const t = useT();
  const current = LANGUAGES.find((l) => l.id === language) ?? LANGUAGES[0];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className={cn(pill, "w-8 gap-1.5 px-0 sm:w-auto sm:px-2.5")} aria-label={`${t("Language")}: ${current.english}`}>
          <Languages className="size-4" />
          <span className="hidden text-xs font-semibold text-foreground sm:inline">{current.short}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56 p-1.5">
        <DropdownMenuLabel className="px-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">{t("Language")}</DropdownMenuLabel>
        {LANGUAGES.map((l) => {
          const active = l.id === language;
          return (
            <DropdownMenuItem key={l.id} onSelect={() => setLanguage(l.id)} className={cn("gap-3 rounded-md py-2", active && "bg-accent/60")}>
              <span className={cn("grid h-7 min-w-9 place-items-center rounded-md border px-1.5 text-xs font-semibold", active ? "border-primary/40 bg-primary text-primary-foreground" : "bg-muted text-foreground")}>{l.short}</span>
              <span className="min-w-0 flex-1 leading-tight">
                <span className="block text-sm font-medium">{l.native}</span>
                {l.native !== l.english ? <span className="block text-xs text-muted-foreground">{l.english}</span> : null}
              </span>
              {active ? <Check className="size-4 text-primary!" /> : null}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{title}</p>
      {children}
    </div>
  );
}

/** Light/dark/system, accent colour and text size, saved in this browser. */
export function AppearanceMenu() {
  const { theme, setTheme } = useTheme();
  const accent = useUiStore((s) => s.accent);
  const fontSize = useUiStore((s) => s.fontSize);
  const setAccent = useUiStore((s) => s.setAccent);
  const setFontSize = useUiStore((s) => s.setFontSize);
  const t = useT();
  // next-themes only knows the theme in the browser; render a neutral state during server rendering.
  const mounted = useSyncExternalStore(subscribeNothing, () => true, () => false);
  const currentTheme = mounted ? (theme ?? "system") : null;
  const swatch = ACCENTS.find((a) => a.id === accent)?.swatch;
  const isDefault = accent === DEFAULT_ACCENT && fontSize === DEFAULT_FONT_SIZE && currentTheme === "system";

  const themes = [
    { id: "light", label: t("Light"), icon: Sun },
    { id: "dark", label: t("Dark"), icon: Moon },
    { id: "system", label: t("System"), icon: Monitor },
  ];

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className={cn(pill, "relative w-8 px-0")} aria-label={t("Appearance")}>
          <Palette className="size-4" />
          <span className="absolute right-1 bottom-1 size-2 rounded-full ring-2 ring-card" style={{ background: swatch }} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(20rem,calc(100vw-2rem))] space-y-4 p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-semibold">{t("Appearance")}</p>
            <p className="text-xs text-muted-foreground">{t("Saved in this browser")}</p>
          </div>
          <Button variant="ghost" size="xs" disabled={isDefault} onClick={() => { setTheme("system"); setAccent(DEFAULT_ACCENT); setFontSize(DEFAULT_FONT_SIZE); }}>
            <RotateCcw />{t("Reset")}
          </Button>
        </div>

        <Section title={t("Theme")}>
          <div role="radiogroup" aria-label={t("Theme")} className="grid grid-cols-3 gap-2">
            {themes.map(({ id, label, icon: Icon }) => {
              const active = currentTheme === id;
              return (
                <button key={id} type="button" role="radio" aria-checked={active} onClick={() => setTheme(id)}
                  className={cn("flex flex-col items-center gap-1.5 rounded-lg border p-2.5 text-xs font-medium transition-colors hover:bg-muted", active ? "border-primary bg-accent text-accent-foreground ring-1 ring-primary" : "text-muted-foreground")}>
                  <Icon className="size-4.5" />
                  {label}
                </button>
              );
            })}
          </div>
        </Section>

        <Section title={t("Accent colour")}>
          <div role="radiogroup" aria-label={t("Accent colour")} className="flex flex-wrap gap-2.5">
            {ACCENTS.map((a) => {
              const active = a.id === accent;
              return (
                <button key={a.id} type="button" role="radio" aria-checked={active} aria-label={t(a.label)} title={t(a.label)} onClick={() => setAccent(a.id)}
                  className={cn("grid size-8 place-items-center rounded-full text-white shadow-sm transition-transform hover:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2",
                    active && "ring-2 ring-foreground/70 ring-offset-2 ring-offset-popover")}
                  style={{ background: a.swatch }}>
                  {active ? <Check className="size-4" strokeWidth={3} /> : null}
                </button>
              );
            })}
          </div>
        </Section>

        <Section title={t("Text size")}>
          <div role="radiogroup" aria-label={t("Text size")} className="grid grid-cols-4 gap-1 rounded-lg bg-muted p-1">
            {FONT_SIZES.map((f, i) => {
              const active = f.id === fontSize;
              return (
                <button key={f.id} type="button" role="radio" aria-checked={active} aria-label={t(f.label)} title={t(f.label)} onClick={() => setFontSize(f.id)}
                  className={cn("flex h-10 items-end justify-center rounded-md pb-1.5 font-semibold transition-colors", active ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                  <span style={{ fontSize: `${12 + i * 3}px`, lineHeight: 1 }}>A</span>
                </button>
              );
            })}
          </div>
          <p className="text-center text-xs text-muted-foreground">{t(FONT_SIZES.find((f) => f.id === fontSize)?.label ?? "Default")}</p>
        </Section>
      </PopoverContent>
    </Popover>
  );
}

function initialsOf(name: string | undefined) {
  return (name ?? "").split(" ").filter(Boolean).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
}

export function UserMenu() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const router = useRouter();
  const { confirm } = useDialogs();
  const t = useT();
  const initials = initialsOf(user?.fullName);
  const role = user?.roles[0]?.name;

  const resetDemo = async () => {
    const ok = await confirm({ title: "Reset demo data?", description: "All records in this browser return to the original sample data. This cannot be undone.", confirmLabel: "Reset data", destructive: true });
    if (!ok) return;
    const { resetMockData } = await import("@/mock-server/router");
    resetMockData();
    await logout().catch(() => undefined);
    window.location.replace(new URL("/login", window.location.origin));
  };

  const avatar = (size: string, text: string) => (
    <span className="relative shrink-0">
      <Avatar className={size}>
        <AvatarFallback className={cn("bg-gradient-to-br from-primary to-primary/60 font-semibold text-primary-foreground", text)}>{initials}</AvatarFallback>
      </Avatar>
      <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full bg-success ring-2 ring-card" aria-hidden />
    </span>
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label={`${t("Account menu")}: ${user?.fullName ?? ""}`}
          className="flex h-9 shrink-0 items-center gap-2 rounded-full border bg-card p-0.5 shadow-xs transition-colors hover:bg-muted data-[state=open]:bg-muted sm:pr-2">
          {avatar("size-8", "text-xs")}
          <span className="hidden min-w-0 text-left leading-tight xl:block">
            <span className="block max-w-32 truncate text-sm font-medium">{user?.fullName}</span>
            <span className="block max-w-32 truncate text-[11px] text-muted-foreground">{role}</span>
          </span>
          <ChevronDown className="hidden size-3.5 text-muted-foreground sm:block" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72 overflow-hidden p-0">
        <div className="relative bg-gradient-to-br from-primary/15 via-accent/60 to-transparent px-4 pt-4 pb-3">
          <div className="flex items-center gap-3">
            {avatar("size-12", "text-base")}
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{user?.fullName}</p>
              <p className="truncate text-xs text-muted-foreground">@{user?.username}{user?.email ? ` · ${user.email}` : ""}</p>
            </div>
          </div>
          {user?.roles.length ? (
            <div className="mt-3 flex flex-wrap gap-1">
              {user.roles.map((r) => (
                <span key={r.id} className="inline-flex items-center gap-1 rounded-full border border-primary/25 bg-card/80 px-2 py-0.5 text-[11px] font-medium text-foreground">
                  <ShieldCheck className="size-3 text-primary" />{r.name}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <DropdownMenuSeparator className="my-0" />
        <DropdownMenuGroup className="p-1.5">
          <DropdownMenuItem className="gap-2.5 py-2" onSelect={() => router.push("/profile")}><UserRound />{t("My profile")}</DropdownMenuItem>
          <DropdownMenuItem className="gap-2.5 py-2" onSelect={() => router.push("/notifications")}><Bell />{t("Notifications")}</DropdownMenuItem>
          {isMockMode ? <DropdownMenuItem className="gap-2.5 py-2" onSelect={() => void resetDemo()}><Database />Reset demo data</DropdownMenuItem> : null}
        </DropdownMenuGroup>
        <DropdownMenuSeparator className="my-0" />
        <div className="p-1.5">
          <DropdownMenuItem variant="destructive" className="gap-2.5 py-2" onSelect={() => void logout().then(() => router.replace("/login"))}><LogOut />{t("Sign out")}</DropdownMenuItem>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
