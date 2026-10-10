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
  /**
   * Plan proposal: LCP < 2.5 s on 4G (Lighthouse's default mobile profile is slow 4G + 4x CPU),
   * measured with real throttling (perf/run.mjs), where it is deterministic (about 1.4 s today).
   */
  lcpMs: number;
  /**
   * Drift guard, stricter than the contract above. With real throttling LCP is deterministic:
   * 1.41-1.44 s locally and 1.44-1.46 s on the CI runner (FE-UX48), so 1.8 s means something added
   * about a third of a second to the critical path, long before 2.5 s. Raise it deliberately, with
   * a reason, never to make a run pass.
   */
  lcpDriftMs: number;
  /** Plan proposal: JS < 200 KB gzipped on public routes (transfer size, compressed by the server). */
  scriptKb: number;
  /** Core Web Vitals "good" thresholds, added to the plan's two. */
  cls: number;
  tbtMs: number;
}

export const BUDGET: Budget = {
  lcpMs: 2500,
  lcpDriftMs: 1800,
  scriptKb: 200,
  cls: 0.1,
  tbtMs: 300,
};

/** Public routes that must meet the budget (no sign-in needed). */
export const PUBLIC_ROUTES = ["/", "/login", "/signup", "/forgot-password", "/terms"] as const;

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
  if (metrics.lcpMs > budget.lcpDriftMs && metrics.lcpMs <= budget.lcpMs) {
    out.push(
      `LCP ${Math.round(metrics.lcpMs)} ms > ${budget.lcpDriftMs} ms drift guard (baseline about 1450 ms)`,
    );
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

/**
 * Judge one route measured in several attempts: it passes if ANY attempt is within budget, and is
 * reported by the first passing attempt (or the last one when none passes). Shared-runner noise
 * hits one attempt at a time (+0.6 s on a single route, then gone), while a real regression is
 * over budget in every attempt, so this removes flakes without hiding regressions.
 */
export function judgeAttempts(
  attempts: readonly Metrics[],
  budget: Budget = BUDGET,
): { metrics: Metrics; violations: string[]; attemptsUsed: number } {
  if (attempts.length === 0) throw new Error("No attempts to judge");
  for (let i = 0; i < attempts.length; i += 1) {
    const metrics = attempts[i] as Metrics;
    if (violations(metrics, budget).length === 0) {
      return { metrics, violations: [], attemptsUsed: i + 1 };
    }
  }
  const metrics = attempts[attempts.length - 1] as Metrics;
  return { metrics, violations: violations(metrics, budget), attemptsUsed: attempts.length };
}
