/**
 * Geometry for the sign-in and sign-up voice panel (UX plan §12.24). Pure and deterministic, so the
 * server and the browser draw the same thing and tests can pin it. Nothing here is random.
 */

export interface PanelBar {
  /** Height as a fraction of the box, 0.05..1. */
  height: number;
  /** True for the few bars around the highlight, which take the accent colour. */
  accent: boolean;
}

/** Where the highlighted run sits along the row, as a fraction of its length. */
const HIGHLIGHT_AT = 0.38;
/** Half-width of the highlighted run, in bars. */
const HIGHLIGHT_REACH = 4.5;

/** A voice-shaped row of `count` bars: a slow swell with a faster ripple on top. */
export function panelBars(count: number): PanelBar[] {
  let seed = 11;
  return Array.from({ length: count }, (_, i) => {
    seed = (seed * 9301 + 49297) % 233280;
    const swell = 0.3 + 0.7 * Math.abs(Math.sin(i / 7.5) * 0.6 + Math.sin(i / 3.1 + 1) * 0.4);
    const height = Math.max(0.05, Math.min(1, swell * (0.45 + (0.55 * seed) / 233280)));
    return {
      height: Number(height.toFixed(2)),
      accent: Math.abs(i - count * HIGHLIGHT_AT) < HIGHLIGHT_REACH,
    };
  });
}
