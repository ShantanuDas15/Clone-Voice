import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");
const read = (rel: string) => readFileSync(path.join(ROOT, rel), "utf8");
const css = read("app/account-experience.css");

function sources(dir: string): string[] {
  return readdirSync(path.join(ROOT, dir)).flatMap((name) => {
    const rel = path.join(dir, name);
    if (statSync(path.join(ROOT, rel)).isDirectory()) return sources(rel);
    return /\.(ts|tsx)$/.test(name) ? [rel] : [];
  });
}

/**
 * The Account screen's look is an owner-approved exception to the flat-style and no-loop rules (UX
 * plan §4.10, §12.28). These tests keep it an exception: scoped to one file and one route, themed by
 * tokens, still for anyone who pauses or reduces motion, and never leaking into components.
 */
describe("account-experience.css, the scoped exception", () => {
  it("is imported only by the Account page", () => {
    const importers = [...sources("app"), ...sources("components"), ...sources("lib")].filter((f) =>
      /account-experience\.css/.test(read(f)),
    );
    expect(importers).toEqual([path.join("app", "(app)", "account", "page.tsx")]);
  });

  it("styles only ax- classes", () => {
    const selectors = css
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, "")
      .replace(/@media[^{]+\{/g, "")
      .match(/[^{};]+(?=\{)/g)!
      .map((s) => s.trim())
      .filter(Boolean);
    for (const sel of selectors) {
      expect(/\.ax-/.test(sel), sel).toBe(true);
    }
  });

  it("takes its colours from the theme tokens, with no hex values", () => {
    expect(css.replace(/#000\b/g, "")).not.toMatch(/#[0-9a-fA-F]{3,8}\b/); // #000 is only the mask
    expect(css).toContain("hsl(var(--primary)");
  });

  it("stops the endless animation under Pause motion and under reduced motion", () => {
    expect(css.slice(css.indexOf('[data-motion="paused"]'))).toMatch(
      /animation-play-state: paused/,
    );
    const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reduced).toContain(".ax-aurora i");
    expect(reduced).toMatch(/animation: none/);
    expect(reduced).toMatch(/\.ax-motion\s*\{\s*display: none/); // nothing to pause, so no control
  });

  it("keeps its exceptions out of every component (the flat-style test still guards them)", () => {
    for (const f of [...sources("components"), ...sources("app")]) {
      expect(read(f), f).not.toMatch(/backdrop-blur|bg-gradient|(?:linear|radial)-gradient/);
    }
  });
});
