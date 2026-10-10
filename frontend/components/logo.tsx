import type { SVGProps } from "react";
import { BRAND_NAME } from "@/lib/brand";

/**
 * The CloneVoice mark: a voice waveform that rises and then fades out, the fading bars being the
 * "clone" echoing the original. Drawn with `currentColor` so it follows the surrounding text colour
 * (the header uses the `primary` token). Decorative: the wordmark beside it carries the name.
 */
const BARS = [
  { x: 3, h: 8, o: 1 },
  { x: 8.5, h: 16, o: 1 },
  { x: 14, h: 26, o: 1 },
  { x: 19.5, h: 16, o: 0.55 },
  { x: 25, h: 8, o: 0.3 },
] as const;

export function LogoMark(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true" focusable="false" {...props}>
      {BARS.map((b) => (
        <rect
          key={b.x}
          x={b.x}
          y={16 - b.h / 2}
          width="3.6"
          height={b.h}
          rx="1.8"
          fill="currentColor"
          opacity={b.o}
        />
      ))}
    </svg>
  );
}

/** Mark plus wordmark, for the header. */
export function Logo() {
  return (
    <span className="inline-flex items-center gap-2">
      <LogoMark className="text-primary" />
      <span className="text-lg font-semibold tracking-tight">{BRAND_NAME}</span>
    </span>
  );
}
