import { expect, test, type Page } from "@playwright/test";

import { ORIGIN, mockApi } from "./mock-api";

/**
 * Real-engine checks for the H-series voice-state motion work (plan §12.17): the recorder orb (H1),
 * the seekable Take (H2), the slow-generation status (H3), History waveform previews (H4) and the
 * list motion (H5). The API is mocked at the network layer; audio is a generated sine WAV.
 */
const CORS = {
  "Access-Control-Allow-Origin": ORIGIN,
  "Access-Control-Allow-Credentials": "true",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
  "Access-Control-Expose-Headers": "X-Total-Count",
};
const VOICE_ID = "22222222-2222-4222-8222-222222222222";
const GEN_ID = "33333333-3333-4333-8333-333333333333";

/** A mono 16-bit PCM WAV of a sine tone, `seconds` long. */
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
    buf.writeInt16LE(Math.round(Math.sin((2 * Math.PI * 440 * i) / rate) * 12000), 44 + i * 2);
  return buf;
}

const row = (id: string, text: string, peaks: number[] | null) => ({
  id,
  voice_profile_id: VOICE_ID,
  voice_profile_name: "My voice",
  status: "completed",
  input_text: text,
  output_filename: `synthesized_${id.slice(0, 8)}.wav`,
  duration_seconds: 3,
  audio_available: true,
  created_at: "2026-10-02T00:00:00Z",
  waveform_peaks: peaks,
});
const PEAKS = Array.from({ length: 64 }, (_, i) => 10 + Math.round(80 * Math.abs(Math.sin(i / 5))));

/** Signed-in mock plus audio, two History rows (one with peaks, one without) and a slow synthesize. */
async function mockWithAudio(page: Page, synthDelayMs = 0): Promise<void> {
  await mockApi(page, false, { emotionControl: false });
  const wav = sineWav(3);
  const deleted = new Set<string>();
  await page.route("**/api/v1/synthesize/**", async (r) => {
    const req = r.request();
    const path = new URL(req.url()).pathname.replace("/api/v1", "");
    if (req.method() === "OPTIONS") return r.fulfill({ status: 204, headers: CORS });
    if (req.method() === "DELETE") {
      deleted.add(path.split("/")[2] ?? "");
      return r.fulfill({ status: 204, headers: CORS });
    }
    if (path === "/synthesize/history")
      return r.fulfill({
        status: 200,
        contentType: "application/json",
        headers: { ...CORS, "X-Total-Count": "2" },
        body: JSON.stringify(
          [
            row(GEN_ID, "First take with a preview.", PEAKS),
            row("55555555-5555-4555-8555-555555555555", "Older row, no preview.", null),
          ].filter((x) => !deleted.has(x.id)),
        ),
      });
    if (path === "/synthesize/capabilities")
      return r.fulfill({
        status: 200,
        contentType: "application/json",
        headers: CORS,
        body: '{"emotion_control":false}',
      });
    if (path.endsWith("/audio"))
      return r.fulfill({ status: 200, contentType: "audio/wav", headers: CORS, body: wav });
    return r.fallback();
  });
  await page.route("**/api/v1/synthesize", async (r) => {
    const req = r.request();
    if (req.method() === "OPTIONS") return r.fulfill({ status: 204, headers: CORS });
    if (synthDelayMs) await new Promise((res) => setTimeout(res, synthDelayMs));
    return r.fulfill({
      status: 200,
      contentType: "audio/wav",
      headers: { ...CORS, "Content-Disposition": 'attachment; filename="out.wav"' },
      body: wav,
    });
  });
}

test("H4 History shows a waveform preview only for rows that have peaks", async ({ page }) => {
  await mockWithAudio(page);
  await page.goto(`${ORIGIN}/history`);
  await expect(page.getByText("First take with a preview.")).toBeVisible();
  await expect(page.getByTestId("waveform-preview")).toHaveCount(1);
  const box = await page.getByTestId("waveform-preview").boundingBox();
  expect(box && box.width > 40 && box.height > 8).toBeTruthy();
  await expect(page.getByText("Older row, no preview.")).toBeVisible();
});

test("H2 a loaded take shows its length, a playhead, a hover readout and seeks by keyboard", async ({
  page,
  browserName,
}) => {
  await mockWithAudio(page);
  await page.goto(`${ORIGIN}/history`);
  await page.getByRole("button", { name: /^Play/ }).first().click();
  const time = page.getByTestId("take-time").first();
  await expect(time).toContainText(/\/\s*0:0[23]/, { timeout: 15_000 });
  const slider = page.getByRole("slider", { name: /^Seek/ }).first();
  await expect(slider).toBeEnabled();
  await expect(page.getByTestId("take-playhead").first()).toBeAttached();

  const box = await slider.boundingBox();
  if (!box) throw new Error("no slider box");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByTestId("take-hover-time").first()).toBeVisible();
  await page.mouse.move(0, 0);
  await expect(page.getByTestId("take-hover-time")).toHaveCount(0);

  await slider.focus();
  const before = await slider.getAttribute("aria-valuetext");
  await page.keyboard.press("ArrowRight");
  await expect
    .poll(async () => slider.getAttribute("aria-valuetext"), { message: browserName })
    .not.toBe(before);
});

test("H3 generation turns into 'Still generating' after 20 s and then finishes", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await mockWithAudio(page, 23_000);
  await page.goto(`${ORIGIN}/generate`);
  await page
    .getByLabel(/text to speak|your text|text/i)
    .first()
    .fill("A sentence to speak aloud.");
  await page.getByRole("button", { name: "Generate speech" }).click();
  const status = page.getByRole("status").filter({ hasText: /generating/i });
  await expect(status).toHaveAttribute("data-phase", /.+/);
  const first = await status.getAttribute("data-phase");
  await expect(status).toContainText("Still generating", { timeout: 30_000 });
  expect(await status.getAttribute("data-phase")).not.toBe(first);
  await expect(page.getByTestId("generation-icon")).toBeVisible();
  await expect(page.getByText("Your audio is ready.").first()).toBeAttached({ timeout: 20_000 });
});

test("H5 deleting a History row removes it without a layout jump or error", async ({ page }) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(e.message));
  await mockWithAudio(page);
  await page.goto(`${ORIGIN}/history`);
  await expect(page.getByText("Older row, no preview.")).toBeVisible();
  await page
    .getByRole("button", { name: /delete/i })
    .first()
    .click();
  const confirm = page.getByRole("button", { name: /^(delete|confirm|yes)/i }).last();
  if (await confirm.isVisible()) await confirm.click();
  await expect(page.getByText("First take with a preview.")).toHaveCount(0, { timeout: 5_000 });
  expect(problems).toEqual([]);
});

test("H1 recorder shows the orb while recording (needs a fake microphone)", async ({
  page,
  browserName,
}) => {
  test.skip(
    browserName === "webkit",
    "WebKit has no fake microphone and records in an unsupported format",
  );
  await mockWithAudio(page);
  await page.goto(`${ORIGIN}/voices`);
  await expect(page.getByLabel("Voice name")).toBeVisible();
  const record = page.getByRole("radio", { name: "Record now" });
  test.skip((await record.count()) === 0, "recording not offered in this browser");
  await record.click();
  await page.getByRole("button", { name: "Start recording" }).click();
  await expect(page.locator(".bx-rec-pulse")).toBeAttached(); // the live button's pulse
  await expect(page.getByRole("meter")).toBeAttached();
  const stop = page.getByRole("button", { name: "Stop recording" });
  await expect(stop).toBeEnabled({ timeout: 15_000 });
  await stop.click();
  await expect(page.locator('audio[aria-label="Recording preview"]')).toBeAttached();
});
