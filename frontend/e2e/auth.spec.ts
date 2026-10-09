import { type Page, expect, test } from "@playwright/test";

import { PASSWORD, signOut, signUp, uniqueEmail } from "./helpers";

async function tokenInStorage(page: Page): Promise<boolean> {
  return page.evaluate(() => {
    const dump = JSON.stringify([
      Object.entries(localStorage),
      Object.entries(sessionStorage),
      document.cookie,
    ]);
    return /eyJ[A-Za-z0-9_-]{10,}\./.test(dump); // a JWT
  });
}

test("signup keeps the session across reloads, stores no token, and logs out", async ({ page }) => {
  const email = uniqueEmail("auth");
  await signUp(page, email);
  expect(await tokenInStorage(page)).toBe(false);

  await page.reload();
  await expect(page).toHaveURL(/\/generate/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  expect(await tokenInStorage(page)).toBe(false);

  await signOut(page);
  await page.goto("/generate");
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/generate/);
});

test("wrong password gives one generic message", async ({ page }) => {
  const email = uniqueEmail("badpw");
  await signUp(page, email);
  await signOut(page);
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/incorrect email or password/i)).toBeVisible();
});

test("two tabs refreshing together never log each other out; logout propagates", async ({
  context,
}) => {
  const a = await context.newPage();
  await signUp(a, uniqueEmail("tabs"));
  const b = await context.newPage();
  await b.goto("/generate");
  await expect(b.getByRole("button", { name: "Sign out" })).toBeVisible();

  // Both tabs bootstrap (a /refresh each) at the same instant, several times.
  for (let i = 0; i < 5; i++) {
    await Promise.all([a.reload(), b.reload()]);
    await expect(a.getByRole("button", { name: "Sign out" })).toBeVisible();
    await expect(b.getByRole("button", { name: "Sign out" })).toBeVisible();
  }

  await a.getByRole("button", { name: "Sign out" }).click();
  await expect(
    b.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Sign in" }),
  ).toBeVisible();
});

test("an expired access token mid-session recovers silently", async ({ page }) => {
  await signUp(page, uniqueEmail("expiry"));
  // Make the next authenticated call fail once with 401; the client must refresh and retry.
  let failed = false;
  await page.route("**/api/v1/voice/profiles", async (route) => {
    if (!failed) {
      failed = true;
      await route.fulfill({ status: 401, json: { detail: "Token expired" } });
    } else await route.continue();
  });
  await page.goto("/voices");
  await expect(page.getByText(/haven't created a voice yet/i)).toBeVisible();
  expect(failed).toBe(true);
  await expect(page).toHaveURL(/\/voices/);
});
