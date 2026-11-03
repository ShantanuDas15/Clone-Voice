/**
 * Geometry for the home page's decorative background (UX plan §12.19). Pure and deterministic, so
 * the server and the browser draw the same thing and tests can pin it. Nothing here is random.
 */

/** Horizontal distance between bar centres, in px; each bar is 4 px wide. */
export const BAR_PITCH = 12;

/** Bars in each side margin, enough to reach the edge of a 2560 px screen from the 1024 px column. */
export const SIDE_BAR_COUNT = 56;

export interface SideBar {
  /** Height as a percentage of the hero (10..88). */
  height: number;
  /** Opacity 0.12..0.5: strongest next to the content, fading toward the screen edge. */
  opacity: number;
}

/** The bars of one margin, ordered from the content column outward. */
export function sideBars(count: number = SIDE_BAR_COUNT): SideBar[] {
  return Array.from({ length: count }, (_, i) => {
    const height = 10 + Math.abs(Math.sin(i / 5.3) * 0.55 + Math.sin(i / 2.1 + 1) * 0.45) * 78;
    const opacity = Math.max(0.12, 0.5 - (i / count) * 0.38);
    return {
      height: Math.round(height),
      opacity: Number(opacity.toFixed(2)),
      delayMs: 200 + i * 4,
    };
  });
}

export interface Ribbon {
  /** SVG path over 2 x 1200 units; sliding it by exactly half its width loops seamlessly. */
  path: string;
  strokeWidth: number;
  opacity: number;
  /** Full Tailwind class, written out so the JIT sees it (see tailwind.config.ts), one speed and direction per ribbon. */
  animation: string;
}

const RIBBON_SPECS = [
  {
    periods: 1,
    amplitude: 52,
    wobble: 2,
    strokeWidth: 2,
    opacity: 0.5,
    animation: "motion-safe:animate-drift-slow",
  },
  {
    periods: 2,
    amplitude: 36,
    wobble: 3,
    strokeWidth: 1.5,
    opacity: 0.3,
    animation: "motion-safe:animate-drift-mid",
  },
  {
    periods: 3,
    amplitude: 26,
    wobble: 5,
    strokeWidth: 1.5,
    opacity: 0.18,
    animation: "motion-safe:animate-drift-long",
  },
] as const;

/** Width of the drawn path in SVG units; a whole number of periods fits in each half. */
export const RIBBON_WIDTH = 2400;

/** The three sine ribbons. Each spans two whole periods of 1200 units, so a -50% slide repeats exactly. */
export function ribbons(): Ribbon[] {
  return RIBBON_SPECS.map((s) => {
    const points: string[] = [];
    for (let i = 0; i <= 240; i++) {
      const x = (i / 240) * RIBBON_WIDTH;
      const phase = (x / 1200) * Math.PI * 2;
      const y =
        100 +
        Math.sin(phase * s.periods) *
          s.amplitude *
          (0.65 + 0.35 * Math.sin(phase * s.wobble + s.periods));
      points.push(`${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`);
    }
    return {
      path: points.join(" "),
      strokeWidth: s.strokeWidth,
      opacity: s.opacity,
      animation: s.animation,
    };
  });
}

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
