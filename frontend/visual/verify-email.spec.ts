import { expect, test } from "@playwright/test";

import { ORIGIN } from "./mock-api";

/**
 * /verify-email has no screen of its own to open (it needs an emailed token), so each state is
 * reached by mocking the verify call: the answer, and whether a session exists.
 */
const CORS = {
  "Access-Control-Allow-Origin": ORIGIN,
  "Access-Control-Allow-Credentials": "true",
  "Access-Control-Allow-Headers": "*",
  "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,OPTIONS",
};
const unverifiedUser = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "ada@example.com",
  name: "Ada",
  avatar_url: null,
  provider: "local",
  has_password: true,
  email_verified_at: null,
  created_at: "2026-10-01T00:00:00Z",
};
const json = (status: number, body: unknown) => ({
  status,
  contentType: "application/json",
  headers: CORS,
  body: JSON.stringify(body),
});

const STATES = [
  { name: "verified", hash: "#token=t", verify: 200, signedIn: false },
  { name: "verified-signed-in", hash: "#token=t", verify: 200, signedIn: true },
  { name: "incomplete", hash: "", verify: 200, signedIn: false },
  { name: "invalid-signed-in", hash: "#token=t", verify: 400, signedIn: true },
  { name: "error", hash: "#token=t", verify: 500, signedIn: false },
] as const;
const VIEWS = [
  { width: 375, theme: "light" },
  { width: 1280, theme: "dark" },
] as const;

for (const state of STATES) {
  for (const { width, theme } of VIEWS) {
    test(`verify-email ${state.name} @${width} ${theme}`, async ({ page, context }) => {
      await context.addCookies([{ name: "cv-theme", value: theme, url: ORIGIN }]);
      await page.setViewportSize({ width, height: 800 });
      await page.route("**/health**", (r) => r.fulfill(json(200, { status: "ok" })));
      await page.route("**/api/v1/**", (r) => {
        const request = r.request();
        const path = new URL(request.url()).pathname.replace("/api/v1", "");
        if (request.method() === "OPTIONS") return r.fulfill({ status: 204, headers: CORS });
        if (path === "/auth/verify-email")
          return r.fulfill(json(state.verify, { detail: state.verify === 200 ? "ok" : "no" }));
        if (path === "/auth/refresh")
          return r.fulfill(
            state.signedIn ? json(200, { access_token: "t", token_type: "bearer" }) : json(401, {}),
          );
        if (path === "/auth/me")
          return r.fulfill(state.signedIn ? json(200, unverifiedUser) : json(401, {}));
        return r.fulfill(json(401, {}));
      });
      await page.goto(`/verify-email${state.hash}`);
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText("Verifying your email…")).toHaveCount(0);
      await expect(page).toHaveScreenshot(`verify-email-${state.name}-${width}-${theme}.png`, {
        fullPage: true,
      });
    });
  }
}
