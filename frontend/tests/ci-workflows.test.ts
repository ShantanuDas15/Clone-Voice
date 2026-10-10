import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const read = (name: string) =>
  readFileSync(path.resolve(__dirname, "../../.github/workflows", name), "utf8");

/** The text of one top-level job in a workflow file. */
function job(yaml: string, name: string): string {
  const start = yaml.indexOf(`\n  ${name}:`);
  if (start < 0) throw new Error(`no job ${name}`);
  const rest = yaml.slice(start + 1);
  const next = rest.slice(1).search(/\n  [a-z-]+:\n/);
  return next < 0 ? rest : rest.slice(0, next + 1);
}
const field = (text: string, key: string) => new RegExp(`${key}:\\s*(\\S+)`).exec(text)?.[1];

describe("visual baselines workflow (UX plan §12 M4)", () => {
  const visual = job(read("frontend.yml"), "visual");
  const update = read("visual-update.yml");

  it("uses the same pinned runner and Node version as the job it feeds", () => {
    expect(field(visual, "runs-on")).toMatch(/^ubuntu-\d+\.\d+$/);
    expect(field(update, "runs-on")).toBe(field(visual, "runs-on"));
    expect(field(update, "node-version")).toBe(field(visual, "node-version"));
  });

  it("installs the same browser and runs the same command", () => {
    for (const text of [visual, update]) {
      expect(text).toContain("npx playwright install --with-deps chromium");
      expect(text).toContain("npm run test:visual");
    }
  });

  it("is manual only, read-only, and never commits or pushes", () => {
    expect(update).toMatch(/on:\s*\n\s+workflow_dispatch:/);
    expect(update).not.toMatch(/\n\s+(push|pull_request|schedule):/);
    expect(update).toContain("contents: read");
    expect(update).not.toMatch(/contents:\s*write|git (add|commit|push)|GITHUB_TOKEN/);
  });

  it("starts from empty, verifies the result is stable, and uploads it", () => {
    expect(update.indexOf("rm -f visual/__screenshots__")).toBeLessThan(
      update.indexOf("--update-snapshots"),
    );
    expect(update.indexOf("--update-snapshots")).toBeLessThan(
      update.lastIndexOf("npm run test:visual"),
    );
    expect(update).toContain("actions/upload-artifact@v4");
    expect(update).toContain("path: frontend/visual/__screenshots__");
    expect(update).toContain("if-no-files-found: error");
  });
});

describe("unit-test job Node version (FE-UX42)", () => {
  it("runs the unit tests on Node 24 or newer, where jsdom multipart uploads complete", () => {
    const check = job(read("frontend.yml"), "check");
    const major = Number(/node-version:\s*(\d+)/.exec(check)?.[1]);
    expect(major).toBeGreaterThanOrEqual(24);
    expect(readFileSync(path.resolve(__dirname, "../.nvmrc"), "utf8").trim()).toBe(String(major));
  });
});

describe("required checks are reliable (FE-UX45, FE-UX46)", () => {
  const head = read("frontend.yml").split("\njobs:")[0] ?? "";

  it("has no path filter, so a docs-only or backend-only PR still gets check, perf and visual", () => {
    expect(head).toMatch(/\n\s+pull_request:/);
    expect(head).not.toMatch(/^\s*paths(-ignore)?:/m);
  });

  it("pushes only on main, so a PR branch does not run every required check twice", () => {
    expect(head).toMatch(/\n\s+push:\s*\n\s+branches:\s*\[main\]/);
  });

  it("re-measures a route that misses before failing it, and never masks the result", () => {
    const perf = job(read("frontend.yml"), "perf");
    expect(Number(/PERF_ATTEMPTS:\s*(\d+)/.exec(perf)?.[1])).toBeGreaterThanOrEqual(2);
    expect(perf).not.toMatch(/continue-on-error|\|\| true/);
    const runner = readFileSync(path.resolve(__dirname, "../perf/run.mjs"), "utf8");
    expect(runner).toContain("judgeAttempts");
  });
});
