import { expect, test } from "@playwright/test";

import { createVoice, signUpVerified } from "./helpers";

test("generate → play → download → history → replay from history (real weights)", async ({
  page,
}) => {
  test.setTimeout(420_000);
  await signUpVerified(page, "synth");
  await createVoice(page, "Synth voice");

  await page.goto("/generate");
  const select = page.getByLabel("Voice");
  await expect(select).toBeEnabled();
  await select.selectOption({ label: "Synth voice" });
  await page.getByLabel("Text").fill("Hello there.");
  let synthRequests = 0;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/synthesize")) synthRequests += 1;
  });
  await page.getByRole("button", { name: "Generate speech" }).click();

  const player = page.locator('audio[aria-label="Generated speech"]');
  await expect(player).toBeAttached({ timeout: 300_000 }); // the <audio> has no UI of its own
  expect(synthRequests).toBe(1);
  // The Standard engine is the default, so the result card says nothing about engines.
  await expect(
    page.getByRole("region", { name: /your audio/i }).getByText(/voice engine/i),
  ).toHaveCount(0);

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
  await page.goto("/history");
  await expect(page.getByText("Hello there.")).toBeVisible();
  await page.getByRole("button", { name: /^Play:/ }).click();
  const past = page.locator('audio[aria-label^="Generated audio from"]');
  await expect(past).toBeAttached();
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
  await page.goto("/generate");
  await page.getByLabel("Voice").selectOption({ label: "Text voice" });
  await page.getByLabel("Text").fill("Use <b>bold</b> here");
  await page.getByRole("button", { name: "Generate speech" }).click();
  await expect(page.getByText(/unsupported|characters/i).first()).toBeVisible({ timeout: 30_000 });
});

test("delete a generation from History: it is gone after a reload, not just hidden", async ({
  page,
}) => {
  test.setTimeout(420_000);
  await signUpVerified(page, "gendel");
  await createVoice(page, "Delete voice");
  await page.goto("/generate");
  await page.getByLabel("Voice").selectOption({ label: "Delete voice" });
  await page.getByLabel("Text").fill("Remove this one.");
  await page.getByRole("button", { name: "Generate speech" }).click();
  await expect(page.locator('audio[aria-label="Generated speech"]')).toBeAttached({
    timeout: 300_000,
  });

  await page.goto("/history");
  await expect(page.getByText("1 generation.")).toBeVisible();
  await page.getByRole("button", { name: "Delete: Remove this one." }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByText("Delete this audio?")).toBeVisible();
  await dialog.getByRole("button", { name: "Delete audio" }).click();
  await expect(page.getByText(/nothing generated yet/i)).toBeVisible();

  await page.reload(); // the server agrees: no row, no text
  await expect(page.getByText(/nothing generated yet/i)).toBeVisible();
  await expect(page.getByText("Remove this one.")).toHaveCount(0);
});

test("filter History by voice: two voices, each row and count follows the choice", async ({
  page,
}) => {
  test.setTimeout(600_000);
  await signUpVerified(page, "genfilter");
  await createVoice(page, "Filter one");
  await createVoice(page, "Filter two");
  for (const { voice, text } of [
    { voice: "Filter one", text: "Spoken by the first." },
    { voice: "Filter two", text: "Spoken by the second." },
  ]) {
    await page.goto("/generate");
    await page.getByLabel("Voice").selectOption({ label: voice });
    await page.getByLabel("Text").fill(text);
    await page.getByRole("button", { name: "Generate speech" }).click();
    await expect(page.locator('audio[aria-label="Generated speech"]')).toBeAttached({
      timeout: 300_000,
    });
  }

  await page.goto("/history");
  await expect(page.getByText("2 generations.")).toBeVisible();
  const voice = page.getByLabel("Voice");
  await voice.selectOption({ label: "Filter two" });
  await expect(page.getByText("1 generation.")).toBeVisible();
  await expect(page.getByText("Spoken by the second.")).toBeVisible();
  await expect(page.getByText("Spoken by the first.")).toHaveCount(0);

  await voice.selectOption({ label: "All voices" });
  await expect(page.getByText("2 generations.")).toBeVisible();
  await expect(page.getByText("Spoken by the first.")).toBeVisible();
});

test("search History by the text typed: matches, no match, clear, literal wildcard", async ({
  page,
}) => {
  test.setTimeout(600_000);
  await signUpVerified(page, "genfind");
  await createVoice(page, "Find voice");
  for (const text of ["Happy birthday to you.", "The weather is mild."]) {
    await page.goto("/generate");
    await page.getByLabel("Voice").selectOption({ label: "Find voice" });
    await page.getByLabel("Text").fill(text);
    await page.getByRole("button", { name: "Generate speech" }).click();
    await expect(page.locator('audio[aria-label="Generated speech"]')).toBeAttached({
      timeout: 300_000,
    });
  }

  await page.goto("/history");
  await expect(page.getByText("2 generations.")).toBeVisible();
  const search = page.getByLabel("Search your text");
  await search.fill("BIRTHDAY");
  await expect(page.getByText("1 generation found.")).toBeVisible();
  await expect(page.getByText("Happy birthday to you.")).toBeVisible();
  await expect(page.getByText("The weather is mild.")).toHaveCount(0);

  await search.fill("zebra");
  await expect(page.getByText(/match “zebra”/)).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();
  await expect(search).toHaveValue("");
  await expect(page.getByText("2 generations.")).toBeVisible();

  await search.fill("100%"); // a wildcard is a literal, so it matches nothing here
  await expect(page.getByText(/match “100%”/)).toBeVisible();
});
