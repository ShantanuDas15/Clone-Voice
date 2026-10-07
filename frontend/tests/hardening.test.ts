import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = path.resolve(__dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(path.join(ROOT, dir)).flatMap((name) => {
    const rel = path.join(dir, name);
    if (statSync(path.join(ROOT, rel)).isDirectory()) return sources(rel);
    return /\.(ts|tsx)$/.test(name) ? [rel] : [];
  });
}

const APP_FILES = ["app", "components", "hooks", "lib"].flatMap(sources);
const read = (rel: string) => readFileSync(path.join(ROOT, rel), "utf8");

describe("security guardrails (Definition of Done 5, 9)", () => {
  it("never uses dangerouslySetInnerHTML", () => {
    expect(APP_FILES.filter((f) => read(f).includes("dangerouslySetInnerHTML"))).toEqual([]);
  });

  it("never touches browser storage or cookies (the access token is memory-only)", () => {
    const offenders = APP_FILES.filter((f) =>
      /\b(localStorage|sessionStorage|indexedDB|document\.cookie)\b/.test(read(f)),
    );
    expect(offenders).toEqual([]);
  });

  it("only exposes the documented NEXT_PUBLIC_ variables", () => {
    const used = new Set(APP_FILES.flatMap((f) => read(f).match(/NEXT_PUBLIC_[A-Z_]+/g) ?? []));
    expect([...used].sort()).toEqual([
      "NEXT_PUBLIC_API_BASE_URL",
      "NEXT_PUBLIC_APP_ORIGIN",
      "NEXT_PUBLIC_SENTRY_DSN",
    ]);
  });

  it("does not log to the console (no text, audio, emails or tokens in logs, R16)", () => {
    expect(
      APP_FILES.filter((f) => /\bconsole\.(log|info|debug|warn|error)\b/.test(read(f))),
    ).toEqual([]);
  });
});
