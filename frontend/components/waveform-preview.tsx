import { PEAK_SCALE } from "@/lib/api/history";

/**
 * The shape of a generated clip, drawn from the stored bar heights (0..100) so a History row can
 * show it before the audio is fetched. Static and decorative (`aria-hidden`): the Play button and
 * the row's text are the content. Renders nothing for an empty list.
 */
export function WaveformPreview({ peaks }: { peaks: number[] | null | undefined }) {
  if (!peaks || peaks.length === 0) return null;
  const w = peaks.length * 4;
  return (
    <svg
      aria-hidden
      focusable="false"
      data-testid="waveform-preview"
      viewBox={`0 0 ${w} 32`}
      preserveAspectRatio="none"
      className="h-8 w-full"
    >
      <g className="fill-muted-foreground/50">
        {peaks.map((p, i) => {
          const h = Math.max(2, (Math.min(PEAK_SCALE, Math.max(0, p)) / PEAK_SCALE) * 30);
          return <rect key={i} x={i * 4 + 0.5} y={16 - h / 2} width={3} height={h} rx={1.5} />;
        })}
      </g>
    </svg>
  );
}
