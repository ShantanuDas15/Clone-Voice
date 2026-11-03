/** Seconds after which a generation is called slow and the wording changes. */
export const SLOW_AFTER_SECONDS = 20;

export type GenerationPhase = "working" | "slow";

/** Which state a running generation is in; the server reports no stages, so only time is known. */
export function generationPhase(elapsedSeconds: number): GenerationPhase {
  return elapsedSeconds >= SLOW_AFTER_SECONDS ? "slow" : "working";
}

function PhaseIcon({ phase }: { phase: GenerationPhase }) {
  return (
    <svg
      aria-hidden
      focusable="false"
      data-testid="generation-icon"
      data-phase={phase}
      viewBox="0 0 24 24"
      width="16"
      height="16"
      className="mr-1.5 inline-block align-[-2px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    >
      {phase === "working" ? (
        <path d="M4 12v0M8 8v8M12 4v16M16 8v8M20 12v0" />
      ) : (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </>
      )}
    </svg>
  );
}

/**
 * The status shown while speech is generated: what is happening, the seconds so far, and how long
 * it may take. It is one polite live region, so the text change from "Generating…" to the slow
 * wording is announced once; the ticking seconds are hidden from assistive technology. The server
 * reports no stages, so none are invented: the only honest change is "this is taking longer".
 */
export function GenerationStatus({ elapsed }: { elapsed: number }) {
  const phase = generationPhase(elapsed);
  return (
    <div role="status" aria-live="polite" className="space-y-2 text-sm" data-phase={phase}>
      <p>
        <PhaseIcon phase={phase} />
        {phase === "working" ? "Generating…" : "Still generating…"}{" "}
        {/* Hidden from assistive tech so the ticking seconds are not announced every second. */}
        <span aria-hidden className="font-mono tabular-nums">
          {elapsed} s
        </span>
      </p>
      <p className={phase === "slow" ? "text-foreground" : "text-muted-foreground"}>
        {phase === "working"
          ? "This can take a minute or more on slow servers; please keep this page open."
          : "This is taking longer than usual. Keep this page open, or cancel and try again."}
      </p>
      <div aria-hidden className="h-1 overflow-hidden rounded bg-muted">
        <div className="h-full w-1/3 animate-indeterminate rounded bg-primary motion-reduce:w-full motion-reduce:animate-none" />
      </div>
    </div>
  );
}
