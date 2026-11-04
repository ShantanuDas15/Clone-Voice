/**
 * Geometry of the home page's voiceprint stage (owner-approved mock, UX plan §12.25). Pure, so tests
 * can pin it. The bars follow the real shape of the sample clip; the pointer and the playhead only
 * add to them.
 */

/** Bars across the full-width stage. */
export const HOME_BARS = 96;

/** The clip's peak (0..1) at position `u` (0..1); 0.5 when there are none. */
export function peakAt(peaks: readonly number[], u: number): number {
  if (peaks.length === 0) return 0.5;
  const p =
    peaks[Math.min(peaks.length - 1, Math.max(0, Math.round(u * (peaks.length - 1))))] ?? 50;
  return Math.min(100, Math.max(0, p)) / 100;
}

/** How strongly the pointer at `px` swells a bar at `x`, 0..1 (a bell about 7 % of the width wide). */
export function pointerNear(x: number, px: number, width: number): number {
  if (px < 0 || width <= 0) return 0;
  return Math.exp(-(((x - px) / (width * 0.07)) ** 2));
}

/** How strongly the playhead at `progress` lights a bar at `u`, 0..1; 0 when nothing plays. */
export function sweepNear(u: number, progress: number, live: boolean): number {
  return live ? Math.exp(-(((u - progress) / 0.045) ** 2)) : 0;
}

/** Height of bar `i` as a fraction of the stage (0.04..0.96), at `seconds`. */
export function barHeight(
  i: number,
  peak: number,
  seconds: number,
  pointer: number,
  sweep: number,
): number {
  const ripple = 0.06 * Math.sin(seconds * 1.5 + i * 0.45);
  return Math.min(0.96, Math.max(0.04, 0.1 + 0.62 * peak + ripple + pointer * 0.3 + sweep * 0.3));
}
