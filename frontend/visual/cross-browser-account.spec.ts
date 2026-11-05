import { expect, test } from "@playwright/test";

import { ORIGIN, mockApi } from "./mock-api";

/**
 * The Account screen in the real engines (UX plan §12.28): the section rail, the voiceprint ring,
 * the data counters, and Pause motion holding the endless animation still.
 */
test("the account screen shows its rail, ring and counters, and Pause motion holds the animation", async ({
  page,
}) => {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await mockApi(page, false);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(`${ORIGIN}/account`);

  const rail = page.getByRole("navigation", { name: "Account sections" });
  await expect(rail.getByRole("link")).toHaveCount(4);
  await expect(page.locator(".ax-ring-canvas")).toBeVisible();
  await expect(page.getByRole("list", { name: "What is stored for you" })).toBeVisible();

  // Typing a name changes the ring's initials.
  const name = page.getByLabel("Display name");
  await name.fill("grace hopper");
  await expect(page.getByTestId("ring-initials")).toHaveText("GH");

  // A rail link takes you to its section.
  await rail.getByRole("link", { name: "Delete account" }).click();
  await expect(page.locator("#s-delete")).toBeInViewport();

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
  expect(problems).toEqual([]);
});
