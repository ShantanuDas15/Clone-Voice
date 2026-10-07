import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { STYLE_HASHES, buildCsp, cspHeaderName, generateNonce } from "@/lib/csp";

const opts = { nonce: "abc123", apiOrigin: "https://api.example.com" };

describe("buildCsp", () => {
  const csp = buildCsp(opts);
  const directive = (name: string) =>
    csp
      .split("; ")
      .find((d) => d.startsWith(`${name} `))
      ?.slice(name.length + 1)
      .split(" ");

  it("gates scripts by nonce with no unsafe-inline or unsafe-eval", () => {
    expect(directive("script-src")).toEqual(["'self'", "'nonce-abc123'", "'strict-dynamic'"]);
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
  });

  it("allows eval only in development", () => {
    expect(buildCsp({ ...opts, development: true })).toContain("'unsafe-eval'");
  });

  it("limits connections to self and the API origin", () => {
    expect(directive("connect-src")).toEqual(["'self'", "https://api.example.com"]);
  });

  it("allows blob media for playback and forbids framing, plugins and foreign bases", () => {
    expect(directive("media-src")).toEqual(["'self'", "blob:"]);
    expect(directive("frame-ancestors")).toEqual(["'none'"]);
    expect(directive("object-src")).toEqual(["'none'"]);
    expect(directive("base-uri")).toEqual(["'self'"]);
    expect(directive("default-src")).toEqual(["'self'"]);
  });
});

describe("csp helpers", () => {
  it("is report-only until enforcement is switched on", () => {
    expect(cspHeaderName(false)).toBe("Content-Security-Policy-Report-Only");
    expect(cspHeaderName(true)).toBe("Content-Security-Policy");
  });

  it("generates a fresh base64 nonce each time", () => {
    const a = generateNonce();
    expect(a).toMatch(/^[A-Za-z0-9+/=]+$/);
    expect(generateNonce()).not.toBe(a);
  });
});

describe("style hashes", () => {
  const sha = (text: string) => `'sha256-${createHash("sha256").update(text).digest("base64")}'`;

  it("allow exactly the installed sonner's injected stylesheet and its empty element", () => {
    const bundle = readFileSync(
      path.resolve(__dirname, "../node_modules/sonner/dist/index.mjs"),
      "utf8",
    );
    const literal = /__insertCSS\("((?:[^"\\]|\\.)*)"\)/.exec(bundle)?.[1];
    expect(literal).toBeTruthy();
    const css = JSON.parse(`"${literal}"`) as string;
    expect(STYLE_HASHES).toContain(sha(css));
    expect(STYLE_HASHES).toContain(sha(""));
  });

  it("keeps scripts free of hashes and unsafe keywords", () => {
    expect(buildCsp(opts)).toMatch(/style-src [^;]*'sha256-/);
    expect(buildCsp(opts)).not.toMatch(/script-src [^;]*sha256/);
  });
});

describe("reporting origin", () => {
  it("is allowed in connect-src only when reporting is configured", () => {
    const without = buildCsp(opts);
    const withIt = buildCsp({ ...opts, reportingOrigin: "https://o1.ingest.sentry.io" });
    expect(without).not.toContain("sentry");
    expect(withIt).toContain(
      "connect-src 'self' https://api.example.com https://o1.ingest.sentry.io",
    );
  });
});
