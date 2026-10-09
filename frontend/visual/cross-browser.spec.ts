import { expect, test } from "@playwright/test";

import { ORIGIN, mockApi, mockSignedOut } from "./mock-api";

/**
 * Structural smoke for the engines whose screenshots we do not baseline (WebKit, Firefox): every
 * route renders its single h1, nothing throws or logs an error, and nothing overflows sideways.
 */
const PUBLIC = ["/", "/login", "/signup", "/forgot-password"];
const SIGNED_IN = ["/generate", "/voices", "/history", "/account"];

for (const width of [375, 1280]) {
  for (const path of [...PUBLIC, ...SIGNED_IN]) {
    test(`${path} @${width}`, async ({ page }) => {
      const problems: string[] = [];
      page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
      page.on("console", (m) => {
        // Expected: the mocked API's 401/404 answers, and WebKit's note that a report-only CSP
        // without `report-to` has no effect (the soak policy sets none; see FE-UX27).
        if (
          m.type() === "error" &&
          !/status of 40[14]|Failed to load resource|delivered in report-only mode/i.test(m.text())
        )
          problems.push(`console: ${m.text()}`);
      });
      if (SIGNED_IN.includes(path)) await mockApi(page, false);
      else await mockSignedOut(page);
      await page.setViewportSize({ width, height: 800 });
      await page.goto(`${ORIGIN}${path}`);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      expect(problems).toEqual([]);
    });
  }
}
