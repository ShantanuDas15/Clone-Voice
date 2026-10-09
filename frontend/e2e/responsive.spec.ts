import { type Page, expect, test } from "@playwright/test";

import { signUpVerified } from "./helpers";

const VIEWPORTS = [
  { name: "320", width: 320, height: 640 },
  { name: "768", width: 768, height: 1024 },
  { name: "1280", width: 1280, height: 800 },
] as const;

async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/** Visible buttons/inputs smaller than 44 px (touch target, plan §5.11). */
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const out: string[] = [];
    document
      .querySelectorAll(
        "a[href], button, input:not([type=checkbox]):not([type=radio]), select, textarea",
      )
      .forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return;
        if (el.closest(".sr-only")) return; // visually hidden (the file input)
        // Links inside running text are exempt (WCAG 2.5.8 inline exception); the logo,
        // nav and tab links are not.
        if (el.tagName === "A" && getComputedStyle(el).display === "inline") return;
        if (r.height < 43.5)
          out.push(
            `${el.tagName.toLowerCase()} "${(el.textContent || (el as HTMLInputElement).name || "").trim().slice(0, 30)}" ${Math.round(r.height)}px`,
          );
      });
    return out;
  });
}

for (const vp of VIEWPORTS) {
  test(`no horizontal scroll and 44px targets at ${vp.name}px`, async ({ page }) => {
    test.setTimeout(120_000);
    await page.setViewportSize({ width: vp.width, height: vp.height });
    for (const path of ["/", "/login", "/signup", "/forgot-password"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await overflow(page), `${path} overflows at ${vp.name}`).toBeLessThanOrEqual(0);
      expect(await smallTargets(page), `${path} small targets at ${vp.name}`).toEqual([]);
    }
    await signUpVerified(page, `vp${vp.name}`);
    for (const path of ["/generate", "/voices", "/history", "/account"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await overflow(page), `${path} overflows at ${vp.name}`).toBeLessThanOrEqual(0);
      expect(await smallTargets(page), `${path} small targets at ${vp.name}`).toEqual([]);
    }
  });
}

test("content reflows at 400% zoom (320 CSS px wide) without horizontal scroll", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 256 });
  await page.goto("/login");
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});

test("an email address with a long unbroken segment wraps instead of overflowing the account section at 320px", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 640 });
  const email = await signUpVerified(page, "a".repeat(40));
  expect(email.length).toBeGreaterThan(45);
  await page.goto("/account");
  await expect(page.getByText(email)).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(0);
});
