import { type Page, expect, test } from "@playwright/test";

import { createVoice, signUpVerified } from "./helpers";

/** CSP soak: browse every flow in a real browser and collect report-only violations. */
async function collectViolations(page: Page): Promise<string[]> {
  const found: string[] = [];
  page.on("console", (m) => {
    if (/content security policy|violates the following/i.test(m.text())) found.push(m.text());
  });
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      (window as unknown as { __csp: string[] }).__csp ??= [];
      (window as unknown as { __csp: string[] }).__csp.push(
        `${e.violatedDirective} ${e.blockedURI}`,
      );
    });
  });
  return found;
}

test("no CSP violations across public pages, the app, playback and recording", async ({ page }) => {
  test.setTimeout(420_000);
  const violations = await collectViolations(page);
  for (const path of ["/", "/login", "/signup", "/forgot-password", "/verify-email"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  await signUpVerified(page, "csp");
  await createVoice(page, "CSP voice");
  await page.goto("/generate");
  await page.waitForLoadState("networkidle");
  await page.goto("/voices");
  await page.getByRole("radio", { name: "Record now" }).click();
  await page.getByRole("button", { name: "Start recording" }).click();
  await expect(page.getByRole("button", { name: "Stop recording" })).toBeEnabled({
    timeout: 15_000,
  });
  await page.getByRole("button", { name: "Stop recording" }).click();
  await expect(page.getByLabel("Recording preview")).toBeVisible();

  const inPage = await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []);
  expect([...violations, ...inPage]).toEqual([]);
});

test("the CSP header is present with a per-response nonce", async ({ request }) => {
  const a = await request.get("/login");
  const b = await request.get("/login");
  const header = (r: typeof a) =>
    r.headers()["content-security-policy"] ??
    r.headers()["content-security-policy-report-only"] ??
    "";
  const nonce = (h: string) => /'nonce-([^']+)'/.exec(h)?.[1];
  expect(nonce(header(a))).toBeTruthy();
  expect(nonce(header(a))).not.toBe(nonce(header(b)));
});
