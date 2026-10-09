import { expect, test } from "@playwright/test";

import { signUpVerified } from "./helpers";

test("record with a fake microphone, preview, and submit a real WEBM upload", async ({ page }) => {
  await signUpVerified(page, "record");
  await page.goto("/voices");
  await expect(page.getByLabel("Voice name")).toBeVisible();
  test.skip(
    (await page.getByRole("radio", { name: "Record now" }).count()) === 0,
    "this browser records in a format the server does not accept (WebKit); upload is offered instead",
  );
  await page.getByRole("radio", { name: "Record now" }).click();
  await page.getByRole("button", { name: "Start recording" }).click();

  const stop = page.getByRole("button", { name: "Stop recording" });
  await expect(stop).toBeDisabled();
  await expect(stop).toBeEnabled({ timeout: 15_000 }); // after the 5 s minimum
  await stop.click();
  await expect(page.locator('audio[aria-label="Recording preview"]')).toBeAttached();

  const upload = page.waitForRequest((r) => r.url().endsWith("/voice/upload"));
  await page.getByLabel("Voice name").fill("Recorded");
  await page.getByRole("checkbox", { name: /right to use this voice/i }).check();
  await page.getByRole("button", { name: "Create voice" }).click();
  const request = await upload;

  // The server must at least accept the container (magic-byte sniff, Unverified #6). The fake
  // device's tone may legitimately fail speech checks, which would be a 422 about the audio.
  const response = await request.response();
  const text = (await response?.text()) ?? "";
  expect(text).not.toMatch(/does not match its declared audio type|invalid.*signature/i);
  test.info().annotations.push({
    type: "upload result",
    description: `${response?.status()} ${text.slice(0, 160)}`,
  });
});
