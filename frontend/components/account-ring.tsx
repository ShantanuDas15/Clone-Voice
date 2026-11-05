"use client";

import { useEffect, useRef } from "react";

import { token } from "@/components/voice-canvas";
import { RING_BARS, initialsOf, nameSeed, ringAmplitude } from "@/lib/account-ring";
import { addEnergy, decayEnergy, subscribeVoice } from "@/lib/voice-energy";

/**
 * The person's own voiceprint ring (owner-approved mock, UX plan §12.28): 72 bars around their
 * initials, shaped from their name and swelling while they type it. It turns slowly and breathes on
 * its own unless motion is paused (a "Pause motion" control) or reduced, when it paints one still
 * frame. Drawn on a canvas, so no inline styles; the initials are decorative (the name is in the field).
 */
export function AccountRing({ name, paused }: { name: string; paused: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const hold = useRef(paused);
  const seed = useRef(nameSeed(name));
  useEffect(() => {
    hold.current = paused;
  }, [paused]);
  useEffect(() => {
    seed.current = nameSeed(name);
  }, [name]);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const side = 140;
    el.width = side * dpr;
    el.height = side * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    let energy = 0;
    let frame = 0;
    const started = performance.now();
    let frozen = 0;

    const paint = (now: number) => {
      const still = reduce || hold.current;
      if (!still) frozen = now - started;
      const t = frozen;
      const centre = side / 2;
      const inner = side * 0.33;
      const reach = side * 0.15;
      const lit = token("--primary");
      ctx.clearRect(0, 0, side, side);
      ctx.lineCap = "round";
      ctx.lineWidth = side * 0.016;
      ctx.strokeStyle = lit;
      for (let i = 0; i < RING_BARS; i++) {
        const angle = (i / RING_BARS) * Math.PI * 2 - Math.PI / 2 + t / 9000;
        const wobble = still ? 0 : Math.sin(t / 600 + i * 0.5) * 0.06;
        const h = reach * (ringAmplitude(i, seed.current) + wobble + energy * 0.5);
        ctx.globalAlpha = 0.45 + 0.55 * Math.min(1, h / (reach * 1.6));
        ctx.beginPath();
        ctx.moveTo(centre + Math.cos(angle) * inner, centre + Math.sin(angle) * inner);
        ctx.lineTo(centre + Math.cos(angle) * (inner + h), centre + Math.sin(angle) * (inner + h));
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      ctx.strokeStyle = token("--border");
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(centre, centre, inner - side * 0.035, 0, Math.PI * 2);
      ctx.stroke();
      energy = decayEnergy(energy);
    };

    const loop = (now: number) => {
      paint(now);
      frame = requestAnimationFrame(loop);
    };
    paint(started);
    const stop = subscribeVoice((amount) => {
      energy = addEnergy(energy, amount);
      if (reduce) paint(performance.now());
    });
    if (!reduce) frame = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(frame);
      stop();
    };
  }, []);

  return (
    <div className="ax-ring">
      <canvas ref={canvas} aria-hidden className="ax-ring-canvas" />
      <span aria-hidden className="ax-ring-initials" data-testid="ring-initials">
        {initialsOf(name)}
      </span>
    </div>
  );
}
