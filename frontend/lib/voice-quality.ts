import type { VoiceSample } from "@/lib/api/voice";

export type OverallQuality = "good" | "fair" | "poor";

const ORDER: readonly OverallQuality[] = ["poor", "fair", "good"];

/** Chip wording for each overall rating. */
export const QUALITY_LABEL: Readonly<Record<OverallQuality, string>> = {
  good: "Good quality",
  fair: "Fair quality",
  poor: "Poor quality",
};

/**
 * One rating for a whole voice: its worst clip, because one bad recording drags the cloned voice
 * down (the same rule `voiceAdvice` uses to say a recording needs attention). Null when no clip
 * has a known rating, e.g. a voice made before quality reports existed.
 */
export function overallQuality(samples: readonly VoiceSample[]): OverallQuality | null {
  let worst = -1;
  let seen = false;
  for (const sample of samples) {
    const index = ORDER.indexOf(sample.quality?.rating as OverallQuality);
    if (index === -1) continue;
    worst = seen ? Math.min(worst, index) : index;
    seen = true;
  }
  return seen ? (ORDER[worst] ?? null) : null;
}
