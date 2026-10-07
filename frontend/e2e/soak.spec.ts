import { expect, test } from "@playwright/test";

import { createVoice, signUpVerified } from "./helpers";

const RUNS = 50;
const GENERATION_ID = "0b6f6c1e-7f0a-4c8e-9a52-3d1f2e4a5b6c";

/** A short, valid mono 16-bit PCM WAV (0.2 s of silence). */
function tinyWav(): Buffer {
  const rate = 8000;
  const data = Buffer.alloc(rate * 0.2 * 2);
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write("WAVEfmt ", 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}

// Definition of Done 13: object URLs are released over a long session (no leak in a
// 50-generation soak). Synthesis is stubbed so 50 runs take seconds, not minutes; the voice
// profile and the session are real.
test(`${RUNS} generations leave at most one live audio blob URL and one player`, async ({
  page,
}) => {
  test.setTimeout(300_000);
  await page.addInitScript(() => {
    const live = new Set<string>();
    const w = window as unknown as { __live: Set<string>; __created: number };
    w.__live = live;
    w.__created = 0;
    const create = URL.createObjectURL.bind(URL);
    const revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (obj: Blob | MediaSource) => {
      const url = create(obj);
      live.add(url);
      w.__created += 1;
      return url;
    };
    URL.revokeObjectURL = (url: string) => {
      live.delete(url);
      revoke(url);
    };
  });

  await signUpVerified(page, "soak");
  await createVoice(page, "Soak voice");

  const wav = tinyWav();
  let synthRequests = 0;
  await page.route("**/synthesize", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    synthRequests += 1;
    await route.fulfill({
      status: 200,
      contentType: "audio/wav",
      body: wav,
      headers: {
        "content-disposition": `attachment; filename="synthesized_${GENERATION_ID}.wav"`,
        "access-control-allow-origin": "http://localhost:3000",
        "access-control-allow-credentials": "true",
        "access-control-expose-headers": "Content-Disposition",
      },
    });
  });

  await page.goto("/dashboard");
  await expect(page.getByLabel("Voice")).toBeEnabled();
  await page.getByLabel("Voice").selectOption({ label: "Soak voice" });
  await page.getByLabel("Text").fill("Soak test.");

  const state = () =>
    page.evaluate(() => ({
      live: (window as unknown as { __live: Set<string> }).__live.size,
      created: (window as unknown as { __created: number }).__created,
      players: document.querySelectorAll("audio").length,
    }));

  const generate = page.getByRole("button", { name: "Generate speech" });
  for (let i = 1; i <= RUNS; i += 1) {
    await generate.click();
    await expect.poll(() => synthRequests).toBe(i);
    await expect(page.getByLabel("Generated speech")).toBeVisible();
    await expect(generate).toBeEnabled();
    const s = await state();
    expect(s.live, `live blob URLs after run ${i}`).toBeLessThanOrEqual(1);
    expect(s.players, `audio elements after run ${i}`).toBe(1);
  }

  const end = await state();
  expect(end.created).toBeGreaterThanOrEqual(RUNS);
  expect(end.live).toBe(1);

  // Leaving the page releases the last one.
  await page.getByRole("link", { name: "Account" }).click();
  await expect(page).toHaveURL(/\/profile/);
  expect((await state()).live).toBe(0);
});
