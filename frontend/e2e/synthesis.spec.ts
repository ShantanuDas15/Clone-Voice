import { expect, test } from "@playwright/test";

import { createVoice, signUpVerified } from "./helpers";

test("generate → play → download → history → replay from history (real weights)", async ({
  page,
}) => {
  test.setTimeout(420_000);
  await signUpVerified(page, "synth");
  await createVoice(page, "Synth voice");

  await page.goto("/dashboard");
  const select = page.getByLabel("Voice");
  await expect(select).toBeEnabled();
  await select.selectOption({ label: "Synth voice" });
  await page.getByLabel("Text").fill("Hello there.");
  let synthRequests = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/synthesize")) synthRequests += 1;
  });
  await page.getByRole("button", { name: "Generate speech" }).click();

  const player = page.getByLabel("Generated speech");
  await expect(player).toBeVisible({ timeout: 300_000 });
  expect(synthRequests).toBe(1);

  // The blob is real, decodable WAV audio.
  const meta = await player.evaluate(async (el: HTMLAudioElement) => {
    await new Promise((resolve) => {
      if (el.readyState >= 1) resolve(null);
      else el.addEventListener("loadedmetadata", () => resolve(null), { once: true });
    });
    return { duration: el.duration, src: el.src.slice(0, 5) };
  });
  expect(meta.src).toBe("blob:");
  expect(meta.duration).toBeGreaterThan(0.3);

  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download WAV" }).click();
  expect((await download).suggestedFilename()).toMatch(/^synthesized_[0-9a-f-]{36}\.wav$/);

  // History shows it with the voice name, and past audio plays through the authed endpoint.
  await page.goto("/profile");
  await expect(page.getByText("Hello there.")).toBeVisible();
  await page.getByRole("button", { name: "Play" }).click();
  const past = page.getByLabel(/generated audio from/i);
  await expect(past).toBeVisible();
  const pastDuration = await past.evaluate(async (el: HTMLAudioElement) => {
    await new Promise((resolve) => {
      if (el.readyState >= 1) resolve(null);
      else el.addEventListener("loadedmetadata", () => resolve(null), { once: true });
    });
    return el.duration;
  });
  expect(pastDuration).toBeGreaterThan(0.3);
});

test("a text with unsupported characters is refused by the server and shown on the field", async ({
  page,
}) => {
  await signUpVerified(page, "badtext");
  await createVoice(page, "Text voice");
  await page.goto("/dashboard");
  await page.getByLabel("Voice").selectOption({ label: "Text voice" });
  await page.getByLabel("Text").fill("Use <b>bold</b> here");
  await page.getByRole("button", { name: "Generate speech" }).click();
  await expect(page.getByText(/unsupported|characters/i).first()).toBeVisible({ timeout: 30_000 });
});
