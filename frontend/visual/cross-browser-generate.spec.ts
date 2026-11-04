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

test("the stage holds its place from ready to working, then shows the take", async ({ page }) => {
  test.setTimeout(30_000);
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error" && !/status of 40[14]|Failed to load resource/i.test(m.text()))
      problems.push(`console: ${m.text()}`);
  });
  await mock(page, 2_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/generate`);
  await expect(stage(page)).toHaveAttribute("data-state", "ready");
  await expect(page.getByTestId("stage-voiceprint")).toBeVisible();
  const ready = await stage(page).boundingBox();

  await generate(page);
  await expect(stage(page)).toHaveAttribute("data-state", "working");
  await expect(stage(page).getByRole("status")).toContainText(/generating/i);
  await expect(page.getByTestId("stage-voiceprint")).toBeVisible();
  const working = await stage(page).boundingBox();
  // The frame does not move or resize between ready and working.
  expect(Math.abs((working?.y ?? 0) - (ready?.y ?? 0))).toBeLessThanOrEqual(1);
  expect(Math.abs((working?.height ?? 0) - (ready?.height ?? 0))).toBeLessThanOrEqual(2);

  await expect(stage(page)).toHaveAttribute("data-state", "done", { timeout: 10_000 });
  await expect(stage(page).getByRole("button", { name: "Play Generated speech" })).toBeVisible();
  await expect(stage(page).getByText("My voice")).toBeVisible();
  await expect(page.getByTestId("stage-voiceprint")).toHaveCount(0);
  const done = await stage(page).boundingBox();
  expect(Math.abs((done?.y ?? 0) - (ready?.y ?? 0))).toBeLessThanOrEqual(1);
  expect(problems).toEqual([]);
});

test("Generate again keeps the keyboard on the Generate button", async ({ page }) => {
  test.setTimeout(30_000);
  await mock(page, 800);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/generate`);
  await generate(page);
  const again = page.getByRole("button", { name: "Generate again" });
  await expect(again).toBeVisible({ timeout: 10_000 });
  await again.focus();
  await page.keyboard.press("Enter");
  await expect(stage(page)).toHaveAttribute("data-state", "working");
  await expect(page.getByRole("button", { name: /Generating/ })).toBeFocused();
});

test("on a phone the ready panel is hidden, and the status and take appear in view", async ({
  page,
}) => {
  test.setTimeout(30_000);
  await mock(page, 1_500);
  await page.setViewportSize({ width: 375, height: 700 });
  await page.goto(`${ORIGIN}/generate`);
  await expect(stage(page)).toBeHidden();
  await generate(page);
  await expect(stage(page)).toBeVisible();
  await expect(stage(page).getByRole("status")).toContainText(/generating/i);
  await expect(stage(page)).toBeInViewport();
  await expect(stage(page)).toHaveAttribute("data-state", "done", { timeout: 10_000 });
  await expect(stage(page)).toBeInViewport();
  const over = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(over).toBeLessThanOrEqual(0);
});

test("the length meter follows the text", async ({ page }) => {
  await mock(page, 0);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/generate`);
  const meter = page.getByTestId("length-meter");
  await expect(meter).toHaveJSProperty("value", 0);
  await page.getByLabel("Text").fill("x".repeat(250));
  await expect(meter).toHaveJSProperty("value", 250);
  await expect(meter).toHaveAttribute("data-over", "false");
  await page.getByLabel("Text").fill("x".repeat(520));
  await expect(meter).toHaveJSProperty("value", 500);
  await expect(meter).toHaveAttribute("data-over", "true");
});

test("the voiceprint listens while you type, and Pause motion holds the endless animation still", async ({
  page,
}) => {
  await mock(page, 0);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/generate`);
  const stageVoice = page.getByTestId("stage-voiceprint");
  await expect(stageVoice).toBeVisible();
  await page.getByLabel("Text").pressSequentially("Hello there");
  await expect(stageVoice).toContainText("listening");

  const endless = () =>
    page.evaluate(() =>
      document
        .getAnimations()
        .filter(
          (a) => a.playState === "running" && a.effect?.getComputedTiming().iterations === Infinity,
        )
        .map((a) => (a as CSSAnimation).animationName),
    );
  expect((await endless()).length).toBeGreaterThan(0); // the aurora drifts
  await page.getByRole("button", { name: "Pause motion" }).click();
  await expect.poll(endless).toEqual([]);
  await page.getByRole("button", { name: "Resume motion" }).click();
  await expect.poll(async () => (await endless()).length).toBeGreaterThan(0);
});

test("choosing a voice card selects its radio", async ({ page }) => {
  await mock(page, 0);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/generate`);
  await page.locator("label.gx-vc").first().click();
  await expect(page.locator('input[name="tts-voice"]').first()).toBeChecked();
});
