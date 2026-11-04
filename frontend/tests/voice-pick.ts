import { screen, waitFor } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { expect } from "vitest";

/** The voice radio for a profile id (the Generate screen draws voices as a radio group of cards). */
export async function voiceRadio(id: string): Promise<HTMLInputElement> {
  return waitFor(() => {
    const el = document.querySelector<HTMLInputElement>(`input[name="tts-voice"][value="${id}"]`);
    expect(el).not.toBeNull();
    return el as HTMLInputElement;
  });
}

/** Choose a voice by profile id, once the list has loaded. */
export async function pickVoice(user: UserEvent, id: string): Promise<void> {
  const radio = await voiceRadio(id);
  await waitFor(() => expect(radio).toBeEnabled());
  await user.click(radio);
}

/** Choose a delivery by its value ("happy", "sad", ...). */
export async function chooseDelivery(user: UserEvent, value: string): Promise<void> {
  const radio = await waitFor(() => {
    const el = document.querySelector<HTMLInputElement>(
      `input[name="tts-emotion"][value="${value}"]`,
    );
    expect(el).not.toBeNull();
    return el as HTMLInputElement;
  });
  await user.click(radio);
}

/** Resolves once the voice list has loaded and any voice cards are on screen. */
export async function voicesLoaded(): Promise<void> {
  await screen.findByRole("radiogroup", { name: "Voice" });
}
