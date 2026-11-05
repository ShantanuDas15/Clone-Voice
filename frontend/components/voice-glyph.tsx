import { miniBars } from "@/lib/home-demo";

/** A stable small number from an id, so a voice always gets the same glyph. */
export function seedOf(id: string): number {
  let n = 0;
  for (const ch of id) n = (n * 31 + ch.charCodeAt(0)) % 997;
  return (n % 17) + 1;
}

const STEP = 120 / 22;

/**
 * A voice's identity mark: small bars shaped from its id (not its audio), the same on Generate and
 * on the Voices shelf. Decorative; the caller sizes it with `className`.
 */
export function VoiceGlyph({
  id,
  className,
  bars = 22,
}: {
  id: string;
  className: string;
  bars?: number;
}) {
  const values = miniBars(bars, seedOf(id));
  const width = bars * STEP;
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox={`0 0 ${width} 26`}
      preserveAspectRatio="none"
      className={className}
    >
      {values.map((v, i) => (
        <rect key={i} x={i * STEP + 1} y={13 - (v * 26) / 2} width={3} height={v * 26} rx={1.5} />
      ))}
    </svg>
  );
}
