"use client";

import { useEffect, useRef } from "react";

import { panelBars } from "@/lib/auth-panel";
import { drawDelay } from "@/lib/home-backdrop";
import { addEnergy, decayEnergy, subscribeVoice, swollenHeight } from "@/lib/voice-energy";

/**
 * One row of voice bars, drawn once, left to right. It then rests until the user types in the form
 * beside it, when the bars swell for about a second and settle again (lib/voice-energy). Presentation
 * attributes and classes only, set with setAttribute: the site's Content-Security-Policy forbids
 * inline styles. `motion-safe` keeps the draw-in off, and the swell is skipped, under
 * `prefers-reduced-motion`. Decorative.
 */
export function Wave({ count, className }: { count: number; className: string }) {
  const bars = panelBars(count);
  const svg = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const el = svg.current;
    if (!el || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const rects = Array.from(el.querySelectorAll("rect"));
    const rest = panelBars(count).map((b) => b.height * 100);
    let energy = 0;
    let frame = 0;

    const paint = (ms: number) => {
      rects.forEach((rect, i) => {
        const height = 100 * swollenHeight((rest[i] as number) / 100, energy, i, ms);
        rect.setAttribute("height", String(height));
        rect.setAttribute("y", String(50 - height / 2));
      });
    };
    const tick = (ms: number) => {
      energy = decayEnergy(energy);
      paint(ms);
      frame = energy ? requestAnimationFrame(tick) : 0;
    };
    const stop = subscribeVoice((amount) => {
      energy = addEnergy(energy, amount);
      if (!frame) frame = requestAnimationFrame(tick);
    });
    return () => {
      stop();
      cancelAnimationFrame(frame);
    };
  }, [count]);

  return (
    <svg
      ref={svg}
      aria-hidden
      focusable="false"
      data-testid="voice-wave"
      viewBox={`0 0 ${count * 8} 100`}
      preserveAspectRatio="none"
      className={className}
    >
      {bars.map((bar, i) => {
        const h = bar.height * 100;
        return (
          <rect
            key={i}
            x={i * 8 + 1}
            y={50 - h / 2}
            width={6}
            height={h}
            rx={3}
            className={`origin-center [transform-box:fill-box] motion-safe:animate-bar-in ${drawDelay(i, 4)} ${
              bar.accent ? "fill-primary" : "fill-line/60"
            }`}
          />
        );
      })}
    </svg>
  );
}

/** Caption under the wave: "idle", or "listening" for a moment after the user types. */
export function VoiceState() {
  const label = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = subscribeVoice(() => {
      if (label.current) label.current.textContent = "listening";
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (label.current) label.current.textContent = "idle";
      }, 1200);
    });
    return () => {
      stop();
      clearTimeout(timer);
    };
  }, []);

  return (
    <span className="text-primary" ref={label}>
      idle
    </span>
  );
}
