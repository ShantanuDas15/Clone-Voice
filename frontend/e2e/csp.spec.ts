import { type Page, expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

import { createVoice, signUpVerified } from "./helpers";

/** CSP soak: browse every flow in a real browser and collect report-only violations. */
async function collectViolations(page: Page): Promise<string[]> {
  const found: string[] = [];
  page.on("console", (m) => {
    // WebKit also prints a note that a report-only policy without `report-to` has no effect (the
    // soak policy sets none, FE-UX27); that is not a violation.
    if (/delivered in report-only mode/i.test(m.text())) return;
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
  for (const path of ["/", "/login", "/signup", "/forgot-password", "/verify-email", "/terms"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
  }
  await signUpVerified(page, "csp");
  await createVoice(page, "CSP voice");
  await page.goto("/generate");
  await page.waitForLoadState("networkidle");
  await page.goto("/voices");
  // Where recording is unsupported (WebKit) the recorder is not offered (UR16); wait for the form
  // to settle, then run the recording part only if it is there.
  await expect(page.getByLabel("Voice name")).toBeVisible();
  if (await page.getByRole("radio", { name: "Record now" }).count()) {
    await page.getByRole("radio", { name: "Record now" }).click();
    await page.getByRole("button", { name: "Start recording" }).click();
    await expect(page.getByRole("button", { name: "Stop recording" })).toBeEnabled({
      timeout: 15_000,
    });
    await page.getByRole("button", { name: "Stop recording" }).click();
    await expect(page.locator('audio[aria-label="Recording preview"]')).toBeAttached();
  }

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

test.describe("violation reporting (FE-UX40)", () => {
  test("a real violation reaches the endpoint and is logged scrubbed", async ({
    page,
    browserName,
  }) => {
    const logPath = process.env.E2E_FRONTEND_LOG;
    test.skip(!logPath, "set E2E_FRONTEND_LOG to the web server's log file (e2e/README.md)");
    test.skip(browserName === "webkit", "WebKit needs the HTTPS recipe (e2e/README.md)");
    // Playwright cannot see a browser-initiated report request, so the proof is the server's log.
    await page.goto("/login#token=SECRET-FRAGMENT");
    await page.waitForLoadState("networkidle");
    const probe = `/csp-probe-${Date.now()}`;
    await page.evaluate((path) => {
      // An image from a host the policy does not allow. (A script inserted from page code is
      // trusted under `strict-dynamic`, so it is not a usable probe.) `.invalid` never resolves.
      const img = document.createElement("img");
      img.src = `https://csp-probe.invalid${path}.png?secret=QUERY-SECRET`;
      document.body.appendChild(img);
    }, probe);
    let line = "";
    for (let i = 0; i < 100 && !line; i += 1) {
      line =
        readFileSync(logPath as string, "utf8")
          .split("\n")
          .find((l) => l.includes("csp-violation") && l.includes(probe)) ?? "";
      if (!line) await new Promise((r) => setTimeout(r, 250));
    }
    expect(line, "the violation was logged").not.toBe("");
    const record = JSON.parse(line) as Record<string, string>;
    expect(record.event).toBe("csp-violation");
    expect(record.directive).toBe("img-src");
    expect(record.page).toBe("/login");
    expect(line).not.toMatch(/SECRET/);
  });

  test("the endpoint takes POST only, never echoes, and ignores junk", async ({ request }) => {
    const junk = await request.post("/csp-report", {
      headers: { "content-type": "application/csp-report" },
      data: "not json",
    });
    expect(junk.status()).toBe(204);
    expect(await junk.text()).toBe("");
    expect((await request.get("/csp-report")).status()).toBe(405);
  });

  test("the endpoint answers without a nonce policy of its own", async ({ request }) => {
    const res = await request.post("/csp-report", {
      headers: { "content-type": "application/csp-report" },
      data: "{}",
    });
    expect(res.headers()["content-security-policy-report-only"]).toBeUndefined();
  });
});
