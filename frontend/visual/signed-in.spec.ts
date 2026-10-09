import { expect, test } from "@playwright/test";

const WIDTHS = [375, 768, 1280] as const;
const THEMES = ["light", "dark"] as const;
const ROUTES = ["generate", "voices", "history", "account"] as const;

import { ORIGIN, mockApi } from "./mock-api";

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    for (const route of ROUTES) {
      const states = route === "generate" ? [false, true] : [false];
      for (const firstRun of states) {
        const name = `${route}${firstRun ? "-first-run" : ""}-${width}-${theme}`;
        test(name, async ({ page, context }) => {
          await mockApi(page, firstRun);
          await context.addCookies([{ name: "cv-theme", value: theme, url: ORIGIN }]);
          await page.setViewportSize({ width, height: 800 });
          await page.goto(`/${route}`);
          await page.waitForLoadState("networkidle");
          await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
          await expect(page).toHaveScreenshot(`${name}.png`, { fullPage: true });
        });
      }
    }
  }
}
