import { describe, expect, it } from "vitest";

import {
  BUDGET,
  type LighthouseResult,
  type Metrics,
  PUBLIC_ROUTES,
  extractMetrics,
  judgeAttempts,
  medianMetrics,
  violations,
} from "@/perf/budget.mts";

const lhr = (over: Partial<Record<string, unknown>> = {}): LighthouseResult =>
  ({
    audits: {
      "largest-contentful-paint": { numericValue: 1800 },
      "cumulative-layout-shift": { numericValue: 0.02 },
      "total-blocking-time": { numericValue: 40 },
      "resource-summary": {
        details: {
          items: [
            { resourceType: "total", transferSize: 400 * 1024 },
            { resourceType: "script", transferSize: 150 * 1024 },
          ],
        },
      },
      ...over,
    },
  }) as LighthouseResult;

// Realistic real-throttled values (about 1.45 s on CI), not the simulated-era 2.0 s.
const ok: Metrics = { lcpMs: 1450, scriptKb: 150, cls: 0.01, tbtMs: 50 };

describe("extractMetrics", () => {
  it("reads LCP, CLS, TBT and script transfer (bytes to KB)", () => {
    expect(extractMetrics(lhr())).toEqual({ lcpMs: 1800, scriptKb: 150, cls: 0.02, tbtMs: 40 });
  });

  it("throws, rather than passing silently, when an audit is missing", () => {
    expect(() => extractMetrics(lhr({ "largest-contentful-paint": undefined }))).toThrow(/largest/);
    expect(() => extractMetrics(lhr({ "total-blocking-time": { numericValue: NaN } }))).toThrow(
      /blocking/,
    );
    expect(() => extractMetrics(lhr({ "resource-summary": { details: { items: [] } } }))).toThrow(
      /script/,
    );
  });
});

describe("medianMetrics", () => {
  it("takes the per-metric median, ignoring one outlier run", () => {
    const runs = [
      { ...ok, lcpMs: 1400 },
      { ...ok, lcpMs: 9000 },
      { ...ok, lcpMs: 1500 },
    ];
    expect(medianMetrics(runs).lcpMs).toBe(1500);
  });

  it("averages the middle pair for an even count and handles a single run", () => {
    expect(medianMetrics([ok, { ...ok, scriptKb: 170 }]).scriptKb).toBe(160);
    expect(medianMetrics([ok])).toEqual(ok);
  });

  it("rejects an empty set", () => {
    expect(() => medianMetrics([])).toThrow();
  });
});

describe("violations", () => {
  it("passes metrics inside the budget, and exactly at the limit", () => {
    expect(violations(ok)).toEqual([]);
    expect(
      violations({
        lcpMs: BUDGET.lcpDriftMs,
        scriptKb: BUDGET.scriptKb,
        cls: BUDGET.cls,
        tbtMs: BUDGET.tbtMs,
      }),
    ).toEqual([]);
  });

  it("names each metric that is over", () => {
    const out = violations({ lcpMs: 2600, scriptKb: 201, cls: 0.2, tbtMs: 400 });
    expect(out).toHaveLength(4);
    expect(out.join(" ")).toMatch(/LCP.*JS.*CLS.*TBT/);
  });

  it("reports only the metric that is over", () => {
    expect(violations({ ...ok, scriptKb: 250 })).toEqual(["JS 250.0 KB > 200 KB"]);
  });
});

describe("budget definition", () => {
  it("encodes the plan's proposals and covers / and /login", () => {
    expect(BUDGET.lcpMs).toBe(2500);
    expect(BUDGET.scriptKb).toBe(200);
    expect(PUBLIC_ROUTES).toEqual(expect.arrayContaining(["/", "/login"]));
  });
});

describe("judgeAttempts (a noisy runner must not fail a route, a regression must)", () => {
  const m = (lcpMs: number): Metrics => ({ lcpMs, scriptKb: 170, cls: 0.001, tbtMs: 5 });

  it("passes on the first attempt when it is within budget", () => {
    const r = judgeAttempts([m(1450)]);
    expect(r.violations).toEqual([]);
    expect(r.attemptsUsed).toBe(1);
  });

  it("passes when a later attempt is within budget after a noisy first one", () => {
    const r = judgeAttempts([m(2667), m(1442)]);
    expect(r.violations).toEqual([]);
    expect(r.attemptsUsed).toBe(2);
    expect(r.metrics.lcpMs).toBe(1442);
  });

  it("fails when every attempt is over budget, as a real regression is", () => {
    const r = judgeAttempts([m(2658), m(2621), m(2640)]);
    expect(r.violations.length).toBeGreaterThan(0);
    expect(r.attemptsUsed).toBe(3);
    expect(r.metrics.lcpMs).toBe(2640);
  });

  it("never lets a budget miss on another metric through", () => {
    const heavy: Metrics = { lcpMs: 1500, scriptKb: 260, cls: 0.001, tbtMs: 5 };
    expect(judgeAttempts([heavy, heavy]).violations.join()).toMatch(/JS/);
  });

  it("rejects an empty list instead of passing it", () => {
    expect(() => judgeAttempts([])).toThrow();
  });
});

describe("LCP drift guard (FE-UX49)", () => {
  const base: Metrics = { lcpMs: 1450, scriptKb: 170, cls: 0.001, tbtMs: 5 };

  it("passes the measured baseline with room to spare", () => {
    expect(BUDGET.lcpDriftMs).toBeLessThan(BUDGET.lcpMs);
    expect(violations(base)).toEqual([]);
    expect(violations({ ...base, lcpMs: 1800 })).toEqual([]);
  });

  it("fails a slow-down well before the 2.5 s contract, and names the guard", () => {
    const out = violations({ ...base, lcpMs: 1900 });
    expect(out).toHaveLength(1);
    expect(out[0]).toMatch(/drift guard/);
  });

  it("past the contract it reports the contract, once", () => {
    const out = violations({ ...base, lcpMs: 2600 });
    expect(out).toHaveLength(1);
    expect(out[0]).toMatch(/> 2500 ms/);
  });

  it("is not excused by re-measuring: judgeAttempts keeps failing a consistent drift", () => {
    const slow = { ...base, lcpMs: 1900 };
    expect(judgeAttempts([slow, slow]).violations.length).toBeGreaterThan(0);
  });
});
