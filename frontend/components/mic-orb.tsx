interface MicOrbProps {
  /** Input loudness 0..1; 0 is a still, dim ring. */
  level: number;
  /** True when nothing has been heard for a few seconds: the orb reads as "off", not live. */
  silent?: boolean;
}

/** Ring size at full level, relative to the orb. */
const RING_GROWTH = 0.5;

/**
 * A microphone mark with a ring that swells with the live input level. Decorative: the
 * `role="meter"` next to it carries the level for assistive technology. Only transform and opacity
 * change (no layout shift); under reduced motion the ring stops scaling and shows the level by
 * opacity alone.
 */
export function MicOrb({ level, silent = false }: MicOrbProps) {
  const heard = silent ? 0 : level;
  return (
    <span
      aria-hidden
      data-testid="mic-orb"
      data-silent={silent ? "true" : "false"}
      className="relative mr-3 inline-flex h-10 w-10 shrink-0 items-center justify-center"
    >
      <span
        data-testid="mic-orb-ring"
        className="absolute inset-0 rounded-full border-2 border-danger transition-[transform,opacity] duration-fast motion-reduce:!transform-none"
        style={{ transform: `scale(${1 + heard * RING_GROWTH})`, opacity: 0.25 + heard * 0.75 }}
      />
      <span
        className={`relative inline-flex h-8 w-8 items-center justify-center rounded-full text-danger-foreground ${
          silent ? "bg-muted-foreground" : "bg-danger"
        }`}
      >
        <svg focusable="false" viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
          <path d="M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4Zm6-4a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.9V19H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-2.1A6 6 0 0 0 18 11Z" />
        </svg>
      </span>
    </span>
  );
}
