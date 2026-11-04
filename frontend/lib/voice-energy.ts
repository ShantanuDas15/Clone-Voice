/**
 * A tiny pub/sub that lets a form tell the voice panel beside it what the user is doing. The panel
 * answers: a swell while they type, one bigger surge when they sign in. Nothing here runs on its own.
 */

/** `surge` is true for the one-off sign-in moment, false for ordinary typing and focus. */
type Listener = (amount: number, surge: boolean) => void;

const listeners = new Set<Listener>();

/** Tell every listening wave that the user just did something (typed, focused a field, submitted). */
export function pulseVoice(amount = 0.5): void {
  listeners.forEach((listener) => listener(amount, false));
}

/** Tell every listening wave that sign-in worked: the one big surge. */
export function surgeVoice(): void {
  listeners.forEach((listener) => listener(1, true));
}

/** Listen for pulses and surges; returns the function that stops listening. */
export function subscribeVoice(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Add `amount` to the current energy, capped at 1. */
export function addEnergy(energy: number, amount: number): number {
  return Math.min(1, Math.max(0, energy + amount));
}

/** Energy left after one frame; ~1 s from full to rest at 60 fps. */
export function decayEnergy(energy: number): number {
  const next = energy * 0.94;
  return next < 0.02 ? 0 : next;
}

/**
 * Height of one bar (a fraction of the box) at a given energy: its resting height, swollen by up to
 * 90 % with a per-bar ripple, never past the box.
 */
export function swollenHeight(rest: number, energy: number, index: number, ms: number): number {
  const ripple = 0.5 + 0.5 * Math.sin(ms / 110 + index * 0.9);
  return Math.min(1, rest * (1 + energy * ripple * 0.9));
}

/** Bars in the hero voiceprint. */
export const PRINT_BARS = 72;

/** One bar of the hero voiceprint, as a fraction of the box height, at `seconds` and the given energy. */
export function printAmplitude(
  i: number,
  seconds: number,
  energy: number,
  surge: number,
  seed: number,
): number {
  const u = i / (PRINT_BARS - 1);
  const envelope = Math.exp(-(((u - 0.5) / 0.3) ** 2)); // taller in the middle
  const wobble = 0.5 + 0.5 * Math.sin(seconds * 1.6 + i * 0.5) * Math.sin(seconds * 0.9 + i * 0.21);
  const amp =
    0.12 +
    0.28 * envelope * wobble +
    0.1 * seed +
    energy * (0.35 * envelope + 0.25 * seed * (0.6 + 0.4 * Math.sin(seconds * 9 + i))) +
    surge * 0.45 * (0.5 + 0.5 * Math.sin(seconds * 14 - i * 0.4));
  return Math.min(amp, 0.96);
}

/** How much a bar at position `u` (0..1) is lit by the sweeping hot spot, the energy and the surge. */
export function printLit(u: number, seconds: number, energy: number, surge: number): number {
  const focus = 0.5 + 0.28 * Math.sin(seconds * 0.5); // the hot spot sweeps along the line
  const near = Math.exp(-(((u - focus) / 0.1) ** 2));
  return Math.min(1, near * (0.6 + energy) + surge);
}

/** Deterministic 0..1 per-bar seed, so the server and browser agree and tests can pin it. */
export function printSeed(i: number): number {
  return Math.abs((Math.sin(i * 12.9898) * 43758.5453) % 1);
}
