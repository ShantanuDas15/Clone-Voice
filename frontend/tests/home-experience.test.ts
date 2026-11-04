import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const read = (rel: string) => readFileSync(path.join(ROOT, rel), "utf8");
const css = read("app/home-experience.css");

function sources(dir: string): string[] {
  return readdirSync(path.join(ROOT, dir)).flatMap((name) => {
    const rel = path.join(dir, name);
    if (statSync(path.join(ROOT, rel)).isDirectory()) return sources(rel);
    return /\.(ts|tsx)$/.test(name) ? [rel] : [];
  });
}

/**
 * The home page's look is an owner-approved exception to the flat-style and no-loop rules (UX plan
 * §4.10, §12.25). These tests keep it an exception: scoped to one file and one route, themed by
 * tokens, still for anyone who pauses or reduces motion, and never leaking into components.
 */
describe("home-experience.css, the scoped exception", () => {
  it("is imported only by the home page", () => {
    const importers = [...sources("app"), ...sources("components"), ...sources("lib")].filter((f) =>
      /home-experience\.css/.test(read(f)),
    );
    expect(importers).toEqual([path.join("app", "page.tsx")]);
  });

  it("styles only hx- classes (plus the one body rule that stops sideways scroll)", () => {
    const selectors = css
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, "")
      .replace(/@media[^{]+\{/g, "")
      .match(/[^{};]+(?=\{)/g)!
      .map((s) => s.trim())
      .filter(Boolean);
    for (const sel of selectors) {
      expect(sel === "body:has(.hx-root)" || /\.hx-|\[data-motion/.test(sel), sel).toBe(true);
    }
  });

  it("takes its colours from the theme tokens, with no hex values", () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).toContain("hsl(var(--primary)");
  });

  it("stops every endless animation under Pause motion and under reduced motion", () => {
    const paused = css.slice(css.indexOf('[data-motion="paused"]'));
    expect(paused).toMatch(/animation-play-state: paused/);
    const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    for (const target of [".hx-aurora i", ".hx-word", ".hx-bars.hx-on rect", ".hx-typed::after"]) {
      expect(reduced, target).toContain(target);
    }
    expect(reduced).toMatch(/animation: none/);
    expect(reduced).toMatch(/\.hx-motion\s*\{\s*display: none/); // nothing to pause, so no control
  });

  it("offers the Pause motion control and wires it to the hero", () => {
    const hero = read("components/home-hero.tsx");
    expect(hero).toContain("Pause motion");
    expect(hero).toContain("data-motion");
  });

  it("keeps its exceptions out of every component (the flat-style test still guards them)", () => {
    for (const f of [...sources("components"), ...sources("app")]) {
      expect(read(f), f).not.toMatch(/backdrop-blur|bg-gradient|(?:linear|radial)-gradient/);
    }
  });
});
