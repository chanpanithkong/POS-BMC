/**
 * Per-browser appearance preferences: accent colour and text size (light/dark is next-themes).
 * The values are applied to <html> as data-accent and a root font size, so every rem-based
 * size and every colour token follows. globals.css holds the colour tokens for each accent.
 */

export const ACCENTS = [
  { id: "teal", label: "Teal", swatch: "oklch(0.56 0.1 185)" },
  { id: "blue", label: "Blue", swatch: "oklch(0.56 0.15 255)" },
  { id: "violet", label: "Violet", swatch: "oklch(0.56 0.17 293)" },
  { id: "rose", label: "Rose", swatch: "oklch(0.6 0.18 12)" },
  { id: "orange", label: "Orange", swatch: "oklch(0.66 0.16 52)" },
  { id: "green", label: "Green", swatch: "oklch(0.58 0.13 150)" },
] as const;

export const FONT_SIZES = [
  { id: "sm", label: "Small", scale: "87.5%" },
  { id: "md", label: "Default", scale: "100%" },
  { id: "lg", label: "Large", scale: "112.5%" },
  { id: "xl", label: "Extra large", scale: "125%" },
] as const;

export type Accent = (typeof ACCENTS)[number]["id"];
export type FontSize = (typeof FONT_SIZES)[number]["id"];

export const DEFAULT_ACCENT: Accent = "teal";
export const DEFAULT_FONT_SIZE: FontSize = "md";

export const isAccent = (value: unknown): value is Accent => ACCENTS.some((a) => a.id === value);
export const isFontSize = (value: unknown): value is FontSize => FONT_SIZES.some((f) => f.id === value);

export function applyAppearance(accent: Accent, fontSize: FontSize) {
  const root = document.documentElement;
  if (accent === DEFAULT_ACCENT) delete root.dataset.accent;
  else root.dataset.accent = accent;
  root.style.fontSize = FONT_SIZES.find((f) => f.id === fontSize)?.scale ?? "";
}

/**
 * Runs before the page paints (root layout, beforeInteractive) so a saved colour or text size
 * never flashes the defaults first. It mirrors applyAppearance and reads the persisted UI store.
 */
export const APPEARANCE_BOOT_SCRIPT = `(function(){try{var s=(JSON.parse(localStorage.getItem("pims.ui")||"{}").state)||{};var a=${JSON.stringify(ACCENTS.map((a) => a.id))};var f=${JSON.stringify(Object.fromEntries(FONT_SIZES.map((f) => [f.id, f.scale])))};var r=document.documentElement;if(a.indexOf(s.accent)>0)r.setAttribute("data-accent",s.accent);if(f[s.fontSize])r.style.fontSize=f[s.fontSize];}catch(e){}})();`;
