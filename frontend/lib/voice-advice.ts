import type { VoiceSample } from "@/lib/api/voice";

/** Clips at which a voice stops being nudged for more (S3.5b: four averaged clips cut garbled speech). */
export const RECOMMENDED_CLIPS = 3;

/** Shown for a voice built from only one or two clips; the measured gain is in SPEECH_QUALITY_STUDY.md. */
export const FEW_CLIPS_NUDGE =
  "Add more clips of the same person: voices made from several clips have fewer garbled or missing words.";

/**
 * One line that tells the owner of a voice whether its clips need attention, so the advice does not
 * hide behind a collapsed panel. Null when every clip is fine (or nothing is known about them).
 */
export function voiceAdvice(samples: readonly VoiceSample[]): string | null {
  const parts: string[] = [];
  const odd = samples.filter((s) => s.mismatch).map((s) => s.position + 1);
  if (odd.length === 1) parts.push(`Clip ${odd[0]} may be a different speaker.`);
  else if (odd.length > 1) parts.push(`Clips ${odd.join(", ")} may be different speakers.`);
  const ratings = samples.map((s) => s.quality?.rating);
  if (ratings.includes("poor")) parts.push("A recording is poor.");
  else if (ratings.includes("fair")) parts.push("A recording could be cleaner.");
  if (samples.length > 0 && samples.length < RECOMMENDED_CLIPS) parts.push(FEW_CLIPS_NUDGE);
  return parts.length > 0 ? parts.join(" ") : null;
}
