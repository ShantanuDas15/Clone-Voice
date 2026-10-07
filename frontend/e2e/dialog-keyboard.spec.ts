import { expect, test } from "@playwright/test";

import { createVoice, signUpVerified } from "./helpers";

test("both confirmation dialogs are keyboard-operable modals in a real browser", async ({
  page,
}) => {
  test.setTimeout(180_000);
  await signUpVerified(page, "dlgkey");
  await createVoice(page, "Keyboard voice");

  // Delete-voice: focus lands on the confirm button, Tab cycles, Escape returns to the opener.
  const rowDelete = page.getByRole("button", { name: "Delete Keyboard voice" });
  await rowDelete.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("alertdialog");
  await expect(page.getByRole("button", { name: "Delete voice" })).toBeFocused();
  for (let i = 0; i < 6; i += 1) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(rowDelete).toBeFocused();

  // Delete-account: first field focused, focus never leaves, Escape restores the trigger.
  const trigger = page.getByRole("button", { name: /delete my account/i });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByLabel(/type delete/i)).toBeFocused();
  for (let i = 0; i < 8; i += 1) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});
