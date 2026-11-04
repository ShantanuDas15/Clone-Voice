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

/** Caption under the wave: "idle", "listening" for a moment after typing, "verified" after sign-in. */
export function VoiceState() {
  const label = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = subscribeVoice((_amount, surge) => {
      if (label.current) label.current.textContent = surge ? "verified" : "listening";
      clearTimeout(timer);
      timer = setTimeout(
        () => {
          if (label.current) label.current.textContent = "idle";
        },
        surge ? 1800 : 1200,
      );
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

/**
 * The headline's second line, typed out and swapped between phrases (owner-approved mock). The first
 * phrase is there in full from the start, so the page is complete at rest and under
 * `prefers-reduced-motion`, which never starts the typing. With one phrase it never moves at all.
 */
export function TypedLine({ phrases }: { phrases: readonly string[] }) {
  const line = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = line.current;
    if (!el || phrases.length < 2) return;
    if (!window.matchMedia?.("(prefers-reduced-motion: no-preference)").matches) return;
    let index = 0;
    let chars = (phrases[0] as string).length;
    let deleting = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const phrase = phrases[index] as string;
      let wait = deleting ? 28 : 55;
      if (!deleting && chars >= phrase.length) {
        deleting = true;
        wait = 2600;
      } else if (deleting) {
        chars = Math.max(0, chars - 2);
        if (chars === 0) {
          deleting = false;
          index = (index + 1) % phrases.length;
        }
      } else {
        chars += 1;
      }
      el.textContent = (phrases[index] as string).slice(0, chars) || "\u200b";
      timer = setTimeout(tick, wait);
    };
    timer = setTimeout(tick, 2600);
    return () => clearTimeout(timer);
  }, [phrases]);

  return (
    <span ref={line} className="vx-say block min-h-[1.1em] text-primary">
      {phrases[0]}
    </span>
  );
}
