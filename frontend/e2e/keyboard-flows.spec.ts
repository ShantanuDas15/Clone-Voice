import { type Locator, type Page, expect, test } from "@playwright/test";

import { PASSWORD, SAMPLE_WAV, signUp, uniqueEmail, verifyEmail } from "./helpers";

/**
 * Keyboard-only completion of every flow in the UX plan's Definition of Done (item 2): the only
 * input devices used are `keyboard.press` and `keyboard.type`. Nothing is clicked or filled.
 */

/**
 * Put the sequential-focus start point back at the top of the document, as after a fresh page
 * load. Firefox otherwise keeps it where the removed control used to be after a client-side
 * navigation, so Tab would start mid-page.
 */
async function focusTop(page: Page): Promise<void> {
  await page.evaluate(() => {
    (document.activeElement as HTMLElement | null)?.blur();
    document.body.tabIndex = -1;
    document.body.focus();
    document.body.removeAttribute("tabindex");
  });
}

/** Tab until `target` has focus, failing if it is not reached in `max` presses. */
async function tabTo(page: Page, target: Locator, max = 60): Promise<void> {
  for (let i = 0; i < max; i += 1) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  await expect(target).toBeFocused();
}

/** The focused element must show an outline (the `focus-visible` ring), not rely on defaults. */
async function expectFocusRing(page: Page): Promise<void> {
  const ring = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return null;
    const s = getComputedStyle(el);
    return { style: s.outlineStyle, width: s.outlineWidth };
  });
  expect(ring, "an element has focus").not.toBeNull();
  expect(ring?.style).not.toBe("none");
  expect(ring?.width).not.toBe("0px");
}

/** Focus `target` by Tab, check its ring, optionally type, and leave it focused. */
async function reach(page: Page, target: Locator, text?: string): Promise<void> {
  await tabTo(page, target);
  await expectFocusRing(page);
  if (text !== undefined) await page.keyboard.type(text);
}

async function pressOn(page: Page, target: Locator, key = "Enter"): Promise<void> {
  await tabTo(page, target);
  await expectFocusRing(page);
  await page.keyboard.press(key);
}

test("sign up, sign out and sign in again with the keyboard alone", async ({ page }) => {
  const email = uniqueEmail("kbauth");
  await page.goto("/signup");
  await reach(page, page.getByLabel("Name"), "Keyboard User");
  await reach(page, page.getByLabel("Email"), email);
  await reach(page, page.getByLabel("Password", { exact: true }), PASSWORD);
  await pressOn(page, page.getByRole("button", { name: "Create account" }));
  await expect(page).toHaveURL(/\/generate/);

  // The current page is exposed to assistive technology and reachable in the nav.
  const nav = page.getByRole("navigation", { name: "Primary" });
  await focusTop(page);
  await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
  for (const name of ["Voices", "History", "Account"]) {
    await tabTo(page, nav.getByRole("link", { name }).first());
    await expectFocusRing(page);
  }

  await focusTop(page);
  // Following a nav link lands on the new page's heading, and Tab continues from there.
  await pressOn(page, nav.getByRole("link", { name: "Voices" }).first());
  await expect(page).toHaveURL(/\/voices/);
  await expect(page.getByRole("heading", { level: 1, name: "Voices" })).toBeFocused();
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => !!document.activeElement?.closest("main"))).toBe(true);

  await focusTop(page);
  await pressOn(page, page.getByRole("button", { name: "Sign out" }), "Space");
  await expect(page).toHaveURL(/\/$/);

  await page.goto("/login");
  await reach(page, page.getByLabel("Email"), email);
  await reach(page, page.getByLabel("Password", { exact: true }), PASSWORD);
  await pressOn(page, page.getByRole("button", { name: "Sign in" }));
  await expect(page).toHaveURL(/\/generate/);
});

test("create a voice by file, generate, replay from history, delete it, then delete the account", async ({
  page,
}) => {
  test.setTimeout(420_000);
  const email = uniqueEmail("kbflow");
  await signUp(page, email);
  await verifyEmail(page, email);

  // Create a voice: name, the real file chooser opened from the keyboard, consent, submit.
  await page.goto("/voices");
  await reach(page, page.getByLabel("Voice name"), "Keyboard voice");
  await tabTo(page, page.locator("input[type=file]"));
  const chooser = page.waitForEvent("filechooser");
  await page.keyboard.press("Space");
  await (await chooser).setFiles(SAMPLE_WAV);
  await expect(page.getByTestId("selected-file")).toBeVisible();
  await tabTo(page, page.getByRole("checkbox", { name: /right to use this voice/i }));
  await expectFocusRing(page);
  await page.keyboard.press("Space");
  await pressOn(page, page.getByRole("button", { name: "Create voice" }));
  await expect(page.getByText("Voice “Keyboard voice” created.")).toBeVisible({
    timeout: 120_000,
  });

  // Generate: pick the voice with the keyboard, type the text, submit.
  await page.goto("/generate");
  const select = page.getByLabel("Voice");
  await expect(select).toBeEnabled();
  await tabTo(page, select);
  await expectFocusRing(page);
  await page.keyboard.type("Keyboard"); // type-ahead selects the matching option
  await expect(select).toHaveValue(/.+/);
  await reach(page, page.getByLabel("Text"), "Hello from the keyboard.");
  await pressOn(page, page.getByRole("button", { name: "Generate speech" }));
  await expect(page.locator('audio[aria-label="Generated speech"]')).toBeAttached({
    timeout: 300_000,
  });

  // History: replay the past generation with the keyboard.
  await page.goto("/history");
  await expect(page.getByText("Hello from the keyboard.")).toBeVisible();
  await pressOn(page, page.getByRole("button", { name: "Play", exact: true }));
  await expect(page.locator('audio[aria-label^="Generated audio from"]')).toBeAttached();

  // Delete the voice: open the dialog and confirm, all by key.
  await page.goto("/voices");
  await pressOn(page, page.getByRole("button", { name: "Delete Keyboard voice" }));
  await expect(page.getByRole("button", { name: "Delete voice" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Delete Keyboard voice" })).toHaveCount(0);

  // Delete the account: confirmation text, password, submit.
  await page.goto("/account");
  await pressOn(page, page.getByRole("button", { name: /delete my account/i }));
  await expect(page.getByLabel(/type delete/i)).toBeFocused();
  await page.keyboard.type("DELETE");
  await reach(page, page.getByLabel("Password", { exact: true }), PASSWORD);
  await pressOn(page, page.getByRole("button", { name: "Delete account" }));
  await expect(page).toHaveURL(/^https?:\/\/localhost:\d+\/$/);
});

test("record a voice sample with the keyboard alone (start, stop, preview)", async ({ page }) => {
  const email = uniqueEmail("kbrec");
  await signUp(page, email);
  await page.goto("/voices");
  await expect(page.getByLabel("Voice name")).toBeVisible();
  test.skip(
    (await page.getByRole("radio", { name: "Record now" }).count()) === 0,
    "this browser records in a format the server does not accept (WebKit); upload is offered instead",
  );

  // The mode group is one tab stop; arrows move the choice (FE-UX13).
  await tabTo(page, page.getByRole("radio", { checked: true }));
  await expectFocusRing(page);
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "Record now" })).toBeChecked();

  await pressOn(page, page.getByRole("button", { name: "Start recording" }));
  const stop = page.getByRole("button", { name: "Stop recording" });
  await expect(stop).toBeEnabled({ timeout: 15_000 }); // after the 5 s minimum
  await tabTo(page, stop);
  await expectFocusRing(page);
  await page.keyboard.press("Space");
  await expect(page.locator('audio[aria-label="Recording preview"]')).toBeAttached();
});
