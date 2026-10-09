import { expect, test } from "@playwright/test";

import { PASSWORD, emailedToken, signUp, uniqueEmail, verifyEmail } from "./helpers";

test("verification link from the real email clears the banner; reopening it still succeeds", async ({
  page,
}) => {
  const email = uniqueEmail("verify");
  await signUp(page, email);
  await expect(page.getByText(/verify your email address \(/i)).toBeVisible();

  await verifyEmail(page, email);
  await page.goto("/generate");
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  await expect(page.getByText(/verify your email address \(/i)).toHaveCount(0);

  // Idempotent: the same link opened again is still a success, and the fragment is stripped.
  const token = await emailedToken("verify-email", email);
  await page.goto(`/verify-email#token=${token}`);
  await expect(page.getByText(/verified/i).first()).toBeVisible();
  expect(new URL(page.url()).hash).toBe("");
});

test("forgot → reset changes the password, ends other sessions and reuse is refused", async ({
  browser,
}) => {
  const email = uniqueEmail("reset");
  const first = await browser.newContext();
  const tab = await first.newPage();
  await signUp(tab, email);

  const second = await browser.newContext();
  const page = await second.newPage();
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(page.getByText(/if an account exists/i)).toBeVisible();

  const token = await emailedToken("reset-password", email);
  await page.goto(`/reset-password#token=${token}`);
  expect(new URL(page.url()).hash).toBe("");
  await page.getByLabel("New password", { exact: true }).fill("brand-new-password-1");
  await page.getByLabel("Confirm new password").fill("brand-new-password-1");
  await page.getByRole("button", { name: /reset|set|save|change/i }).click();
  await expect(page.getByText(/password has been changed/i)).toBeVisible();
  await page.goto("/login");

  // The old session in the other browser is dead once its access token can no longer refresh.
  await tab.reload();
  await expect(tab.getByRole("link", { name: "Sign in" })).toBeVisible();

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/incorrect email or password/i)).toBeVisible();
  await page.getByLabel("Password", { exact: true }).fill("brand-new-password-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/generate/);

  // Token reuse → 400 "request a new link".
  await page.goto(`/reset-password#token=${token}`);
  await page.getByLabel("New password", { exact: true }).fill("another-password-22");
  await page.getByLabel("Confirm new password").fill("another-password-22");
  await page.getByRole("button", { name: /reset|set|save|change/i }).click();
  await expect(page.getByText(/new link|expired|invalid/i).first()).toBeVisible();
});

test("Google error codes on /login render copy, and an unknown code a generic message", async ({
  page,
}) => {
  await page.goto("/login?error=google_account_conflict");
  await expect(page.getByRole("alert").first()).toBeVisible();
  const known = await page.getByRole("alert").first().innerText();
  await page.goto("/login?error=something_new");
  await expect(page.getByRole("alert").first()).toBeVisible();
  expect(await page.getByRole("alert").first().innerText()).not.toBe(known);
});

test("signed-out visit to a token page with no fragment shows 'link incomplete'", async ({
  page,
}) => {
  await page.goto("/verify-email");
  await expect(page.getByText(/incomplete|missing|invalid/i).first()).toBeVisible();
});
