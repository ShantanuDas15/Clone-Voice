import { expect, test } from "@playwright/test";

import { SAMPLE_WAV, createVoice, signUpVerified } from "./helpers";

test("degraded health: banner shows and generate/upload are paused, then recover", async ({
  page,
}) => {
  await signUpVerified(page, "degraded");
  let down = true;
  await page.route("**/health/ready", (route) =>
    down
      ? route.fulfill({ status: 503, json: { status: "degraded" } })
      : route.fulfill({ status: 200, json: { status: "ok" } }),
  );
  await page.goto("/voices");
  await expect(page.getByText(/experiencing problems/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Create voice" })).toBeDisabled();

  down = false;
  await page.goto("/voices"); // a fresh load re-probes
  await expect(page.getByText(/experiencing problems/i)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Create voice" })).toBeEnabled();
});

test("a 503 with Retry-After on the voice list shows an error and Try again recovers", async ({
  page,
}) => {
  await signUpVerified(page, "dbdown");
  let failures = 3; // the first try plus both automatic GET retries (R5)
  await page.route("**/api/v1/voice/profiles", (route) =>
    failures-- > 0
      ? route.fulfill({
          status: 503,
          headers: {
            "Retry-After": "5",
            "access-control-allow-origin": new URL(page.url()).origin,
            "access-control-allow-credentials": "true",
            "access-control-expose-headers": "Retry-After",
          },
          json: { detail: "Database unavailable" },
        })
      : route.continue(),
  );
  await page.goto("/voices");
  await expect(page.getByText(/couldn't load your voices/i)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText(/haven't created a voice yet/i)).toBeVisible();
});

test("a slow network shows skeletons, not a blank page", async ({ page }) => {
  await signUpVerified(page, "slow");
  await page.route("**/api/v1/voice/profiles", async (route) => {
    await new Promise((r) => setTimeout(r, 2500));
    await route.continue();
  });
  await page.goto("/voices");
  await expect(page.getByLabel("Loading voices")).toBeVisible();
  await expect(page.getByText(/haven't created a voice yet/i)).toBeVisible({ timeout: 15_000 });
});

test("a dropped connection during synthesis is not treated as failure and is never retried", async ({
  page,
}) => {
  test.setTimeout(240_000);
  await signUpVerified(page, "dropsynth");
  await createVoice(page, "Drop voice");
  await page.goto("/generate");
  await page.getByLabel("Voice").selectOption({ label: "Drop voice" });
  await page.getByLabel("Text").fill("Hello there.");

  let attempts = 0;
  await page.route("**/api/v1/synthesize", (route) => {
    attempts += 1;
    return route.abort("connectionreset");
  });
  await page.getByRole("button", { name: "Generate speech" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /history/i })).toBeVisible();
  await page.waitForTimeout(3000);
  expect(attempts).toBe(1); // R5: no automatic retry of a non-idempotent POST
  await expect(page.getByRole("button", { name: "Generate speech" })).toBeEnabled();
});

test("going offline during an upload ends in a clear message and a consistent list", async ({
  page,
}) => {
  await signUpVerified(page, "dropupload");
  await page.goto("/voices");
  let attempts = 0;
  await page.route("**/api/v1/voice/upload", (route) => {
    attempts += 1;
    return route.abort("internetdisconnected");
  });
  await page.getByLabel("Voice name").fill("Offline voice");
  await page.locator("input[type=file]").setInputFiles(SAMPLE_WAV);
  await page.getByRole("checkbox", { name: /right to use this voice/i }).check();
  await page.getByRole("button", { name: "Create voice" }).click();
  await expect(page.getByText(/interrupted/i)).toBeVisible();
  await page.waitForTimeout(2000);
  expect(attempts).toBe(1);
  await expect(page.getByText(/haven't created a voice yet/i)).toBeVisible();
});

test("the browser going offline shows a network message on the next action", async ({
  page,
  context,
}) => {
  await signUpVerified(page, "offline");
  await page.goto("/account");
  await expect(page.getByLabel("Display name")).toBeVisible();
  await context.setOffline(true);
  await page.getByLabel("Display name").fill("Offline Name");
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByText(/can't reach the server/i)).toBeVisible();
  await context.setOffline(false);
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByText("Name updated.")).toBeVisible();
});
