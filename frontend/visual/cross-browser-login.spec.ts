import { expect, test } from "@playwright/test";

import { ORIGIN, mockSignedOut } from "./mock-api";

/**
 * The sign-in and sign-up voice panel in the real engines (UX plan §12.24): beside the form from
 * 1024 px, a thin wave above the card below that, drawn once and then still, nothing scrolls
 * sideways, and no script or policy errors.
 */
test.beforeEach(async ({ page }) => {
  await mockSignedOut(page);
});

for (const route of ["login", "signup"]) {
  test(`${route}: the panel sits beside the form at 1280 and gives way to the strip at 768`, async ({
    page,
  }) => {
    const problems: string[] = [];
    page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error" && !/status of 40[14]|Failed to load resource/i.test(m.text()))
        problems.push(`console: ${m.text()}`);
    });
    await page.emulateMedia({ reducedMotion: "no-preference" });

    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto(`${ORIGIN}/${route}`);
    const panel = page.getByTestId("voice-panel");
    await expect(panel).toBeVisible();
    const waves = page.getByTestId("voice-wave");
    await expect(waves.first()).toBeVisible();
    await expect(waves.last()).toBeHidden(); // the strip is for narrow screens
    const form = page.locator("main form");
    const [p, f] = await Promise.all([panel.boundingBox(), form.boundingBox()]);
    expect(p!.x + p!.width).toBeLessThanOrEqual(f!.x); // beside, not over
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);

    await page.setViewportSize({ width: 768, height: 900 });
    await expect(panel).toBeHidden();
    await expect(waves.last()).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    expect(problems).toEqual([]);
  });
}

test("the draw-in finishes and leaves nothing moving", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/login`);
  await expect(page.getByTestId("voice-panel")).toBeVisible();
  await page.waitForTimeout(2500); // 56 bars: the last starts at about 340 ms and runs 380 ms
  const running = await page.evaluate(
    () =>
      document
        .getAnimations()
        .filter((a) => a.playState === "running" && (a as CSSAnimation).animationName)
        .map((a) => (a as CSSAnimation).animationName).length,
  );
  expect(running).toBe(0);
});

test("under reduced motion the finished wave is there at once and nothing animates", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/login`);
  await expect(page.getByTestId("voice-wave").first().locator("rect")).toHaveCount(56);
  const animated = await page.evaluate(
    () => document.getAnimations().filter((a) => (a as CSSAnimation).animationName).length,
  );
  expect(animated).toBe(0);
});
