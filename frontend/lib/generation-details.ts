import type { Generation } from "@/lib/api/history";
import { EMOTIONS } from "@/lib/emotion";

const emotionLabel = (value: string): string =>
  EMOTIONS.find((e) => e.value === value)?.label ?? value;

/**
 * Short, plain facts about how a generation was made, for the history row: a backup engine, the
 * requested delivery and whether it took effect, per-sentence readings, sound tags that were left
 * out, and a seed. Empty when the row recorded nothing worth saying (old rows, plain requests).
 */
export function generationDetails(gen: Generation): string[] {
  const facts: string[] = [];
  if (gen.engine_fallback_from) {
    facts.push(`Made by the backup voice engine (${gen.engine_fallback_from} was unavailable)`);
  }
  if (gen.emotion && gen.emotion !== "auto") {
    const strength = gen.intensity != null ? ` at ${Math.round(gen.intensity * 100)}%` : "";
    const outcome = gen.style_applied === false ? ", not applied by this voice engine" : "";
    facts.push(`Delivery: ${emotionLabel(gen.emotion).split(" (")[0]}${strength}${outcome}`);
  }
  if (gen.emotions_used && gen.emotions_used.length > 0) {
    facts.push(`Sentence by sentence: ${gen.emotions_used.join(", ")}`);
  }
  if (gen.sound_tags_dropped && gen.sound_tags_dropped.length > 0) {
    const tags = gen.sound_tags_dropped.map((t) => `[${t}]`).join(" ");
    facts.push(`Left out, not supported by this voice engine: ${tags}`);
  }
  if (gen.seed != null) {
    facts.push(`Seed ${gen.seed}${gen.seed_applied === false ? " (not used by this engine)" : ""}`);
  }
  return facts;
}
