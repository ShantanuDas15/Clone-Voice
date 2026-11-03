"use client";

import { useEffect, useRef, useState } from "react";

import { BAR_PITCH, RIBBON_WIDTH, drawDelay, ribbons, sideBars } from "@/lib/home-backdrop";

const BARS = sideBars();
const RIBBONS = ribbons();

/**
 * One margin of faint voice bars, from the content column outward. Shown only where the page leaves
 * room either side of its 64 rem column (about 1200 px and up). One SVG per margin, drawn with
 * presentation attributes only: the site's Content-Security-Policy forbids inline `style` attributes,
 * so no height, opacity or delay can live in one. Each bar draws once, rippling outward from the content, then rests.
 */
function SideBars({ side }: { side: "left" | "right" }) {
  const width = BARS.length * BAR_PITCH;
  return (
    <div
      className={`absolute bottom-0 top-0 hidden w-[calc(50vw-33rem)] overflow-hidden min-[1200px]:block ${
        side === "left" ? "right-[calc(50%+33rem)]" : "left-[calc(50%+33rem)]"
      }`}
    >
      <svg
        data-testid="home-bars"
        viewBox={`0 0 ${width} 100`}
        preserveAspectRatio="none"
        focusable="false"
        className={`absolute top-0 h-full ${side === "left" ? "right-0" : "left-0"}`}
        width={width}
      >
        {BARS.map((bar, i) => {
          // Bar 0 touches the content column: the right end of the left margin, the left end of the right.
          const x = side === "left" ? width - 2 - i * BAR_PITCH : 2 + i * BAR_PITCH;
          return (
            <line
              key={i}
              x1={x}
              x2={x}
              y1={50 - bar.height / 2}
              y2={50 + bar.height / 2}
              className={`origin-center stroke-line [transform-box:fill-box] motion-safe:animate-bar-in ${drawDelay(i, 4)}`}
              strokeWidth={4}
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
              opacity={bar.opacity}
            />
          );
        })}
      </svg>
    </div>
  );
}

/**
 * The home page's decorative background: voice bars in the side margins and three slow sine ribbons
 * in a text-free band at the foot of the hero. Everything is `aria-hidden` and ignores the pointer.
 *
 * Motion (§4.10 exception for this page, §12.19): the ribbons drift (transform only), swell while
 * the sample plays (`live`), pause whenever the band is off screen, and do not move at all under
 * `prefers-reduced-motion`. No colour is invented: bars use `line`, ribbons use `primary`.
 */
export function HomeBackdrop({ live }: { live: boolean }) {
  const band = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);

  // Stop the drift while the band is out of view; without IntersectionObserver it just keeps running.
  useEffect(() => {
    const el = band.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      const last = entries[entries.length - 1];
      if (last) setPaused(!last.isIntersecting);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      aria-hidden
      data-testid="home-backdrop"
      className="pointer-events-none absolute inset-0 -z-10"
    >
      <SideBars side="left" />
      <SideBars side="right" />
      <div
        ref={band}
        data-testid="home-wave"
        data-live={live}
        data-paused={paused}
        className="home-wave absolute bottom-0 left-1/2 h-[150px] w-screen -translate-x-1/2 overflow-hidden"
      >
        {RIBBONS.map((r, i) => (
          <div
            key={i}
            className={`absolute left-0 top-1/2 -mt-[75px] h-[150px] w-full transition-transform duration-base ${
              live ? "scale-y-[1.25]" : "scale-y-[0.7]"
            }`}
          >
            <svg
              viewBox={`0 0 ${RIBBON_WIDTH} 200`}
              preserveAspectRatio="none"
              focusable="false"
              className={`absolute left-0 top-0 h-full w-[200%] overflow-visible ${r.animation}`}
            >
              <path
                d={r.path}
                className="fill-none stroke-primary"
                strokeWidth={r.strokeWidth}
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
                opacity={r.opacity}
              />
            </svg>
          </div>
        ))}
      </div>
    </div>
  );
}
