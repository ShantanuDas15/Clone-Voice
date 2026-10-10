import { expect, test } from "@playwright/test";

const WIDTHS = [375, 768, 1280, 1920] as const;
const THEMES = ["light", "dark"] as const;
const ROUTES = [
  { name: "home", path: "/" },
  { name: "login", path: "/login" },
  { name: "signup", path: "/signup" },
  { name: "forgot-password", path: "/forgot-password" },
  { name: "terms", path: "/terms" },
] as const;

test.beforeEach(async ({ page }) => {
  // Signed out and healthy: refresh says 401, readiness says ok, nothing else is called.
  await page.route("**/health**", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: '{"status":"ok"}' }),
  );
  await page.route("**/api/v1/**", (r) =>
    r.fulfill({
      status: 401,
      contentType: "application/json",
      body: '{"detail":"Not authenticated"}',
    }),
  );
});

for (const theme of THEMES) {
  for (const width of WIDTHS) {
    for (const route of ROUTES) {
      test(`${route.name} @${width} ${theme}`, async ({ page, context }) => {
        await context.addCookies([
          { name: "cv-theme", value: theme, url: "http://localhost:3000" },
        ]);
        await page.setViewportSize({ width, height: 800 });
        await page.goto(route.path);
        await page.waitForLoadState("networkidle");
        await expect(page).toHaveScreenshot(`${route.name}-${width}-${theme}.png`, {
          fullPage: true,
        });
      });
    }
  }
}
