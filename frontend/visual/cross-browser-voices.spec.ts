import { expect, test } from "@playwright/test";

import { ORIGIN, mockApi } from "./mock-api";

/**
 * The Voices "new voice" stage in the real engines (UX plan §12.23): it shows the chosen clip's own
 * shape (decoded in the browser), moves from analysing to created, draws the voice in, and raises no
 * script or policy errors.
 */
const CORS = {
  "Access-Control-Allow-Origin": ORIGIN,
  "Access-Control-Allow-Credentials": "true",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
  "Access-Control-Expose-Headers": "X-Total-Count",
};

/** A mono 16-bit PCM WAV of a tone whose level rises and falls, `seconds` long. */
function sineWav(seconds: number, rate = 16000): Buffer {
  const n = Math.floor(seconds * rate);
  const buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + n * 2, 4);
  buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(n * 2, 40);
  for (let i = 0; i < n; i++)
    buf.writeInt16LE(
      Math.round(
        Math.sin((2 * Math.PI * 440 * i) / rate) *
          12000 *
          Math.abs(Math.sin((2 * Math.PI * 3 * i) / n)), // a rising and falling level, like speech
      ),
      44 + i * 2,
    );
  return buf;
}

test("the new-voice stage shows the clip's shape, then the created voice", async ({ page }) => {
  test.setTimeout(45_000);
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/status of 40[14]|Failed to load resource/i.test(m.text()))
      problems.push(`console: ${m.text()}`);
  });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await mockApi(page, false);
  await page.route("**/api/v1/voice/upload", async (r) => {
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204, headers: CORS });
    await new Promise((res) => setTimeout(res, 1500));
    return r.fulfill({
      status: 201,
      contentType: "application/json",
      headers: CORS,
      body: JSON.stringify({
        id: "55555555-5555-4555-8555-555555555555",
        name: "Studio narrator",
        status: "ready",
        consent_confirmed_at: "2026-11-04T00:00:00Z",
        terms_version: "1",
        created_at: "2026-11-04T00:00:00Z",
        quality: { rating: "good", hints: [] },
        samples: [{ position: 0, agreement: 1, mismatch: false }],
      }),
    });
  });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/voices`);

  const stage = page.locator("section[data-state]");
  await expect(stage).toHaveAttribute("data-state", "ready");
  const heights = () =>
    page
      .getByTestId("voice-shape")
      .locator("rect")
      .evaluateAll((rs) => new Set(rs.map((r) => r.getAttribute("height"))).size);
  expect(await heights()).toBe(1); // a flat line until a clip is chosen

  await page.getByLabel("Voice name").fill("Studio narrator");
  await page
    .getByRole("form", { name: "Create a voice" })
    .locator('input[type="file"]')
    .setInputFiles({ name: "clip.wav", mimeType: "audio/wav", buffer: sineWav(3) });
  await expect.poll(heights, { timeout: 10_000 }).toBeGreaterThan(2); // the clip's own shape
  await page.getByRole("checkbox", { name: /right to use this voice/ }).check();
  await page.getByRole("checkbox", { name: /speaker is 18 or older/ }).check();
  await page.getByRole("button", { name: "Create voice" }).click();

  await expect(stage).toHaveAttribute("data-state", /uploading|analysing/);
  // Whether the browser reports the bytes as all sent before the answer varies with the mock, so
  // either busy state is fine; the stage must be showing live status, never the ready steps.
  await expect(stage.getByRole("status")).toBeVisible();
  await expect(stage).toHaveAttribute("data-state", "created", { timeout: 15_000 });
  await expect(page.getByText("Voice “Studio narrator” created.")).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Generate speech with “Studio narrator”" }),
  ).toBeVisible();
  // Every bar has taken the accent colour.
  await expect(page.getByTestId("voice-shape").locator("rect.fill-primary")).toHaveCount(64);
  expect(problems).toEqual([]);
});
