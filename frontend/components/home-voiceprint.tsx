"use client";

import { useEffect, useRef } from "react";

import { token } from "@/components/voice-canvas";
import { HOME_BARS, barHeight, peakAt, pointerNear, sweepNear } from "@/lib/home-voiceprint";

/**
 * The home page's stage (owner-approved mock, UX plan §4.10 and §12.25): a full-width row of bars in
 * the shape of the sample clip, gently rippling, swelling around the pointer, and lit by a sweep
 * while the clip plays. Drawn on a canvas, so no inline style. It stops drawing while off screen,
 * holds still when `paused` (the visitor's Pause motion control) and under `prefers-reduced-motion`,
 * which paints one still frame. Decorative.
 */
export function HomeVoiceprint({
  peaks,
  live,
  progress,
  paused,
}: {
  peaks: readonly number[];
  live: boolean;
  progress: number;
  paused: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const input = useRef({ live, progress, paused });
  const repaint = useRef<() => void>(() => {});

  useEffect(() => {
    input.current = { live, progress, paused };
    repaint.current();
  }, [live, progress, paused]);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const started = performance.now();
    let width = 0;
    let height = 0;
    let pointer = -1;
    let visible = true;
    let frozenAt = 1.2;
    let frame = 0;

    const size = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const box = el.getBoundingClientRect();
      width = box.width;
      height = box.height;
      el.width = Math.round(width * dpr);
      el.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (now: number) => {
      if (!width || !height) return;
      const { live: on, progress: p, paused: hold } = input.current;
      const still = reduce || hold;
      const seconds = still ? frozenAt : (now - started) / 1000;
      if (!still) frozenAt = seconds;
      const accent = token("--primary");
      const idle = token("--line");
      const step = width / HOME_BARS;
      const bar = Math.max(2.5, step * 0.52);
      ctx.clearRect(0, 0, width, height);
      for (let i = 0; i < HOME_BARS; i += 1) {
        const u = i / (HOME_BARS - 1);
        const x = i * step + step / 2;
        const near = pointerNear(x, pointer, width);
        const sweep = sweepNear(u, p, on);
        const h = Math.max(4, barHeight(i, peakAt(peaks, u), seconds, near, sweep) * height);
        const played = on && u <= p;
        const lit = near > 0.35 || sweep > 0.3 || played;
        ctx.globalAlpha = lit ? 1 : 0.5;
        ctx.fillStyle = lit ? accent : idle;
        ctx.shadowColor = accent;
        ctx.shadowBlur = lit ? 12 * Math.max(near, sweep, played ? 0.5 : 0) : 0;
        ctx.beginPath();
        ctx.roundRect(x - bar / 2, (height - h) / 2, bar, h, bar / 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;
    };

    const loop = (now: number) => {
      if (visible) draw(now);
      frame = requestAnimationFrame(loop);
    };

    size();
    draw(performance.now());
    repaint.current = () => draw(performance.now());
    const resize = new ResizeObserver(() => {
      size();
      draw(performance.now());
    });
    resize.observe(el);
    const watch =
      typeof IntersectionObserver === "undefined"
        ? null
        : new IntersectionObserver((entries) => {
            const last = entries[entries.length - 1];
            if (last) visible = last.isIntersecting;
          });
    watch?.observe(el);
    const move = (e: PointerEvent) => {
      pointer = e.clientX - el.getBoundingClientRect().left;
      if (reduce) draw(performance.now());
    };
    const leave = () => {
      pointer = -1;
      if (reduce) draw(performance.now());
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerleave", leave);
    if (!reduce) frame = requestAnimationFrame(loop);
    return () => {
      repaint.current = () => {};
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerleave", leave);
      resize.disconnect();
      watch?.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [peaks]);

  return (
    <canvas
      ref={canvas}
      data-testid="home-voiceprint"
      data-live={live}
      role="img"
      aria-label="A waveform of the sample voice. Move the pointer over it, or play the sample."
      className="hx-canvas"
    />
  );
}
