/**
 * Theme preference: "system" (follow the OS), "light" or "dark". The choice lives in a first-party
 * `cv-theme` cookie rather than browser storage so the server can render `<html data-theme>` on the
 * first byte (no flash, no inline script, which the nonce-based CSP would otherwise need).
 * "system" is represented by the absence of the cookie and of the attribute.
 */
export type Theme = "system" | "light" | "dark";

export const THEME_COOKIE = "cv-theme";
export const THEME_ORDER: readonly Theme[] = ["system", "light", "dark"];

/** Browser-chrome colours (the `paper` token in each theme), used for `<meta name="theme-color">`. */
export const THEME_COLORS = { light: "#F6F4EF", dark: "#121413" } as const;

const ONE_YEAR_S = 60 * 60 * 24 * 365;
const FADE_MS = 250;

/** Coerce an untrusted cookie value to a Theme; anything unknown means "system". */
export function parseTheme(value: string | null | undefined): Theme {
  return value === "light" || value === "dark" ? value : "system";
}

/** The theme a click moves to: system → light → dark → system. */
export function nextTheme(current: Theme): Theme {
  return THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length] ?? "system";
}

/** The `data-theme` attribute value for a theme (undefined = follow the OS). */
export function themeAttribute(theme: Theme): "light" | "dark" | undefined {
  return theme === "system" ? undefined : theme;
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}

/** Keep the mobile browser chrome colour in step with the effective theme. */
export function syncThemeColor(theme: Theme): void {
  const effective = theme === "system" ? (systemPrefersDark() ? "dark" : "light") : theme;
  let meta = document.head.querySelector<HTMLMetaElement>('meta[name="theme-color"][data-cv]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "theme-color";
    meta.setAttribute("data-cv", "");
    document.head.appendChild(meta);
  }
  meta.content = THEME_COLORS[effective];
}

/** Persist the choice and apply it to the document, cross-fading the colours once. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  const attr = themeAttribute(theme);

  if (!prefersReducedMotion()) {
    root.classList.add("theme-transition");
    window.setTimeout(() => root.classList.remove("theme-transition"), FADE_MS);
  }
  if (attr) root.setAttribute("data-theme", attr);
  else root.removeAttribute("data-theme");

  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie =
    theme === "system"
      ? `${THEME_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax${secure}`
      : `${THEME_COOKIE}=${theme}; Path=/; Max-Age=${ONE_YEAR_S}; SameSite=Lax${secure}`;
  syncThemeColor(theme);
}
