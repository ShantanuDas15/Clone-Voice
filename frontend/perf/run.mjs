/**
 * Lighthouse budget gate: `npm run perf` (needs `npm run build && npx next start -p 3000`).
 * Audits each public route with Lighthouse's default mobile profile (slow 4G, 4x CPU), takes the
 * median of RUNS runs, prints a table and exits 1 if any route breaks the budget.
 */
import { chromium } from "@playwright/test";
import { launch } from "chrome-launcher";
import lighthouse from "lighthouse";

import { BUDGET, PUBLIC_ROUTES, extractMetrics, medianMetrics, violations } from "./budget.mts";

const BASE = process.env.PERF_BASE_URL ?? "http://localhost:3000";
const RUNS = Number(process.env.PERF_RUNS ?? 3);

const chrome = await launch({
  chromePath: process.env.CHROME_PATH ?? chromium.executablePath(),
  chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu"],
});

let failed = false;
try {
  console.log(
    `Budget: LCP ≤ ${BUDGET.lcpMs} ms, JS ≤ ${BUDGET.scriptKb} KB, CLS ≤ ${BUDGET.cls}, TBT ≤ ${BUDGET.tbtMs} ms (median of ${RUNS})`,
  );
  for (const route of PUBLIC_ROUTES) {
    const runs = [];
    for (let i = 0; i < RUNS; i += 1) {
      const result = await lighthouse(`${BASE}${route}`, {
        port: chrome.port,
        output: "json",
        onlyCategories: ["performance"],
        logLevel: "error",
      });
      runs.push(extractMetrics(result.lhr));
    }
    const m = medianMetrics(runs);
    const bad = violations(m);
    failed ||= bad.length > 0;
    console.log(
      `${bad.length ? "FAIL" : "ok  "} ${route.padEnd(16)} LCP ${Math.round(m.lcpMs)} ms · JS ${m.scriptKb.toFixed(1)} KB · CLS ${m.cls.toFixed(3)} · TBT ${Math.round(m.tbtMs)} ms${bad.length ? `  → ${bad.join("; ")}` : ""}`,
    );
  }
} finally {
  await chrome.kill();
}
process.exit(failed ? 1 : 0);
