import { type Page, expect, test } from "@playwright/test";

import { signUp, signUpVerified, uniqueEmail } from "./helpers";

// The unfixed header shifted 0.17-0.35; 0.05 leaves room for incidental sub-pixel shifts.
/** Sum of layout shifts (no recent input) over a page load, Chromium only. */
async function observeShifts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __cls: number };
    w.__cls = 0;
    new PerformanceObserver((list) => {
      for (const e of list.getEntries() as unknown as { value: number; hadRecentInput: boolean }[])
        if (!e.hadRecentInput) w.__cls += e.value;
    }).observe({ type: "layout-shift", buffered: true });
  });
}

const cls = (page: Page) => page.evaluate(() => (window as unknown as { __cls: number }).__cls);

/** Hold the session refresh so the header changes state well after first paint. */
async function slowRefresh(page: Page): Promise<void> {
  await page.route("**/auth/refresh", async (route) => {
    await new Promise((r) => setTimeout(r, 1200));
    await route.continue();
  });
}

// 320 is the smallest supported width, 360 the most common Android phone, 412 a large one.
const WIDTHS = [320, 360, 412];

test.describe("header does not shift when the session resolves (CLS)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "layout-shift API is Chromium-only");

  for (const width of WIDTHS) {
    test.describe(`${width}px`, () => {
      test.use({ viewport: { width, height: 823 } });

      test("signed out", async ({ page }) => {
        await observeShifts(page);
        await slowRefresh(page);
        await page.goto("/login");
        await expect(page.getByRole("link", { name: "Sign up" })).toBeVisible();
        expect(await cls(page)).toBeLessThan(0.05);
      });

      test("signed in, after a reload", async ({ page }) => {
        // Verified, so no late notice is involved; the unverified case is the next test.
        await signUpVerified(page, "cls");
        await observeShifts(page);
        await slowRefresh(page);
        await page.goto("/dashboard");
        await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
        expect(await cls(page)).toBeLessThan(0.05);
      });

      test("signed in but unverified (the verify-email notice appears late)", async ({ page }) => {
        await signUp(page, uniqueEmail("cls-unverified"));
        await observeShifts(page);
        await slowRefresh(page);
        await page.goto("/dashboard");
        await expect(page.getByText(/verify your email address \(/i)).toBeVisible();
        expect(await cls(page)).toBeLessThan(0.05);
      });
    });
  }
});
