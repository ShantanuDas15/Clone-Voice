import "@/lib/zod-setup";
import { z } from "zod";

/** Mirrors `SynthesizeRequest.text`: 1-500 characters (the character-set check stays server-side). */
export const TEXT_MAX = 500;

export const synthesisTextSchema = z
  .string()
  .trim()
  .min(1, "Enter some text to speak")
  .max(TEXT_MAX, `Text must be at most ${TEXT_MAX} characters`);

/**
 * Light pre-warning only (R6): emoji and pictographs are never in the SV2TTS symbol set. Everything
 * else is left to the server's 422 message, whose rules depend on `unidecode` behaviour.
 */
export function hasLikelyUnsupportedChars(text: string): boolean {
  return /\p{Extended_Pictographic}/u.test(text);
}
