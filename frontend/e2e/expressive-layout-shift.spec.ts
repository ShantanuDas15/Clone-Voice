import { expect, test } from "@playwright/test";

import { CLS_WIDTHS, cls, clsWhat, observeShifts } from "../visual/cls";
import { createVoice, signUpVerified } from "./helpers";

/**
 * Pre-release check for an engine that offers delivery controls (FE-UX57). Skipped unless
 * `E2E_EXPRESSIVE=1`, because it needs the backend started as in e2e/README.md "Expressive engine".
 * The Delivery and Strength controls appear when the capabilities answer arrives, a moment after the
 * form, and push the footer down: measured 0.065 to 0.071 at phone widths on the real backend,
 * against 0.008 to 0.014 on SV2TTS. The ceiling is Google's "good" 0.1, so this fails if the
 * late-controls shift gets noticeably worse, not for the known 0.07.
 */
test.skip(
  ({ browserName }) => browserName !== "chromium" || process.env.E2E_EXPRESSIVE !== "1",
  "Chromium only, and only with E2E_EXPRESSIVE=1 on an expressive-engine backend",
);

for (const width of CLS_WIDTHS) {
  test(`signed-in generate page, delivery controls arriving late @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 823 });
    await signUpVerified(page, "expressive");
    await createVoice(page, "Expressive voice");
    await observeShifts(page);
    await page.route("**/auth/refresh", async (route) => {
      await new Promise((r) => setTimeout(r, 1200));
      await route.continue();
    });
    await page.goto("/generate");
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    // Proves the backend is configured as intended: the controls are only there if it says so.
    await expect(page.getByLabel("Delivery", { exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    expect(await cls(page), await clsWhat(page)).toBeLessThan(0.1);
  });
}
