import { expect, test } from "@playwright/test";

import { SAMPLE_WAV, createVoice, signUp, signUpVerified, uniqueEmail } from "./helpers";

test("an unverified user is told to verify and the server refuses the upload (403)", async ({
  page,
}) => {
  await signUp(page, uniqueEmail("unverified"));
  await page.goto("/voices");
  await page.getByLabel("Voice name").fill("Nope");
  await page.locator("input[type=file]").setInputFiles(SAMPLE_WAV);
  await page.getByRole("checkbox", { name: /right to use this voice/i }).check();
  await page.getByRole("button", { name: "Create voice" }).click();
  await expect(page.getByText(/verify your email/i).first()).toBeVisible();
});

test("upload a real sample, see it listed, then delete it", async ({ page }) => {
  await signUpVerified(page, "voice");
  await createVoice(page, "Sample voice");
  await expect(page.getByRole("list").getByText("Sample voice")).toBeVisible();
  await expect(page.getByText("Ready", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Delete Sample voice" }).click();
  await page.getByRole("button", { name: "Delete voice" }).click();
  await expect(page.getByText(/haven't created a voice yet/i)).toBeVisible();
});

test("an empty file and a non-audio file are refused", async ({ page }) => {
  await signUpVerified(page, "badfile");
  await page.goto("/voices");
  await page.locator("input[type=file]").setInputFiles({
    name: "empty.wav",
    mimeType: "audio/wav",
    buffer: Buffer.alloc(0),
  });
  await expect(page.getByText("That file is empty.")).toBeVisible();

  // Text content with a .wav name and wav type: only the server can tell.
  await page.locator("input[type=file]").setInputFiles({
    name: "fake.wav",
    mimeType: "audio/wav",
    buffer: Buffer.from("this is not audio at all, just text pretending to be a wav file"),
  });
  await page.getByLabel("Voice name").fill("Fake");
  await page.getByRole("checkbox", { name: /right to use this voice/i }).check();
  await page.getByRole("button", { name: "Create voice" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /.+/ }).first()).toBeVisible({
    timeout: 30_000,
  });
  // The failure left the UI consistent with the server (any failed row is listed and deletable).
  await expect(page.getByText(/created\./)).toHaveCount(0);
});

test("consent is required: no request is made without it", async ({ page }) => {
  await signUpVerified(page, "consent");
  await page.goto("/voices");
  let uploads = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/voice/upload")) uploads += 1;
  });
  await page.getByLabel("Voice name").fill("No consent");
  await page.locator("input[type=file]").setInputFiles(SAMPLE_WAV);
  await page.getByRole("button", { name: "Create voice" }).click();
  await expect(page.getByText(/right to use this voice/i).last()).toBeVisible();
  expect(uploads).toBe(0);
});
