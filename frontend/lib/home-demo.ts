/** Deterministic bar heights (0.1..1) for the small illustrations on the home page; no randomness. */
export function miniBars(count: number, seed: number): number[] {
  let s = seed * 977 + 13;
  return Array.from({ length: count }, (_, i) => {
    s = (s * 9301 + 49297) % 233280;
    const swell = 0.3 + 0.7 * Math.abs(Math.sin(i / 5 + seed) * 0.6 + Math.sin(i / 2.3 + 1) * 0.4);
    return Number(Math.max(0.1, Math.min(1, swell * (0.5 + (0.5 * s) / 233280))).toFixed(2));
  });
}
