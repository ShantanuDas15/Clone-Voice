import { type ReactNode, type Ref, useId } from "react";

import { GenerationStatus } from "@/components/generation-status";

export type StageState = "ready" | "working" | "done";

/** Bars in the resting line; the same count the finished take draws (`BARS` in take.tsx). */
const BASELINE_BARS = 64;

const TAG: Record<StageState, string> = { ready: "Ready", working: "Generating", done: "Done" };

/**
 * The resting line of the stage: one flat row of 64 small marks where the voice will appear. Drawn
 * with presentation attributes only (the site's Content-Security-Policy forbids inline styles) and
 * the same 48 px box as the take's waveform, so the panel does not move when the take replaces it.
 */
function Baseline() {
  return (
    <svg
      aria-hidden
      focusable="false"
      data-testid="stage-baseline"
      viewBox={`0 0 ${BASELINE_BARS * 4} 32`}
      preserveAspectRatio="none"
      className="h-12 w-full"
    >
      <g className="fill-line/60">
        {Array.from({ length: BASELINE_BARS }, (_, i) => (
          <rect key={i} x={i * 4 + 0.5} y={15} width={3} height={2} rx={1} />
        ))}
      </g>
    </svg>
  );
}

/**
 * The right-hand panel of the Generate screen: one frame, three states (UX plan §12.21). Ready shows
 * the steps over a resting line; working shows the real status and clock (the server reports no
 * stages, so none are invented); done holds the take. The frame, the heading and the line stay put,
 * so the panel does not jump between states, and only its lower part changes, fading in.
 *
 * Below `lg` the ready state is hidden (the form is the whole page there); working and done show.
 * The heading's text names the region, so a screen reader hears which state it is in.
 */
export function GenerateStage({
  state,
  voiceName,
  elapsed,
  stageRef,
  children,
}: {
  state: StageState;
  /** The voice being used (or chosen), shown under the heading; omitted when there is none yet. */
  voiceName?: string;
  /** Seconds the running generation has taken; used only while `state` is "working". */
  elapsed: number;
  stageRef?: Ref<HTMLElement>;
  /** The finished take and its controls; used only while `state` is "done". */
  children?: ReactNode;
}) {
  const titleId = useId();
  return (
    <section
      ref={stageRef}
      aria-labelledby={titleId}
      data-state={state}
      className={`max-w-xl flex-col gap-4 rounded-lg border border-border bg-surface p-5 lg:sticky lg:top-4 lg:flex lg:min-h-[22rem] ${
        state === "ready" ? "hidden" : "flex"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id={titleId} className="font-medium">
          {state === "ready" ? (
            "Your audio appears here"
          ) : state === "working" ? (
            "Your audio"
          ) : (
            <>
              Your audio{" "}
              <span className="text-sm font-normal text-muted-foreground">
                (AI-generated voice)
              </span>
            </>
          )}
        </h2>
        {/* The state in words, for the eye; the live regions below carry it for assistive technology. */}
        <span
          aria-hidden
          data-testid="stage-tag"
          className="rounded-full bg-muted px-2.5 py-1 font-mono text-xs text-muted-foreground"
        >
          {TAG[state]}
        </span>
      </div>
      {voiceName ? (
        <p className="-mt-2 text-sm text-muted-foreground">
          Voice: <span className="font-medium text-foreground">{voiceName}</span>
        </p>
      ) : null}

      {state === "done" ? (
        <div key="done" className="space-y-2 motion-safe:animate-fade-in">
          {children}
        </div>
      ) : (
        <div key={state} className="space-y-4 motion-safe:animate-fade-in">
          <Baseline />
          {state === "ready" ? (
            <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
              <li>Choose a voice.</li>
              <li>Type or paste your text.</li>
              <li>Press Generate speech, then play or download.</li>
            </ol>
          ) : (
            <GenerationStatus elapsed={elapsed} />
          )}
        </div>
      )}
    </section>
  );
}
