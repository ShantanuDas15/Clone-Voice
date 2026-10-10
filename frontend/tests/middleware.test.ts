import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { config, middleware } from "@/middleware";

describe("middleware", () => {
  it("sets a per-request nonce in the CSP header", () => {
    const first = middleware(new NextRequest("http://localhost:3000/login"));
    const second = middleware(new NextRequest("http://localhost:3000/login"));
    const header = (r: Response) => r.headers.get("content-security-policy-report-only") ?? "";
    expect(header(first)).toContain("connect-src 'self' http://api.test");
    const nonce = (h: string) => /'nonce-([^']+)'/.exec(h)?.[1];
    expect(nonce(header(first))).toBeTruthy();
    expect(nonce(header(first))).not.toBe(nonce(header(second)));
  });

  it("does not wrap the report endpoint itself in the nonce policy", () => {
    const source = String(config.matcher[0]?.source);
    const matches = (path: string) => new RegExp(`^${source}$`).test(path);
    expect(matches("/login")).toBe(true);
    expect(matches("/csp-report")).toBe(false);
  });
});
