import { type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const AXE_SOURCE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

export interface AxeFinding {
  id: string;
  impact: string;
  targets: string[];
}

/** Run axe-core in the real page (layout, colour contrast, focus) and return serious/critical findings. */
export async function seriousViolations(page: Page): Promise<AxeFinding[]> {
  // The page's CSP would block the injected script; the audit contexts set `bypassCSP`.
  await page.evaluate(AXE_SOURCE);
  return page.evaluate(async () => {
    const axe = (window as unknown as { axe: typeof import("axe-core") }).axe;
    const result = await axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] },
    });
    return result.violations
      .filter((v) => v.impact === "serious" || v.impact === "critical")
      .map((v) => ({
        id: v.id,
        impact: v.impact as string,
        targets: v.nodes.slice(0, 4).map((n) => n.target.join(" ")),
      }));
  });
}
