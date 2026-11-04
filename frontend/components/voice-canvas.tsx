"use client";

import { useEffect, useRef } from "react";

import {
  PRINT_BARS,
  addEnergy,
  printAmplitude,
  printLit,
  printSeed,
  subscribeVoice,
} from "@/lib/voice-energy";

/** The theme token `name` ("--primary") as an `hsl()` colour, optionally with an alpha. */
export function token(name: string, alpha?: number): string {
  const triplet = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return alpha === undefined ? `hsl(${triplet})` : `hsl(${triplet} / ${alpha})`;
}

/**
 * The hero "voiceprint" of the sign-in screen (owner-approved mock, UX plan §4.10): bars that ripple
 * gently on their own, a teal hot spot that sweeps along them, a swell while the user types and one
 * surge when sign-in works. Drawn on a canvas, so nothing here is an inline style. Under
 * `prefers-reduced-motion` it paints one still frame and never starts a loop. Decorative.
 */
export function VoiceCanvas({
  className,
  paused = false,
}: {
  className: string;
  /** Holds the endless ripple still (a "Pause motion" control); typing still swells the bars. */
  paused?: boolean;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const hold = useRef(paused);
  useEffect(() => {
    hold.current = paused;
  }, [paused]);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const seeds = Array.from({ length: PRINT_BARS }, (_, i) => printSeed(i));
    const started = performance.now();
    let energy = 0;
    let target = 0;
    let surge = 0;
    let width = 0;
    let height = 0;
    let frame = 0;
    let frozenAt = 1.2;

    const size = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const box = canvas.getBoundingClientRect();
      width = box.width;
      height = box.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (now: number) => {
      if (!width || !height) return; // hidden (the panel is for wide screens)
      const still = reduce || hold.current;
      const seconds = still ? frozenAt : (now - started) / 1000;
      if (!still) frozenAt = seconds;
      const accent = token("--primary");
      const idle = token("--line", 0.55);
      const step = width / PRINT_BARS;
      const bar = Math.max(2, step * 0.5);
      ctx.clearRect(0, 0, width, height);
      for (let i = 0; i < PRINT_BARS; i += 1) {
        const x = i * step + step / 2;
        const amp = printAmplitude(i, seconds, energy, surge, seeds[i] as number);
        const h = Math.max(4, amp * height);
        const lit = printLit(i / (PRINT_BARS - 1), seconds, energy, surge);
        const on = lit > 0.35;
        ctx.fillStyle = on ? accent : idle;
        ctx.shadowColor = accent;
        ctx.shadowBlur = on ? 14 * lit : 0;
        ctx.beginPath();
        ctx.roundRect(x - bar / 2, (height - h) / 2, bar, h, bar / 2);
        ctx.fill();
      }
      ctx.shadowBlur = 0;
    };

    const loop = (now: number) => {
      energy += (target - energy) * 0.08;
      target *= 0.97;
      surge *= 0.96;
      draw(now);
      frame = requestAnimationFrame(loop);
    };

    size();
    draw(performance.now());
    const resize = new ResizeObserver(() => {
      size();
      draw(performance.now());
    });
    resize.observe(canvas);
    const stop = subscribeVoice((amount, isSurge) => {
      if (reduce) return;
      if (isSurge) surge = 1;
      else target = addEnergy(target, amount);
    });
    if (!reduce) frame = requestAnimationFrame(loop);
    return () => {
      stop();
      resize.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  return <canvas ref={ref} aria-hidden data-testid="voice-wave" className={className} />;
}
