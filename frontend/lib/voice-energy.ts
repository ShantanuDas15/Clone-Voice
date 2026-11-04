/**
 * A tiny pub/sub that lets a form tell the voice panel beside it that the user is typing. The panel
 * answers with a short swell of its bars; nothing here runs on its own (UX plan §4.10: motion only
 * in response to the user, and it always settles).
 */

type Listener = (amount: number) => void;

const listeners = new Set<Listener>();

/** Tell every listening wave that the user just did something (typed, focused a field, submitted). */
export function pulseVoice(amount = 0.5): void {
  listeners.forEach((listener) => listener(amount));
}

/** Listen for pulses; returns the function that stops listening. */
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

/** Energy left after one frame; ~1 s from full to rest at 60 fps, far under WCAG 2.2.2's five seconds. */
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
