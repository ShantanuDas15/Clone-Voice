import { type ReactNode, type Ref, useId } from "react";

import { GenerationStatus } from "@/components/generation-status";
import { VoiceCanvas } from "@/components/voice-canvas";
import { VoiceState } from "@/components/voice-wave";
import { formatClock } from "@/lib/recording";

export type StageState = "ready" | "working" | "done";

const TAG: Record<StageState, string> = { ready: "Ready", working: "Generating", done: "Done" };

/**
 * The voiceprint at the top of the stage (owner-approved mock, UX plan §12.26): it ripples gently,
 * swells while the user types or picks a voice, and keeps swelling while a generation runs. It
 * holds the same place through ready and working, so the panel does not move between them.
 */
function Voiceprint({ paused, speaker }: { paused: boolean; speaker?: string }) {
  return (
    <div data-testid="stage-voiceprint" aria-hidden>
      <VoiceCanvas className="h-44 w-full" paused={paused} />
      <p className="mt-3 flex flex-wrap justify-between gap-x-3 border-t border-border pt-2 font-mono text-xs text-muted-foreground">
        <span>
          voiceprint · <VoiceState />
        </span>
        {speaker ? <span>speaks as {speaker}</span> : null}
      </p>
    </div>
  );
}

/**
 * The right-hand panel of the Generate screen: one glass frame, three states (UX plan §12.21,
 * §12.26). Ready shows the live voiceprint over the three steps; working keeps the voiceprint, adds
 * a large clock and the real status (the server reports no stages, so none are invented); done
 * holds the take. The frame and the heading stay put, so the panel does not jump between states.
 *
 * Below `lg` the ready state is hidden (the form is the whole page there); working and done show.
 * The heading's text names the region, so a screen reader hears which state it is in.
 */
export function GenerateStage({
  state,
  voiceName,
  elapsed,
  stageRef,
  paused = false,
  children,
}: {
  state: StageState;
  /** The voice being used (or chosen), shown under the heading; omitted when there is none yet. */
  voiceName?: string;
  /** Seconds the running generation has taken; used only while `state` is "working". */
  elapsed: number;
  stageRef?: Ref<HTMLElement>;
  /** Holds the voiceprint's endless ripple still (the page's Pause motion control). */
  paused?: boolean;
  /** The finished take and its controls; used only while `state` is "done". */
  children?: ReactNode;
}) {
  const titleId = useId();
  return (
    <section
      ref={stageRef}
      aria-labelledby={titleId}
      data-state={state}
      className={`gx-card gx-stage flex-col gap-4 lg:sticky lg:top-4 lg:flex lg:min-h-[34rem] ${
        state === "ready" ? "hidden" : "flex"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id={titleId} className="text-lg font-semibold">
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
          data-state={state}
          className="gx-tag rounded-full bg-muted px-2.5 py-1 font-mono text-xs text-muted-foreground"
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
          <Voiceprint paused={paused} speaker={voiceName?.split(",")[0]} />
          {state === "ready" ? (
            <ol className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
              <li>Choose a voice.</li>
              <li>Type or paste your text.</li>
              <li>Press Generate speech, then play or download.</li>
            </ol>
          ) : (
            <>
              <p aria-hidden className="gx-clock" data-testid="stage-clock">
                {formatClock(elapsed)}
              </p>
              <GenerationStatus elapsed={elapsed} />
            </>
          )}
        </div>
      )}
    </section>
  );
}
