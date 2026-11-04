/**
 * The draw-in stagger shared by the sign-in panel's thin wave and the Take waveform (UX plan §12.19,
 * §12.24). The home page's old side bars and ribbons were replaced by the voiceprint stage
 * (lib/home-voiceprint.ts), so only the stagger is left here.
 */

/**
 * Stagger classes for the one-time bar draw-in: 16 steps of 12 ms after a 160 ms start. They are
 * written out in full because Tailwind only generates classes it can read, and a class is the only
 * way to delay a bar: the site's Content-Security-Policy forbids an inline `style` attribute.
 */
export const DRAW_DELAY_CLASSES = [
  "motion-safe:[animation-delay:160ms]",
  "motion-safe:[animation-delay:172ms]",
  "motion-safe:[animation-delay:184ms]",
  "motion-safe:[animation-delay:196ms]",
  "motion-safe:[animation-delay:208ms]",
  "motion-safe:[animation-delay:220ms]",
  "motion-safe:[animation-delay:232ms]",
  "motion-safe:[animation-delay:244ms]",
  "motion-safe:[animation-delay:256ms]",
  "motion-safe:[animation-delay:268ms]",
  "motion-safe:[animation-delay:280ms]",
  "motion-safe:[animation-delay:292ms]",
  "motion-safe:[animation-delay:304ms]",
  "motion-safe:[animation-delay:316ms]",
  "motion-safe:[animation-delay:328ms]",
  "motion-safe:[animation-delay:340ms]",
] as const;

/** The delay class for bar `index` of a row, `perStep` bars to a step; the last step holds the rest. */
export function drawDelay(index: number, perStep: number): string {
  const step = Math.min(DRAW_DELAY_CLASSES.length - 1, Math.floor(index / perStep));
  return DRAW_DELAY_CLASSES[step] as string;
}
