import { type Page, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

export const PASSWORD = "e2e-password-123";
export const SAMPLE_WAV = path.resolve(__dirname, "../../backend/tests/fixtures/sample_5sec.wav");

let counter = 0;
/** A unique, throwaway address per test so runs never collide. */
export function uniqueEmail(tag: string): string {
  return `e2e-${tag}-${Date.now()}-${counter++}@example.com`;
}

/** Decode a quoted-printable body (the console email backend prints the raw MIME message). */
export function decodeQuotedPrintable(input: string): string {
  return input
    .replace(/=\r?\n/g, "")
    .replace(/=([0-9A-F]{2})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)));
}

/** Newest emailed link of `kind` for `email`, scraped from the backend's console-email log. */
export async function emailedToken(
  kind: "verify-email" | "reset-password",
  email: string,
): Promise<string> {
  const logPath = process.env.E2E_BACKEND_LOG;
  if (!logPath)
    throw new Error("Set E2E_BACKEND_LOG to the backend's log file (see e2e/README.md)");
  const pattern = new RegExp(`/${kind}#token=([A-Za-z0-9._~-]+)`);
  for (let attempt = 0; attempt < 40; attempt++) {
    const lines = readFileSync(logPath, "utf8").split("\n").reverse();
    for (const line of lines) {
      if (!line.includes("EMAIL (console backend)")) continue;
      const message = (JSON.parse(line) as { message?: string }).message ?? "";
      if (!message.includes(email)) continue;
      const match = pattern.exec(decodeQuotedPrintable(message));
      if (match) return match[1] as string;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`No ${kind} email for ${email} found in ${logPath}`);
}

export async function signUp(page: Page, email: string, name = "E2E User"): Promise<void> {
  await page.goto("/signup");
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/generate/);
}

export async function verifyEmail(page: Page, email: string): Promise<void> {
  const token = await emailedToken("verify-email", email);
  await page.goto(`/verify-email#token=${token}`);
  await expect(page.getByText(/verified/i).first()).toBeVisible();
}

/** Sign up and verify, leaving the user signed in on the profile page. */
export async function signUpVerified(page: Page, tag: string): Promise<string> {
  const email = uniqueEmail(tag);
  await signUp(page, email);
  await verifyEmail(page, email);
  await page.goto("/voices");
  await expect(page.getByRole("heading", { name: "Create a voice" })).toBeVisible();
  return email;
}

/** Create a voice profile from the repo's sample WAV through the real upload form. */
export async function createVoice(page: Page, name = "E2E voice"): Promise<void> {
  await page.goto("/voices");
  await page.getByLabel("Voice name").fill(name);
  await page.locator("input[type=file]").setInputFiles(SAMPLE_WAV);
  await page.getByRole("checkbox", { name: /right to use this voice/i }).check();
  await page.getByRole("button", { name: "Create voice" }).click();
  await expect(page.getByText(`Voice “${name}” created.`)).toBeVisible({ timeout: 120_000 });
}

/**
 * Sign out and wait until the app has finished its own navigation home. A `goto` issued earlier
 * collides with that navigation, which Firefox reports as `NS_BINDING_ABORTED`.
 */
export async function signOut(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(
    page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Sign in" }),
  ).toBeVisible();
}
