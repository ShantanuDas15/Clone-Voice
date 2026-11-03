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

const ribbonState = (page: import("@playwright/test").Page) =>
  page.evaluate(() => {
    const svg = document.querySelector('[data-testid="home-wave"] svg') as SVGElement;
    const s = getComputedStyle(svg);
    return { name: s.animationName, play: s.animationPlayState };
  });

test("the ribbons drift at first, rest after three seconds, and stop while off screen", async ({
  page,
}) => {
  test.setTimeout(30_000);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto(`${ORIGIN}/`);
  const wave = page.getByTestId("home-wave");
  await expect.poll(async () => (await ribbonState(page)).name).toBe("drift");
  // WCAG 2.2.2: nothing may move on its own for more than five seconds, so they come to rest.
  await expect(wave).toHaveAttribute("data-paused", "true", { timeout: 8_000 });
  expect((await ribbonState(page)).play).toBe("paused");
});

test("the ribbons move again while the visitor's sample plays, and rest when it ends", async ({
  page,
}) => {
  test.setTimeout(45_000);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/`);
  const wave = page.getByTestId("home-wave");
  await expect(wave).toHaveAttribute("data-paused", "true", { timeout: 8_000 });
  await page.getByRole("button", { name: "Play sample" }).click();
  await expect(page.getByRole("button", { name: "Pause sample" })).toBeVisible({ timeout: 10_000 });
  await expect(wave).toHaveAttribute("data-paused", "false");
  expect((await ribbonState(page)).play).toBe("running");
  await expect(page.getByRole("button", { name: "Play sample" })).toBeVisible({ timeout: 15_000 });
  await expect(wave).toHaveAttribute("data-paused", "true");
  expect((await ribbonState(page)).play).toBe("paused");
});

test("the ribbons stop while scrolled out of view, even during the opening drift", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto(`${ORIGIN}/`);
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(page.getByTestId("home-wave")).toHaveAttribute("data-paused", "true");
  expect((await ribbonState(page)).play).toBe("paused");
});

test("six seconds after load, nothing on the page is still moving by itself", async ({ page }) => {
  test.setTimeout(30_000);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto(`${ORIGIN}/`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(6_000);
  // WCAG 2.2.2 (Pause, Stop, Hide): no endless animation may be running without a control for it.
  const endless = await page.evaluate(() =>
    document
      .getAnimations()
      .filter(
        (a) => a.playState === "running" && a.effect?.getComputedTiming().iterations === Infinity,
      )
      .map((a) => (a as CSSAnimation).animationName),
  );
  expect(endless).toEqual([]);
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
