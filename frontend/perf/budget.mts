/**
 * Performance budgets for the public routes (FRONTEND_IMPLEMENTATION_PLAN.md, Phase 7 task 3).
 * Pure functions over a Lighthouse result so the pass/fail logic is unit-tested without a browser.
 */

/** The slice of a Lighthouse result (LHR) the budgets read. */
export interface LighthouseResult {
  audits: Record<string, { numericValue?: number; details?: { items?: unknown[] } } | undefined>;
}

export interface Metrics {
  lcpMs: number;
  scriptKb: number;
  cls: number;
  tbtMs: number;
}

export interface Budget {
  /** Plan proposal: LCP < 2.5 s on 4G (Lighthouse's default mobile profile is slow 4G + 4x CPU). */
  lcpMs: number;
  /** Plan proposal: JS < 200 KB gzipped on public routes (transfer size, compressed by the server). */
  scriptKb: number;
  /** Core Web Vitals "good" thresholds, added to the plan's two. */
  cls: number;
  tbtMs: number;
}

export const BUDGET: Budget = { lcpMs: 2500, scriptKb: 200, cls: 0.1, tbtMs: 300 };

/** Public routes that must meet the budget (no sign-in needed). */
export const PUBLIC_ROUTES = ["/", "/login", "/signup", "/forgot-password"] as const;

function numeric(lhr: LighthouseResult, id: string): number {
  const value = lhr.audits[id]?.numericValue;
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new Error(`Lighthouse result has no numeric "${id}" audit`);
  }
  return value;
}

/** Pull the budgeted metrics out of a Lighthouse result; throws if one is missing. */
export function extractMetrics(lhr: LighthouseResult): Metrics {
  const items = lhr.audits["resource-summary"]?.details?.items as
    { resourceType: string; transferSize: number }[] | undefined;
  const script = items?.find((i) => i.resourceType === "script");
  if (!script || typeof script.transferSize !== "number") {
    throw new Error('Lighthouse result has no "script" row in resource-summary');
  }
  return {
    lcpMs: numeric(lhr, "largest-contentful-paint"),
    scriptKb: script.transferSize / 1024,
    cls: numeric(lhr, "cumulative-layout-shift"),
    tbtMs: numeric(lhr, "total-blocking-time"),
  };
}

/** The per-metric median of several runs, which absorbs Lighthouse's run-to-run variance. */
export function medianMetrics(runs: readonly Metrics[]): Metrics {
  if (runs.length === 0) throw new Error("No runs to aggregate");
  const median = (pick: (m: Metrics) => number): number => {
    const sorted = runs.map(pick).sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
  };
  return {
    lcpMs: median((m) => m.lcpMs),
    scriptKb: median((m) => m.scriptKb),
    cls: median((m) => m.cls),
    tbtMs: median((m) => m.tbtMs),
  };
}

/** Human-readable budget violations (empty when the metrics pass; the limit itself passes). */
export function violations(metrics: Metrics, budget: Budget = BUDGET): string[] {
  const out: string[] = [];
  if (metrics.lcpMs > budget.lcpMs) {
    out.push(`LCP ${Math.round(metrics.lcpMs)} ms > ${budget.lcpMs} ms`);
  }
  if (metrics.scriptKb > budget.scriptKb) {
    out.push(`JS ${metrics.scriptKb.toFixed(1)} KB > ${budget.scriptKb} KB`);
  }
  if (metrics.cls > budget.cls) out.push(`CLS ${metrics.cls.toFixed(3)} > ${budget.cls}`);
  if (metrics.tbtMs > budget.tbtMs) {
    out.push(`TBT ${Math.round(metrics.tbtMs)} ms > ${budget.tbtMs} ms`);
  }
  return out;
}
