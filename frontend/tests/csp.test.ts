import { describe, expect, it } from "vitest";

import { buildCsp, cspHeaderName, generateNonce } from "@/lib/csp";

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
