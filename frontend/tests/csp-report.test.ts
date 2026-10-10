import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/csp-report/route";
import {
  MAX_BODY_BYTES,
  MAX_REPORTS_PER_REQUEST,
  ReportLimiter,
  clientKey,
  parseCspReports,
} from "@/lib/csp-report";

const legacy = (over: Record<string, unknown> = {}) =>
  JSON.stringify({
    "csp-report": {
      "effective-directive": "script-src-elem",
      "blocked-uri": "https://evil.example/x.js?token=SECRET#frag",
      "document-uri": "https://app.example/verify-email?x=1#token=SECRET",
      disposition: "report",
      ...over,
    },
  });
const modern = (body: Record<string, unknown>) => JSON.stringify([{ type: "csp-violation", body }]);

describe("parseCspReports", () => {
  it("reads the legacy report-uri format and drops query, fragment and credentials", () => {
    const [r] = parseCspReports("application/csp-report", legacy());
    expect(r).toEqual({
      directive: "script-src-elem",
      blocked: "https://evil.example/x.js",
      page: "/verify-email",
      disposition: "report",
    });
    expect(JSON.stringify(r)).not.toMatch(/SECRET|token|frag/);
  });

  it("reads the report-to format", () => {
    const [r] = parseCspReports(
      "application/reports+json; charset=utf-8",
      modern({
        effectiveDirective: "style-src-elem",
        blockedURL: "inline",
        documentURL: "https://app.example/generate",
        disposition: "enforce",
      }),
    );
    expect(r).toEqual({
      directive: "style-src-elem",
      blocked: "inline",
      page: "/generate",
      disposition: "enforce",
    });
  });

  it("drops credentials embedded in a URL", () => {
    const [r] = parseCspReports(
      "application/csp-report",
      legacy({ "blocked-uri": "https://user:pw@evil.example/a" }),
    );
    expect(r?.blocked).toBe("https://evil.example/a");
  });

  it("cannot be used to inject log lines or control characters", () => {
    const hostile = parseCspReports(
      "application/csp-report",
      legacy({
        "effective-directive": 'script-src\n{"event":"fake"}',
        "blocked-uri": 'https://evil.example/a\n{"event":"fake"}‮\u0000',
        "document-uri": "https://app.example/p\r\nmore",
        disposition: "x\ny",
      }),
    );
    const line = JSON.stringify(hostile[0]);
    expect(line).not.toMatch(/[\n\r\u0000‮]/);
    expect(hostile[0]?.directive).toBe("unknown");
    expect(hostile[0]?.disposition).toBe("unknown");
    for (const v of Object.values(hostile[0] ?? {})) expect(String(v)).toMatch(/^[\x20-\x7e]*$/);
  });

  it("caps field length and the number of reports per request", () => {
    const [long] = parseCspReports(
      "application/csp-report",
      legacy({ "blocked-uri": `https://e.example/${"a".repeat(1000)}` }),
    );
    expect(long?.blocked.length).toBeLessThanOrEqual(200);
    const many = JSON.stringify(
      Array.from({ length: 30 }, () => ({
        type: "csp-violation",
        body: { effectiveDirective: "img-src", blockedURL: "data", documentURL: "https://a.b/c" },
      })),
    );
    expect(parseCspReports("application/reports+json", many)).toHaveLength(MAX_REPORTS_PER_REQUEST);
  });

  it.each([
    ["wrong content type", "text/plain", legacy()],
    ["no content type", null, legacy()],
    ["malformed JSON", "application/csp-report", "{not json"],
    ["wrong shape (legacy)", "application/csp-report", '{"other":1}'],
    ["wrong shape (modern)", "application/reports+json", '{"a":1}'],
    ["a non-CSP report", "application/reports+json", '[{"type":"deprecation","body":{}}]'],
    ["an array where an object is expected", "application/csp-report", "[1,2]"],
    ["oversize", "application/csp-report", legacy({ pad: "x".repeat(MAX_BODY_BYTES) })],
  ])("returns nothing for %s", (_n, type, body) => {
    expect(parseCspReports(type, body)).toEqual([]);
  });

  it("marks an unparseable blocked URL instead of passing it through", () => {
    const [r] = parseCspReports("application/csp-report", legacy({ "blocked-uri": "ht!tp://%%" }));
    expect(r?.blocked).toBe("invalid");
  });
});

describe("ReportLimiter", () => {
  it("limits one client, and a rotating client key still hits the global ceiling", () => {
    const l = new ReportLimiter(2, 5, 1000);
    expect([l.allow("a", 0), l.allow("a", 0), l.allow("a", 0)]).toEqual([true, true, false]);
    expect(l.allow("b", 0)).toBe(true);
    expect(l.allow("c", 0)).toBe(true);
    expect(l.allow("d", 0)).toBe(true);
    expect(l.allow("e", 0)).toBe(false); // global 5 spent, even though "e" is new
  });

  it("opens again after the window", () => {
    const l = new ReportLimiter(1, 1, 1000);
    expect(l.allow("a", 0)).toBe(true);
    expect(l.allow("a", 500)).toBe(false);
    expect(l.allow("a", 1000)).toBe(true);
  });

  it("keeps its memory bounded", () => {
    const l = new ReportLimiter(1, 1_000_000, 1000, 10);
    for (let i = 0; i < 100; i += 1) l.allow(`k${i}`, 0);
    expect(
      (l as unknown as { perClient: Map<string, unknown> }).perClient.size,
    ).toBeLessThanOrEqual(10);
  });
});

describe("clientKey", () => {
  it("uses the first forwarded address, printable and short", () => {
    expect(clientKey(new Headers({ "x-forwarded-for": "1.2.3.4, 5.6.7.8" }))).toBe("1.2.3.4");
    expect(clientKey(new Headers())).toBe("unknown");
    expect(clientKey(new Headers({ "x-forwarded-for": "x".repeat(500) })).length).toBe(64);
  });
});

describe("POST /csp-report", () => {
  const lines: string[] = [];
  const write = vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
    lines.push(String(chunk));
    return true;
  });
  afterEach(() => {
    lines.length = 0;
    write.mockClear();
  });
  const post = (body: string, type = "application/csp-report", ip = "9.9.9.9") =>
    POST(
      new Request("http://localhost/csp-report", {
        method: "POST",
        headers: { "content-type": type, "x-forwarded-for": ip },
        body,
      }),
    );

  it("answers 204 and writes one scrubbed JSON line per report", async () => {
    const res = await post(legacy(), "application/csp-report", "10.0.0.1");
    expect(res.status).toBe(204);
    const out = lines.filter((l) => l.includes("csp-violation"));
    expect(out).toHaveLength(1);
    expect(JSON.parse(out[0] as string)).toEqual({
      event: "csp-violation",
      directive: "script-src-elem",
      blocked: "https://evil.example/x.js",
      page: "/verify-email",
      disposition: "report",
    });
    expect(out[0]).not.toMatch(/SECRET/);
  });

  it("answers 204 and logs nothing for junk, oversize bodies and wrong types", async () => {
    for (const [body, type, ip] of [
      ["junk", "application/csp-report", "10.0.0.2"],
      ["x".repeat(MAX_BODY_BYTES + 1), "application/csp-report", "10.0.0.3"],
      [legacy(), "text/plain", "10.0.0.4"],
    ] as const) {
      const res = await post(body, type, ip);
      expect(res.status).toBe(204);
      expect(await res.text()).toBe("");
    }
    expect(lines.filter((l) => l.includes("csp-violation"))).toEqual([]);
  });

  it("does not echo anything back", async () => {
    const res = await post(legacy(), "application/csp-report", "10.0.0.5");
    expect(res.headers.get("content-type")).toBeNull();
  });
});
