import { type Page, expect, test } from "@playwright/test";

import { CLS_WIDTHS, cls, observeShifts } from "../visual/cls";
import { createVoice, signUp, signUpVerified, uniqueEmail } from "./helpers";

/** Hold the session refresh so the header changes state well after first paint. */
async function slowRefresh(page: Page): Promise<void> {
  await page.route("**/auth/refresh", async (route) => {
    await new Promise((r) => setTimeout(r, 1200));
    await route.continue();
  });
}

test.describe("header does not shift when the session resolves (CLS)", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "layout-shift API is Chromium-only");

  for (const width of CLS_WIDTHS) {
    test.describe(`${width}px`, () => {
      test.use({ viewport: { width, height: 823 } });

      test("signed out", async ({ page }) => {
        await observeShifts(page);
        await slowRefresh(page);
        await page.goto("/login");
        await expect(page.getByRole("link", { name: "Create account" })).toBeVisible();
        expect(await cls(page)).toBeLessThan(0.05);
      });

      test("first-run user stays under the 0.2 ceiling", async ({ page }) => {
        // Verified, no voice: the checklist arrives after the form (FE-UX30). Measured 0.04-0.17
        // with a mocked, delayed voice list; this guards against it getting worse.
        await signUpVerified(page, "clsfirst");
        await observeShifts(page);
        await slowRefresh(page);
        await page.goto("/generate");
        await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
        await expect(page.getByRole("list", { name: "First steps" })).toBeVisible();
        expect(await cls(page)).toBeLessThan(0.2);
      });

      test("signed in, after a reload", async ({ page }) => {
        // A returning user: verified with a ready voice, so there is no first-run checklist and no
        // late notice. (A brand-new user's checklist arrives after the voice list and pushes the
        // form down; that is a known trade-off, see FE-UX17 in the engineering plan.)
        await signUpVerified(page, "cls");
        await createVoice(page, "CLS voice");
        await observeShifts(page);
        await slowRefresh(page);
        await page.goto("/generate");
        await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
        expect(await cls(page)).toBeLessThan(0.05);
      });

      test("signed in but unverified (the verify-email notice appears late)", async ({ page }) => {
        await signUp(page, uniqueEmail("cls-unverified"));
        await observeShifts(page);
        await slowRefresh(page);
        await page.goto("/generate");
        await expect(page.getByText(/verify your email address \(/i)).toBeVisible();
        // 0.1 is Google's "good" CLS threshold. At 320 px the footer sits inside the viewport
        // while the session skeleton shows and moves once the page arrives (measured 0.056);
        // the header and the form do not move.
        expect(await cls(page)).toBeLessThan(0.1);
      });
    });
  }
});
