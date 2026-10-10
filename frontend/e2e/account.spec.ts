import { expect, test } from "@playwright/test";

import { PASSWORD, signUp, uniqueEmail } from "./helpers";

test("rename, then delete the account: signed out and login no longer works", async ({ page }) => {
  const email = uniqueEmail("acct");
  await signUp(page, email);
  await page.goto("/account");

  await page.getByLabel("Display name").fill("Renamed User");
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByText("Renamed User").first()).toBeVisible();
  // The toast library is fetched on the first toast (FE-UX36); it must still appear.
  await expect(page.getByText("Name updated.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Display name")).toHaveValue("Renamed User");

  await page.getByRole("button", { name: /delete my account/i }).click();
  await page.getByLabel(/type delete/i).fill("DELETE");
  await page.getByLabel("Password", { exact: true }).fill("wrong-password-xx");
  await page.getByRole("button", { name: "Delete account" }).click();
  await expect(page.getByText("That password is incorrect.")).toBeVisible();

  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Delete account" }).click();
  await expect(page).toHaveURL(/^https?:\/\/localhost:\d+\/$/);

  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(/incorrect email or password/i)).toBeVisible();
});
