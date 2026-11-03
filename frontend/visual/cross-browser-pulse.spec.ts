import { expect, test, type Page } from "@playwright/test";

import { ORIGIN, mockApi } from "./mock-api";

/**
 * The Generate stage in the real engines (UX plan §12.21): it holds its place between states, shows
 * the real status while working, replaces itself with the take, and raises no policy errors.
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

async function mock(page: Page, delayMs: number): Promise<void> {
  await mockApi(page, false, { emotionControl: false });
  const wav = sineWav(3);
  await page.route("**/api/v1/synthesize", async (r) => {
    if (r.request().method() === "OPTIONS") return r.fulfill({ status: 204, headers: CORS });
    await new Promise((res) => setTimeout(res, delayMs));
    return r.fulfill({
      status: 200,
      contentType: "audio/wav",
      headers: { ...CORS, "Content-Disposition": 'attachment; filename="out.wav"' },
      body: wav,
    });
  });
}

const stage = (page: Page) => page.locator("section[data-state]");

async function generate(page: Page): Promise<void> {
  await page.getByLabel("Text").fill("Hello there, this is a test.");
  await page.getByRole("button", { name: "Generate speech" }).click();
}

/** Heights of the pulse bars that are showing right now (opacity above 0). */
const lit = (page: Page) =>
  page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-testid="take-pulse"] rect'))
      .filter((r) => Number(r.getAttribute("opacity")) > 0)
      .map((r) => Number(r.getAttribute("height"))),
  );

/** Open the Generate screen with a finished take. The visual config pins reduced motion on, so each test says which it wants. */
async function openTake(
  page: Page,
  reducedMotion: "reduce" | "no-preference" = "no-preference",
): Promise<void> {
  await page.emulateMedia({ reducedMotion });
  await mock(page, 300);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/generate`);
  await page.getByLabel("Text").fill("Hello there, this is a test.");
  await page.getByRole("button", { name: "Generate speech" }).click();
  await page.locator("section[data-state='done']").waitFor({ timeout: 10_000 });
  await expect(page.getByRole("slider", { name: /^Seek/ })).toBeEnabled({ timeout: 10_000 });
  await expect(page.getByTestId("take-pulse")).toBeAttached({ timeout: 10_000 });
}

test("the pulse follows the audio while the take plays and is gone when it pauses", async ({
  page,
}) => {
  test.setTimeout(30_000);
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/status of 40[14]|Failed to load resource/i.test(m.text()))
      problems.push(`console: ${m.text()}`);
  });
  await openTake(page);
  expect(await lit(page)).toEqual([]); // nothing until it plays

  await page.getByRole("button", { name: /^Play/ }).first().click();
  await expect(page.getByRole("button", { name: /^Pause/ }).first()).toBeVisible({
    timeout: 10_000,
  });
  // The take's level rises and falls, so the tallest lit bar changes from moment to moment.
  const tallest: number[] = [];
  for (let i = 0; i < 12; i++) {
    const heights = await lit(page);
    tallest.push(heights.length ? Math.max(...heights) : 0);
    await page.waitForTimeout(110);
  }
  expect(tallest.filter((h) => h > 0).length).toBeGreaterThan(6);
  expect(Math.max(...tallest) - Math.min(...tallest.filter((h) => h > 0))).toBeGreaterThan(2);
  // The audio itself is untouched: the element is really playing and its clock is moving.
  const playing = await page.evaluate(() => {
    const a = document.querySelector("audio") as HTMLAudioElement;
    return { paused: a.paused, time: a.currentTime };
  });
  expect(playing.paused).toBe(false);
  expect(playing.time).toBeGreaterThan(0);

  await page
    .getByRole("button", { name: /^Pause/ })
    .first()
    .click();
  await expect.poll(() => lit(page)).toEqual([]);
  expect(problems).toEqual([]);
});

test("under reduced motion the take plays but nothing pulses", async ({ page }) => {
  test.setTimeout(30_000);
  await openTake(page, "reduce");
  await page.getByRole("button", { name: /^Play/ }).first().click();
  await expect(page.getByRole("button", { name: /^Pause/ }).first()).toBeVisible({
    timeout: 10_000,
  });
  await page.waitForTimeout(800);
  expect(await lit(page)).toEqual([]);
  const time = await page.evaluate(
    () => (document.querySelector("audio") as HTMLAudioElement).currentTime,
  );
  expect(time).toBeGreaterThan(0); // still plays, and the clock still moves
});

test("the take's playhead and the pulse sit together: the lit bars surround the playhead", async ({
  page,
}) => {
  test.setTimeout(30_000);
  await openTake(page);
  await page.getByRole("button", { name: /^Play/ }).first().click();
  await expect.poll(async () => (await lit(page)).length, { timeout: 10_000 }).toBeGreaterThan(3);
  const where = await page.evaluate(() => {
    const svg = document.querySelector('[data-testid="take-pulse"]')!.closest("svg")!;
    const vb = svg.viewBox.baseVal.width;
    const xs = Array.from(svg.querySelectorAll('[data-testid="take-pulse"] rect'))
      .filter((r) => Number(r.getAttribute("opacity")) > 0)
      .map((r) => Number(r.getAttribute("x")));
    const a = document.querySelector("audio") as HTMLAudioElement;
    return {
      centre: (Math.min(...xs) + Math.max(...xs)) / 2 / vb,
      progress: a.currentTime / a.duration,
    };
  });
  expect(Math.abs(where.centre - where.progress)).toBeLessThan(0.15);
});
