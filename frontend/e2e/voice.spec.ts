import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { SAMPLE_WAV, createVoice, signUp, signUpVerified, uniqueEmail } from "./helpers";

test("an unverified user cannot create a voice and is told why", async ({ page }) => {
  await signUp(page, uniqueEmail("unverified"));
  await page.goto("/voices");
  await page.getByLabel("Voice name").fill("Nope");
  await page.locator("input[type=file]").setInputFiles(SAMPLE_WAV);
  await page.getByRole("checkbox", { name: /right to use this voice/i }).check();
  const create = page.getByRole("button", { name: "Create voice" });
  await expect(create).toBeDisabled();
  await expect(page.getByText("Verify your email first.")).toBeVisible();
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

test("two clips become one voice, with the recording advice shown", async ({ page }) => {
  await signUpVerified(page, "twoclips");
  await page.goto("/voices");
  await page.getByLabel("Voice name").fill("Two clips");
  const wav = readFileSync(SAMPLE_WAV);
  await page.locator("input[type=file]").setInputFiles([
    { name: "one.wav", mimeType: "audio/wav", buffer: wav },
    { name: "two.wav", mimeType: "audio/wav", buffer: wav },
  ]);
  await expect(page.getByTestId("selected-file")).toHaveCount(2);
  await page.getByRole("checkbox", { name: /right to use this voice/i }).check();
  await page.getByRole("button", { name: "Create voice" }).click();
  await expect(page.getByText("Voice “Two clips” created.")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole("region", { name: "Recording quality" })).toBeVisible();
});

test("add a clip to a voice, then remove it again", async ({ page }) => {
  await signUpVerified(page, "manageclips");
  await createVoice(page, "Growing voice");
  const row = page.getByRole("listitem").filter({ hasText: "Growing voice" });
  await row.getByText(/^Clips \(/).click();
  await expect(row.getByText("Clip 1")).toBeVisible();
  await expect(row.getByRole("button", { name: /Remove clip/ })).toHaveCount(0); // the only clip

  const form = row.getByRole("form", { name: "Add clips to Growing voice" });
  await form
    .getByLabel("Voice sample")
    .setInputFiles({ name: "more.wav", mimeType: "audio/wav", buffer: readFileSync(SAMPLE_WAV) });
  await form.getByRole("checkbox").check();
  await form.getByRole("button", { name: "Add clips" }).click();
  await expect(row.getByText("Clip 2")).toBeVisible({ timeout: 120_000 });

  await row.getByRole("button", { name: "Remove clip 2 of Growing voice" }).click();
  await expect(row.getByText("Clip 2")).toHaveCount(0);
  await expect(row.getByText("Clip 1")).toBeVisible();
});
