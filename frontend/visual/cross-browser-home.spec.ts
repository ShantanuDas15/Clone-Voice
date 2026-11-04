import { expect, test } from "@playwright/test";

import { ORIGIN, mockSignedOut } from "./mock-api";

/**
 * The home page in the real engines (UX plan §12.25): the sample plays for real and the stage reacts,
 * the pointer swells the bars, the two promises can be tried, nothing scrolls sideways at any width,
 * the visitor can pause the endless motion, and reduced motion stops all of it.
 */
test.beforeEach(async ({ page }) => {
  await mockSignedOut(page);
});

test("the sample plays the real clip, the stage reacts, and it resets when it ends", async ({
  page,
}) => {
  test.setTimeout(45_000);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/`);
  const stage = page.getByTestId("home-voiceprint");
  await expect(stage).toHaveAttribute("data-live", "false");
  // Nothing is fetched until Play is pressed.
  const requested: string[] = [];
  page.on("request", (r) => requested.push(r.url()));
  await page.waitForTimeout(500);
  expect(requested.filter((u) => u.endsWith("home-sample.wav"))).toEqual([]);

  await page.getByRole("button", { name: "Play sample" }).click();
  await expect(page.getByRole("button", { name: "Pause sample" })).toBeVisible({ timeout: 10_000 });
  await expect(stage).toHaveAttribute("data-live", "true");
  await expect(page.getByTestId("sample-time")).not.toHaveText(/^0:00 \//, { timeout: 5_000 });

  // The clip is 2.9 s: it ends on its own, the button goes back to Play and the stage settles.
  await expect(page.getByRole("button", { name: "Play sample" })).toBeVisible({ timeout: 15_000 });
  await expect(stage).toHaveAttribute("data-live", "false");
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

test("the voiceprint paints, and the bars swell where the pointer is", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/`);
  const stage = page.getByTestId("home-voiceprint");
  await expect(stage).toBeVisible();
  const ink = () =>
    stage.evaluate((c: HTMLCanvasElement) => {
      const px = c.getContext("2d")!.getImageData(0, 0, c.width, c.height).data;
      let n = 0;
      for (let i = 3; i < px.length; i += 4) n += px[i]!;
      return n;
    });
  expect(await ink()).toBeGreaterThan(5_000);
  // Hold the endless ripple still so only the pointer can change what is drawn.
  await page.getByRole("button", { name: "Pause motion" }).click();
  await page.waitForTimeout(150);
  const before = await ink();
  const box = (await stage.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(250);
  expect(await ink()).not.toBe(before);
});

test("the consent gate stays locked until the box is ticked", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/`);
  const gate = page.getByTestId("consent-gate");
  await gate.scrollIntoViewIfNeeded();
  const create = gate.getByRole("button", { name: "Create voice" });
  await expect(create).toHaveAttribute("aria-disabled", "true");
  await gate.getByLabel("I have the right to use this voice.").check();
  await expect(create).toHaveAttribute("aria-disabled", "false");
  await create.click();
  await expect(gate.getByRole("status")).toContainText("Voice created (example)");
});

test("deleting the example voice erases it and everything made with it, and can start over", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/`);
  const demo = page.getByTestId("erase-demo");
  await demo.scrollIntoViewIfNeeded();
  await demo.getByRole("button", { name: "Delete voice" }).click();
  await expect(demo.getByRole("status")).toContainText("Voice and 3 takes erased", {
    timeout: 5_000,
  });
  await demo.getByRole("button", { name: "Start over" }).click();
  await expect(demo.getByRole("button", { name: "Delete voice" })).toBeEnabled();
});

test("the how-it-works picture follows the step in view", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`${ORIGIN}/`);
  const steps = page.locator(".hx-step");
  await steps.nth(1).scrollIntoViewIfNeeded();
  await expect(steps.nth(1)).toHaveClass(/hx-on/);
  await steps.nth(2).scrollIntoViewIfNeeded();
  await expect(steps.nth(2)).toHaveClass(/hx-on/);
});

const endless = (page: import("@playwright/test").Page) =>
  page.evaluate(() =>
    document
      .getAnimations()
      .filter(
        (a) => a.playState === "running" && a.effect?.getComputedTiming().iterations === Infinity,
      )
      .map((a) => (a as CSSAnimation).animationName),
  );

test("Pause motion holds every endless animation still, and Resume starts them again (WCAG 2.2.2)", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1440, height: 800 });
  await page.goto(`${ORIGIN}/`);
  await page.waitForLoadState("networkidle");
  expect((await endless(page)).length).toBeGreaterThan(0);
  await page.getByRole("button", { name: "Pause motion" }).click();
  await expect.poll(() => endless(page)).toEqual([]);
  await page.getByRole("button", { name: "Resume motion" }).click();
  await expect.poll(async () => (await endless(page)).length).toBeGreaterThan(0);
});

test("under reduced motion nothing on the home page animates and there is nothing to pause", async ({
  page,
}) => {
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
  await expect(page.getByRole("button", { name: "Pause motion" })).toBeHidden();
});
