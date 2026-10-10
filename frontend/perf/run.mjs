/**
 * Lighthouse budget gate: `npm run perf` (needs `npm run build && npx next start -p 3000`).
 * Audits each public route with Lighthouse's default mobile profile (slow 4G, 4x CPU), takes the
 * median of RUNS runs, prints a table and exits 1 if any route breaks the budget.
 */
import { chromium } from "@playwright/test";
import { launch } from "chrome-launcher";
import lighthouse from "lighthouse";

import { BUDGET, PUBLIC_ROUTES, extractMetrics, judgeAttempts, medianMetrics } from "./budget.mts";

const BASE = process.env.PERF_BASE_URL ?? "http://localhost:3000";
const RUNS = Number(process.env.PERF_RUNS ?? 3);
// A route that misses is measured again (up to this many times in all) before it fails: shared-runner
// noise spikes one route for a minute, a real regression misses every time (see judgeAttempts).
const ATTEMPTS = Number(process.env.PERF_ATTEMPTS ?? 1);
// Real (DevTools) throttling, not Lighthouse's simulation. The simulated LCP of the same page on the
// same code jumped between 1.66, 1.81, 2.12, 2.61 and 2.75 s because the simulator decides which
// resources are LCP dependencies from the order they finished in a fast local trace, which is a
// race (first paint stayed at 906-916 ms throughout). With real throttling five routes measured
// 1409-1438 ms over 35 runs. Same profile (slow 4G, 4x CPU) and the same 2.5 s budget (FE-UX48).
const THROTTLING = process.env.PERF_THROTTLING ?? "devtools";
const audit = (route) =>
  lighthouse(`${BASE}${route}`, {
    port: chrome.port,
    output: "json",
    onlyCategories: ["performance"],
    logLevel: "error",
    throttlingMethod: THROTTLING,
  });
const PAUSE_MS = Number(process.env.PERF_PAUSE_MS ?? 20_000);

const chrome = await launch({
  chromePath: process.env.CHROME_PATH ?? chromium.executablePath(),
  chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu"],
});

let failed = false;
try {
  console.log(
    `Budget: LCP ≤ ${BUDGET.lcpMs} ms, JS ≤ ${BUDGET.scriptKb} KB, CLS ≤ ${BUDGET.cls}, TBT ≤ ${BUDGET.tbtMs} ms (median of ${RUNS})`,
  );
  // Warm every route once so the first measurement is not a cold server.
  for (const route of PUBLIC_ROUTES) await fetch(`${BASE}${route}`).then((r) => r.arrayBuffer());
  // Then one full Lighthouse run whose result is thrown away, so the first measured route does not
  // pay for a cold browser.
  await audit(PUBLIC_ROUTES[0]);
  for (const route of PUBLIC_ROUTES) {
    const attempts = [];
    for (let attempt = 0; attempt < ATTEMPTS; attempt += 1) {
      const runs = [];
      for (let i = 0; i < RUNS; i += 1) {
        const result = await audit(route);
        runs.push(extractMetrics(result.lhr));
      }
      attempts.push(medianMetrics(runs));
      if (judgeAttempts(attempts).violations.length === 0 || attempt === ATTEMPTS - 1) break;
      console.log(
        `     ${route.padEnd(16)} missed once (LCP ${Math.round(attempts[attempt].lcpMs)} ms); measuring again`,
      );
      await new Promise((r) => setTimeout(r, PAUSE_MS));
    }
    const { metrics: m, violations: bad, attemptsUsed } = judgeAttempts(attempts);
    failed ||= bad.length > 0;
    console.log(
      `${bad.length ? "FAIL" : "ok  "} ${route.padEnd(16)} LCP ${Math.round(m.lcpMs)} ms · JS ${m.scriptKb.toFixed(1)} KB · CLS ${m.cls.toFixed(3)} · TBT ${Math.round(m.tbtMs)} ms${attemptsUsed > 1 ? ` · attempt ${attemptsUsed}` : ""}${bad.length ? `  → ${bad.join("; ")}` : ""}`,
    );
  }
} finally {
  await chrome.kill();
}
process.exit(failed ? 1 : 0);
