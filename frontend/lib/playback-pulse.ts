import type { Envelope } from "@/lib/audio-peaks";

/**
 * The playback pulse (UX plan §12.22, owner-chosen design "A. Pulse"): while a take plays, the bars
 * around the playhead rise and light up with how loud the take is at that moment. These are the pure
 * parts: reading the loudness curve, easing it, and working out one bar. The loop that applies them
 * is `hooks/use-playback-pulse.ts`.
 */

/** Bars either side of the playhead that can react. */
export const PULSE_REACH = 7;
/** How many bars the pulse layer holds: the playhead's bar and `PULSE_REACH` either side. */
export const PULSE_BARS = PULSE_REACH * 2 + 1;
/** Height of the take's box, in the waveform's own units (see `Waveform` in take.tsx). */
export const WAVE_HEIGHT = 48;
/** Tallest resting bar when the pulse is on (it is 44 otherwise): headroom for the bars to rise into. */
export const PULSE_REST_BAR = 28;
/** How far a bar at the playhead rises at full level, as a fraction of its resting height. */
export const PULSE_GAIN = 0.62;
/** Width of the bump: larger spreads the reaction over more bars. */
export const PULSE_FALLOFF = 22;
/** The loop draws about 30 frames a second, however fast the screen refreshes. */
export const PULSE_FRAME_MS = 32;

/** The take's loudness (0..1) at `seconds`, interpolated between the two nearest slices. */
export function levelAt(envelope: Envelope, seconds: number): number {
  const { levels, hop } = envelope;
  const last = levels.length - 1;
  if (last < 0 || !(seconds >= 0)) return 0;
  const position = seconds / hop;
  const from = Math.min(last, Math.floor(position));
  const to = Math.min(last, from + 1);
  const fraction = Math.min(1, position - from);
  return (levels[from] ?? 0) * (1 - fraction) + (levels[to] ?? 0) * fraction;
}

/** Ease the shown level toward the measured one: quick to rise, slower to fall, so it breathes. */
export function smoothLevel(previous: number, target: number): number {
  return previous + (target - previous) * (target > previous ? 0.55 : 0.14);
}

export interface PulseBar {
  /** Bar height in waveform units, never taller than the box. */
  height: number;
  /** 0 hides the bar; it is strongest at the playhead and when the take is loud. */
  opacity: number;
}

/**
 * One bar of the pulse. `peak` is the bar's own 0..1 height, `centre` the playhead in bar units
 * (progress times the number of bars), `level` the eased loudness. A bar further than `PULSE_REACH`
 * from the playhead is hidden, which is also what a take that is not playing looks like.
 */
export function pulseBar(index: number, centre: number, level: number, peak: number): PulseBar {
  const distance = Math.abs(index + 0.5 - centre);
  if (distance > PULSE_REACH) return { height: 0, opacity: 0 };
  const weight = Math.exp(-(distance * distance) / PULSE_FALLOFF);
  const rest = Math.max(2, peak * PULSE_REST_BAR);
  return {
    height: Math.min(WAVE_HEIGHT, rest * (1 + level * PULSE_GAIN * weight)),
    opacity: (0.25 + 0.75 * weight) * (0.35 + 0.65 * level),
  };
}
