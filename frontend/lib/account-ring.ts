/** Bars in the account ring. */
export const RING_BARS = 72;

/** A stable number from a name, so a person always gets the same ring. */
export function nameSeed(name: string): number {
  let h = 2166136261;
  for (const ch of name) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Resting height of bar `i` (0.35..1) for a seed: three slow waves, so the ring has a shape of its own. */
export function ringAmplitude(i: number, seed: number): number {
  const wave =
    Math.sin(i * 0.61 + (seed % 97)) * 0.5 +
    Math.sin(i * 1.7 + (seed % 31)) * 0.3 +
    Math.sin(i * 0.23 + (seed % 13)) * 0.2;
  return 0.35 + 0.65 * Math.abs(wave);
}

/** One or two capital letters for the middle of the ring: first and last word of the name. */
export function initialsOf(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const first = words[0]?.[0] ?? "?";
  const last = words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}
