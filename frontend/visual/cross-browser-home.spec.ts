import { expect, test } from "@playwright/test";

import { ORIGIN, mockSignedOut } from "./mock-api";

/**
 * The home page in the real engines (UX plan §12.19): the sample plays for real, the background
 * reacts and pauses, nothing scrolls sideways at any width, and reduced motion stops all movement.
 */
test.beforeEach(async ({ page }) => {
  await mockSignedOut(page);
});

test("the sample plays the real clip, the wave reacts, and it resets when it ends", async ({
  page,
}) => {
  test.setTimeout(45_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/`);
  const wave = page.getByTestId("home-wave");
  await expect(wave).toHaveAttribute("data-live", "false");
  // Nothing is fetched until Play is pressed.
  const requested: string[] = [];
  page.on("request", (r) => requested.push(r.url()));
  await page.waitForTimeout(500);
  expect(requested.filter((u) => u.endsWith("home-sample.wav"))).toEqual([]);

  await page.getByRole("button", { name: "Play sample" }).click();
  await expect(page.getByRole("button", { name: "Pause sample" })).toBeVisible({ timeout: 10_000 });
  await expect(wave).toHaveAttribute("data-live", "true");
  // The clock moves off 0:00 and the bars take the accent colour as the playhead advances.
  await expect(page.getByTestId("sample-time")).not.toHaveText(/^0:00 \//, { timeout: 5_000 });
  await expect(page.getByTestId("sample-wave").locator("rect.fill-primary").first()).toBeAttached();

  // The clip is 2.9 s: it ends on its own, the button goes back to Play and the wave settles.
  await expect(page.getByRole("button", { name: "Play sample" })).toBeVisible({ timeout: 15_000 });
  await expect(wave).toHaveAttribute("data-live", "false");
  await expect(page.getByTestId("sample-time")).toHaveText(/^0:00 \//);
  expect(requested.filter((u) => u.endsWith("home-sample.wav")).length).toBeGreaterThan(0);
});

for (const width of [375, 768, 1100, 1280, 1920, 2560]) {
  test(`nothing scrolls sideways @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${ORIGIN}/`);
    await page.waitForLoadState("networkidle");
    const over = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(over).toBeLessThanOrEqual(0);
  });
}

test("the side bars appear only where the page leaves room for them", async ({ page }) => {
  await page.goto(`${ORIGIN}/`);
  const bar = page.getByTestId("home-bars").first();
  await page.setViewportSize({ width: 1100, height: 800 });
  await expect(bar).toBeHidden();
  await page.setViewportSize({ width: 1440, height: 800 });
  await expect(bar).toBeVisible();
});

test("the ribbons drift where motion is allowed, and pause once scrolled out of view", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto(`${ORIGIN}/`);
  const state = () =>
    page.evaluate(() => {
      const svg = document.querySelector('[data-testid="home-wave"] svg') as SVGElement;
      const s = getComputedStyle(svg);
      return { name: s.animationName, play: s.animationPlayState };
    });
  await expect.poll(async () => (await state()).name).toBe("drift");
  expect((await state()).play).toBe("running");
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(page.getByTestId("home-wave")).toHaveAttribute("data-paused", "true");
  expect((await state()).play).toBe("paused");
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect(page.getByTestId("home-wave")).toHaveAttribute("data-paused", "false");
});

test("under reduced motion nothing on the home page animates", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto(`${ORIGIN}/`);
  await page.waitForLoadState("networkidle");
  const running = await page.evaluate(() =>
    document
      .getAnimations()
      .filter((a) => a.playState === "running" && (a as CSSAnimation).animationName)
      .map((a) => (a as CSSAnimation).animationName),
  );
  expect(running).toEqual([]);
});
