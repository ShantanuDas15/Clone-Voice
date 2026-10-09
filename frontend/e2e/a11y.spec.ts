import { type Page, expect, test } from "@playwright/test";

import { seriousViolations } from "./audit";
import { createVoice, signUpVerified } from "./helpers";

test.use({ bypassCSP: true });

test("canary: the real-browser audit does flag low contrast and an unlabeled input", async ({
  page,
}) => {
  await page.goto("/login");
  await page.evaluate(() => {
    const bad = document.createElement("div");
    bad.innerHTML =
      '<p style="color:#ccc;background:#fff">hard to read text</p><input type="text" />';
    document.querySelector("main")?.append(bad);
  });
  const ids = (await seriousViolations(page)).map((v) => v.id);
  expect(ids).toContain("color-contrast");
  expect(ids).toContain("label");
});

const SCHEMES = ["light", "dark"] as const;

async function audit(page: Page, label: string) {
  // Axe reads computed colours, so let the 200 ms dialog fade finish (mid-fade is blended).
  await page.waitForFunction(() =>
    document.getAnimations().every((a) => a.playState !== "running"),
  );
  expect(await seriousViolations(page), label).toEqual([]);
}

for (const scheme of SCHEMES) {
  test(`public pages have no serious axe violations (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    for (const path of [
      "/",
      "/login",
      "/login?error=google_failed",
      "/signup",
      "/forgot-password",
      "/verify-email",
      "/reset-password",
    ]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await audit(page, `${path} (${scheme})`);
    }
  });

  test(`signed-in screens and dialogs have no serious axe violations (${scheme})`, async ({
    page,
  }) => {
    test.setTimeout(240_000);
    await page.emulateMedia({ colorScheme: scheme });
    await signUpVerified(page, `ax${scheme}`);
    await createVoice(page, "Audit voice");
    await audit(page, `/voices (${scheme})`);

    await page.getByRole("radio", { name: "Record now" }).click();
    await audit(page, `recorder idle (${scheme})`);
    await page.getByRole("radio", { name: "Upload a file" }).click();

    await page.getByRole("button", { name: "Delete Audit voice" }).click();
    await audit(page, `delete-voice dialog (${scheme})`);
    await page.getByRole("button", { name: "Cancel" }).click();

    await page.goto("/account"); // delete-account moved here with the route split
    await page.getByRole("button", { name: /delete my account/i }).click();
    await audit(page, `delete-account dialog (${scheme})`);

    await page.goto("/generate");
    await page.getByLabel("Text").waitFor();
    await audit(page, `/generate (${scheme})`);
  });
}
