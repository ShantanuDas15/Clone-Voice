import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_COOKIE, applyTheme, nextTheme, parseTheme, themeAttribute } from "@/lib/theme";

const ROOT = path.resolve(__dirname, "..");
const read = (rel: string) => readFileSync(path.join(ROOT, rel), "utf8");

function sources(dir: string): string[] {
  return readdirSync(path.join(ROOT, dir)).flatMap((name) => {
    const rel = path.join(dir, name);
    if (statSync(path.join(ROOT, rel)).isDirectory()) return sources(rel);
    return /\.(ts|tsx)$/.test(name) ? [rel] : [];
  });
}

describe("theme helpers", () => {
  it("treats anything but light/dark as system", () => {
    expect(parseTheme("light")).toBe("light");
    expect(parseTheme("dark")).toBe("dark");
    for (const bad of [undefined, null, "", "system", "DARK", "blue", "<script>"]) {
      expect(parseTheme(bad)).toBe("system");
    }
  });

  it("cycles system → light → dark → system", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("system");
  });

  it("emits a data-theme attribute only for an explicit choice", () => {
    expect(themeAttribute("system")).toBeUndefined();
    expect(themeAttribute("light")).toBe("light");
    expect(themeAttribute("dark")).toBe("dark");
  });
});

describe("applyTheme", () => {
  const mm = (reduce: boolean, dark = false) =>
    vi.fn((q: string) => ({
      matches: q.includes("reduced-motion") ? reduce : q.includes("color-scheme") ? dark : false,
      media: q,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("matchMedia", mm(false));
    window.matchMedia = mm(false) as unknown as typeof window.matchMedia;
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.className = "";
    document.head.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.remove());
    document.cookie = `${THEME_COOKIE}=; Max-Age=0; Path=/`;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("sets the attribute and cookie for an explicit theme and clears both for system", () => {
    applyTheme("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.cookie).toContain(`${THEME_COOKIE}=dark`);

    applyTheme("system");
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(document.cookie).not.toContain(THEME_COOKIE);
  });

  it("cross-fades once: adds the transition class, then removes it", () => {
    applyTheme("light");
    expect(document.documentElement.classList.contains("theme-transition")).toBe(true);
    vi.advanceTimersByTime(300);
    expect(document.documentElement.classList.contains("theme-transition")).toBe(false);
  });

  it("switches instantly under prefers-reduced-motion", () => {
    window.matchMedia = mm(true) as unknown as typeof window.matchMedia;
    applyTheme("dark");
    expect(document.documentElement.classList.contains("theme-transition")).toBe(false);
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("keeps the browser-chrome colour in step, including system following the OS", () => {
    applyTheme("dark");
    const meta = () =>
      document.head.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.content;
    expect(meta()).toBe("#121413");
    applyTheme("light");
    expect(meta()).toBe("#F6F4EF");
    window.matchMedia = mm(false, true) as unknown as typeof window.matchMedia;
    applyTheme("system");
    expect(meta()).toBe("#121413");
    expect(document.head.querySelectorAll('meta[name="theme-color"]')).toHaveLength(1);
  });
});

describe("design-token guardrails", () => {
  const FILES = ["app", "components"].flatMap(sources);

  it("uses token utilities, never `dark:` variants (the theme is a data attribute)", () => {
    expect(FILES.filter((f) => /\bdark:[a-z[!-]/.test(read(f)))).toEqual([]);
  });

  it("has no raw palette colours or hex values in components", () => {
    const offenders = FILES.filter((f) =>
      /\b(?:bg|text|border|ring|fill|stroke)-(?:red|green|blue|indigo|violet|purple|pink|slate|gray|zinc|neutral|stone)-\d{2,3}\b|#[0-9a-fA-F]{6}\b/.test(
        read(f),
      ),
    );
    expect(offenders).toEqual([]);
  });

  it("uses only the motion tokens for durations (fast = 120 ms, base = 200 ms)", () => {
    const offenders = FILES.filter((f) => /\bduration-(?:\d|\[)/.test(read(f)));
    expect(offenders).toEqual([]);
    const config = read("tailwind.config.ts");
    expect(config).toContain('fast: "120ms"');
    expect(config).toContain('base: "200ms"');
  });

  it("builds buttons and messages from the ui primitives, not ad-hoc recipes", () => {
    const outside = FILES.filter((f) => !f.includes(path.join("components", "ui")));
    const recipe =
      /bg-primary px-|border border-line px-|border-line bg-surface|text-sm text-danger|"text-danger"/;
    expect(outside.filter((f) => recipe.test(read(f)))).toEqual([]);
  });
});

/** WCAG 2.x contrast computed from the HSL tokens actually shipped in globals.css. */
describe("palette contrast (both themes)", () => {
  const css = read("app/globals.css");

  function block(startMarker: string): Record<string, [number, number, number]> {
    const start = css.indexOf(startMarker);
    const end = css.indexOf("}", start);
    const out: Record<string, [number, number, number]> = {};
    for (const m of css.slice(start, end).matchAll(/--([\w-]+):\s*(\d+)\s+(\d+)%\s+(\d+)%/g)) {
      out[m[1] as string] = [Number(m[2]), Number(m[3]), Number(m[4])];
    }
    return out;
  }
  // Light = :root; dark = the explicit [data-theme="dark"] block (the media block is asserted equal).
  const light = block(":root {");
  const dark = block(':root[data-theme="dark"] {');
  const darkMedia = block(':root:not([data-theme="light"]) {');

  function lum([h, s, l]: [number, number, number]): number {
    const S = s / 100;
    const L = l / 100;
    const a = S * Math.min(L, 1 - L);
    const f = (n: number) => {
      const k = (n + h / 30) % 12;
      return L - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    };
    const lin = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    return 0.2126 * lin(f(0)) + 0.7152 * lin(f(8)) + 0.0722 * lin(f(4));
  }
  const ratio = (a: [number, number, number], b: [number, number, number]) => {
    const [hi = 0, lo = 0] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  const tok = (t: Record<string, [number, number, number]>, k: string) => {
    const v = t[k];
    if (!v) throw new Error(`missing token --${k}`);
    return v;
  };

  it("has a prefers-contrast: more override per theme entry point that reaches 7:1 / 4.5:1", () => {
    const more = {
      light: { ...light, ...block("/* contrast-light */") },
      dark: { ...dark, ...block("/* contrast-dark */") },
      darkOs: { ...darkMedia, ...block("/* contrast-dark-os */") },
    };
    expect(block("/* contrast-dark-os */")).toEqual(block("/* contrast-dark */"));
    for (const [name, t] of Object.entries(more)) {
      for (const bg of ["background", "surface", "muted"] as const) {
        expect(
          ratio(tok(t, "muted-foreground"), tok(t, bg)),
          `${name} text on ${bg}`,
        ).toBeGreaterThanOrEqual(7);
      }
      for (const bg of ["background", "surface"] as const) {
        expect(ratio(tok(t, "line"), tok(t, bg)), `${name} line on ${bg}`).toBeGreaterThanOrEqual(
          4.5,
        );
      }
      expect(
        ratio(tok(t, "border"), tok(t, "background")),
        `${name} border`,
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it("keeps the OS-driven dark block identical to the explicit dark block", () => {
    for (const k of Object.keys(dark)) expect(darkMedia[k], k).toEqual(dark[k]);
  });

  for (const [name, t] of [
    ["light", light],
    ["dark", dark],
  ] as const) {
    it(`${name}: text and accent pairs meet WCAG AA (4.5:1)`, () => {
      for (const [fg, bg] of [
        ["foreground", "background"],
        ["foreground", "surface"],
        ["muted-foreground", "background"],
        ["muted-foreground", "muted"],
        ["primary", "background"],
        ["primary", "surface"],
        ["danger", "surface"],
        ["danger", "background"],
        ["success", "surface"],
        ["success", "muted"], // the success Badge
        ["primary-foreground", "primary"],
        ["danger-foreground", "danger"],
        ["warning-foreground", "warning"],
      ] as const) {
        expect(ratio(tok(t, fg), tok(t, bg)), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
      }
    });

    it(`${name}: control outlines meet 3:1 against their surface (WCAG 1.4.11)`, () => {
      expect(ratio(tok(t, "line"), tok(t, "surface"))).toBeGreaterThanOrEqual(3);
      expect(ratio(tok(t, "line"), tok(t, "background"))).toBeGreaterThanOrEqual(3);
    });
  }
});
