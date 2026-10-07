import { describe, expect, it } from "vitest";

import {
  checkCors,
  checkFragmentPageReferrer,
  checkMetricsProtected,
  checkRefreshCookie,
  checkSameSite,
  checkSecurityHeaders,
  exitCode,
  parseSetCookie,
  registrableDomain,
} from "../smoke/lib.mts";

const level = (rs: { name: string; level: string }[], name: string) =>
  rs.find((r) => r.name === name)?.level;

describe("registrableDomain / checkSameSite", () => {
  it("uses the last two labels, or the whole host for localhost and IPs", () => {
    expect(registrableDomain("app.example.com")).toBe("example.com");
    expect(registrableDomain("localhost")).toBe("localhost");
    expect(registrableDomain("127.0.0.1")).toBe("127.0.0.1");
  });

  it("passes app.* and api.* on one domain and localhost on two ports", () => {
    expect(checkSameSite("https://app.example.com", "https://api.example.com").level).toBe("pass");
    expect(checkSameSite("http://localhost:3000", "http://localhost:8000").level).toBe("pass");
  });

  it("fails when the cookie could not be sent (different registrable domains)", () => {
    const r = checkSameSite("https://app.example.com", "https://x.up.railway.app");
    expect(r.level).toBe("fail");
    expect(r.detail).toContain("G-13");
  });
});

describe("checkSecurityHeaders", () => {
  const good = {
    "Content-Security-Policy":
      "default-src 'self'; script-src 'self' 'nonce-x'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
  };

  it("passes an enforcing, nonce-based policy (header names are case-insensitive)", () => {
    const rs = checkSecurityHeaders(good);
    expect(rs.every((r) => r.level === "pass")).toBe(true);
  });

  it("warns, not fails, on report-only (the default until the owner enforces)", () => {
    const rs = checkSecurityHeaders({
      "content-security-policy-report-only": good["Content-Security-Policy"],
      "x-content-type-options": "nosniff",
    });
    expect(level(rs, "CSP header")).toBe("warn");
    expect(exitCode(rs)).toBe(0);
  });

  it("fails on a missing CSP, unsafe-inline, a missing nosniff or no framing protection", () => {
    expect(level(checkSecurityHeaders({}), "CSP header")).toBe("fail");
    const unsafe = checkSecurityHeaders({
      ...good,
      "Content-Security-Policy": "script-src 'unsafe-inline'; frame-ancestors 'none'",
    });
    expect(level(unsafe, "CSP has no unsafe-inline/unsafe-eval")).toBe("fail");
    expect(
      level(
        checkSecurityHeaders({ "content-security-policy": "default-src 'self'" }),
        "X-Content-Type-Options",
      ),
    ).toBe("fail");
    expect(
      level(
        checkSecurityHeaders({ "content-security-policy": "default-src 'self'" }),
        "clickjacking protection",
      ),
    ).toBe("fail");
  });
});

describe("checkFragmentPageReferrer", () => {
  it("requires no-referrer on the emailed-token pages", () => {
    expect(checkFragmentPageReferrer({ "Referrer-Policy": "no-referrer" }).level).toBe("pass");
    expect(checkFragmentPageReferrer({ "referrer-policy": "origin" }).level).toBe("fail");
    expect(checkFragmentPageReferrer({}).level).toBe("fail");
  });
});

describe("checkCors", () => {
  const origin = "https://app.example.com";
  const pre = { "access-control-allow-origin": origin, "access-control-allow-credentials": "true" };
  const sim = { "access-control-expose-headers": "Content-Disposition, X-Request-ID" };

  it("passes a correctly configured API", () => {
    expect(checkCors(pre, sim, origin).every((r) => r.level === "pass")).toBe(true);
  });

  it("fails when the origin is not allowed (ALLOWED_ORIGINS wrong) and says how to fix it", () => {
    const rs = checkCors(
      { ...pre, "access-control-allow-origin": "https://other.example" },
      sim,
      origin,
    );
    expect(rs[0]?.level).toBe("fail");
    expect(rs[0]?.detail).toContain("ALLOWED_ORIGINS");
    expect(checkCors({}, sim, origin)[0]?.detail).toContain("absent");
  });

  it("fails without credentials or without the exposed download header", () => {
    expect(
      level(
        checkCors({ ...pre, "access-control-allow-credentials": "false" }, sim, origin),
        "CORS allows credentials",
      ),
    ).toBe("fail");
    expect(level(checkCors(pre, {}, origin), "CORS exposes Content-Disposition")).toBe("fail");
  });
});

describe("refresh cookie", () => {
  it("parses name and lower-cased attributes", () => {
    expect(parseSetCookie("refresh_token=abc; HttpOnly; Secure; SameSite=Lax; Path=/")).toEqual({
      name: "refresh_token",
      attributes: ["httponly", "secure", "samesite=lax", "path=/"],
    });
  });

  it("passes a hardened https cookie", () => {
    const rs = checkRefreshCookie(["refresh_token=a; HttpOnly; Secure; SameSite=Lax"], true);
    expect(rs.every((r) => r.level === "pass")).toBe(true);
  });

  it("fails a script-readable, non-Lax or (on https) non-Secure cookie, or none at all", () => {
    expect(
      level(
        checkRefreshCookie(["refresh_token=a; SameSite=Lax; Secure"], true),
        "refresh cookie HttpOnly",
      ),
    ).toBe("fail");
    expect(
      level(
        checkRefreshCookie(["refresh_token=a; HttpOnly; Secure; SameSite=None"], true),
        "refresh cookie SameSite=Lax",
      ),
    ).toBe("fail");
    expect(
      level(
        checkRefreshCookie(["refresh_token=a; HttpOnly; SameSite=Lax"], true),
        "refresh cookie Secure",
      ),
    ).toBe("fail");
    expect(level(checkRefreshCookie(["other=1"], true), "refresh cookie is set")).toBe("fail");
  });

  it("does not demand Secure over plain http (local runs)", () => {
    const rs = checkRefreshCookie(["refresh_token=a; HttpOnly; SameSite=Lax"], false);
    expect(level(rs, "refresh cookie Secure")).toBe("warn");
  });
});

describe("metrics and exit code", () => {
  it("warns when /metrics is public, passes otherwise", () => {
    expect(checkMetricsProtected(200).level).toBe("warn");
    expect(checkMetricsProtected(401).level).toBe("pass");
  });

  it("exits 1 on any failure, 0 on warnings only", () => {
    const w = { name: "a", level: "warn" as const, detail: "" };
    const f = { name: "b", level: "fail" as const, detail: "" };
    expect(exitCode([w])).toBe(0);
    expect(exitCode([w, f])).toBe(1);
  });
});
