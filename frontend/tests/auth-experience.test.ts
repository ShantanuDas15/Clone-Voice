import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const read = (rel: string) => readFileSync(path.join(ROOT, rel), "utf8");
const css = read("app/auth-experience.css");

function sources(dir: string): string[] {
  return readdirSync(path.join(ROOT, dir)).flatMap((name) => {
    const rel = path.join(dir, name);
    if (statSync(path.join(ROOT, rel)).isDirectory()) return sources(rel);
    return /\.(ts|tsx|css)$/.test(name) ? [rel] : [];
  });
}

/**
 * The sign-in look is an owner-approved exception to the flat-style and no-loop rules (UX plan §4.10).
 * These tests keep it an exception: scoped to its own file, themed by tokens, still for anyone who
 * asks for reduced motion, and never leaking into the rest of the app.
 */
describe("auth-experience.css, the scoped exception", () => {
  it("is imported only by AuthCard, so no other route loads it", () => {
    const importers = [...sources("app"), ...sources("components"), ...sources("lib")].filter(
      (f) => /\.(ts|tsx)$/.test(f) && /auth-experience\.css/.test(read(f)),
    );
    expect(importers).toEqual([path.join("components", "auth-card.tsx")]);
  });

  it("styles only its own vx- classes (nothing global, no element-only selectors)", () => {
    const selectors = css
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, "")
      .replace(/@media[^{]+\{/g, "")
      .match(/[^{};]+(?=\{)/g)!
      .map((s) => s.trim())
      .filter(Boolean);
    for (const sel of selectors) expect(sel, sel).toMatch(/\.vx-/);
  });

  it("takes its colours from the theme tokens, with no hex values", () => {
    expect(css.replace(/#000\b/g, "")).not.toMatch(/#[0-9a-fA-F]{3,8}\b/); // #000 is only the mask
    expect(css).toContain("hsl(var(--primary)");
  });

  it("switches every animation and transition off under prefers-reduced-motion", () => {
    const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toMatch(/\.vx-aurora i/);
    expect(reduced).toMatch(/\.vx-say::after/);
    expect(reduced).toMatch(/animation: none/);
    expect(reduced).toMatch(/transition: none/);
    // Every looping animation has its keyframes here, and none is faster than the mock's.
    expect(
      [...css.matchAll(/animation:\s*(vx-[\w-]+)\s+([\d.]+)s/g)].every((m) => +m[2]! >= 1),
    ).toBe(true);
  });

  it("keeps its exceptions out of every component (the flat-style test still guards them)", () => {
    for (const f of sources("components")) {
      if (!f.endsWith(".tsx")) continue;
      expect(read(f), f).not.toMatch(/backdrop-blur|bg-gradient|(?:linear|radial)-gradient/);
    }
  });
});
