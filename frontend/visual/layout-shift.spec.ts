import { expect, test } from "@playwright/test";

import { CLS_WIDTHS, cls, clsWhat, observeShifts } from "./cls";
import { mockApi, mockSignedOut } from "./mock-api";

/**
 * The header and page must not move when the session resolves (UX plan FE-UX17/38). The same four
 * cases and ceilings as `e2e/layout-shift.spec.ts`, but against the mocked API, so they run on every
 * pull request in the required `visual` job (the real-backend version needs model weights and is
 * not in CI). FE-UX52 shipped a header that passed every other check and failed these at 320 and
 * 360 px; the refresh is held for 1.2 s and every other answer for 150 ms so the late states are
 * reproduced the same way each run.
 */
const REFRESH_MS = 1200;
const LATENCY_MS = 50;
// No delivery controls: the real-backend spec runs on SV2TTS, whose form does not grow late.
const opts = { refreshDelayMs: REFRESH_MS, latencyMs: LATENCY_MS, emotionControl: false };

test.describe("header does not shift when the session resolves (CLS, mocked API)", () => {
  for (const width of CLS_WIDTHS) {
    test.describe(`${width}px`, () => {
      test.use({ viewport: { width, height: 823 } });

      test("signed out", async ({ page }) => {
        await observeShifts(page);
        await mockSignedOut(page, REFRESH_MS);
        await page.goto("/login");
        await expect(page.getByRole("link", { name: "Create account" })).toBeVisible();
        await page.waitForLoadState("networkidle");
        expect(await cls(page), await clsWhat(page)).toBeLessThan(0.05);
      });

      test("first-run user (verified, no voice) stays under the 0.2 ceiling", async ({ page }) => {
        // The checklist arrives after the form (FE-UX30); this guards against it getting worse.
        await observeShifts(page);
        await mockApi(page, true, { ...opts, verified: true });
        await page.goto("/generate");
        await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
        await expect(page.getByRole("list", { name: "First steps" })).toBeVisible();
        await page.waitForLoadState("networkidle");
        expect(await cls(page), await clsWhat(page)).toBeLessThan(0.2);
      });

      test("signed in with a voice, after a reload", async ({ page }) => {
        await observeShifts(page);
        await mockApi(page, false, opts);
        await page.goto("/generate");
        await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
        await page.waitForLoadState("networkidle");
        expect(await cls(page), await clsWhat(page)).toBeLessThan(0.05);
      });

      test("signed in but unverified (the verify-email notice appears late)", async ({ page }) => {
        await observeShifts(page);
        await mockApi(page, true, opts);
        await page.goto("/generate");
        await expect(page.getByText(/verify your email address \(/i)).toBeVisible();
        await page.waitForLoadState("networkidle");
        // 0.1 is Google's "good" CLS threshold (see the e2e spec for why it is not lower).
        expect(await cls(page), await clsWhat(page)).toBeLessThan(0.1);
      });
    });
  }
});
