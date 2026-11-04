"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { VoiceQualityReport } from "@/components/voice-quality-report";
import type { VoiceProfileUpload } from "@/lib/api/voice";

export type VoiceStageState = "ready" | "uploading" | "analysing" | "created";

/** Bars in the shape; the same count as the Generate take and its resting line. */
const BARS = 64;

const TAG: Record<VoiceStageState, string> = {
  ready: "Ready",
  uploading: "Uploading",
  analysing: "Analysing",
  created: "Created",
};

/**
 * The shape of the chosen clip: its own loudness as 64 bars (`peaks`, 0..1, decoded in the browser),
 * or a flat resting line when there is none. While uploading, bars take the accent colour as the real
 * upload progress advances; once the voice exists they all do, drawn in once. Presentation attributes
 * only (the site's Content-Security-Policy forbids inline styles); decorative (`aria-hidden`).
 */
function Shape({
  state,
  peaks,
  progress,
}: {
  state: VoiceStageState;
  peaks: readonly number[] | null;
  progress: number;
}) {
  const sent = state === "uploading" ? Math.floor(progress * BARS) : state === "created" ? BARS : 0;
  return (
    <svg
      aria-hidden
      focusable="false"
      data-testid="voice-shape"
      viewBox={`0 0 ${BARS * 4} 48`}
      preserveAspectRatio="none"
      className={`h-24 w-full ${state === "created" ? "motion-safe:animate-draw-in" : ""}`.trim()}
    >
      {Array.from({ length: BARS }, (_, i) => {
        const p = peaks?.[Math.floor((i / BARS) * peaks.length)];
        const h = p === undefined ? 2 : Math.max(2, Math.min(1, Math.max(0, p)) * 44);
        return (
          <rect
            key={i}
            x={i * 4 + 0.5}
            y={24 - h / 2}
            width={3}
            height={h}
            rx={1.5}
            className={
              i < sent ? "fill-primary" : state === "analysing" ? "fill-line/40" : "fill-line/60"
            }
          />
        );
      })}
    </svg>
  );
}

/** Whole seconds since `running` became true (0 when it is not). */
function useSeconds(running: boolean): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!running) {
      setSeconds(0);
      return;
    }
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return seconds;
}

function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/**
 * The right-hand panel of the Voices screen, one frame through four states (UX plan §12.23): ready
 * (the steps), uploading (the real byte progress, drawn into the clip's own shape), analysing (a
 * clock and the indeterminate bar; the server reports no steps, so none are invented) and created
 * (the shape drawn in once, the quality advice and the next step). Below `lg` the ready state is
 * hidden, as on Generate. The live regions carry the state for assistive technology.
 */
export function VoiceStage({
  state,
  progress,
  peaks,
  created,
}: {
  state: VoiceStageState;
  /** Bytes sent, 0..1; used while `state` is "uploading". */
  progress: number;
  peaks: readonly number[] | null;
  created: VoiceProfileUpload | null;
}) {
  const titleId = useId();
  const section = useRef<HTMLElement>(null);
  const seconds = useSeconds(state === "analysing");

  // The result and the progress can sit below the fold: bring the panel into view when it changes.
  useEffect(() => {
    if (state === "ready") return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    section.current?.scrollIntoView?.({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }, [state]);

  return (
    <section
      ref={section}
      aria-labelledby={titleId}
      data-state={state}
      className={`max-w-xl flex-col gap-4 rounded-lg border border-border bg-surface p-5 lg:sticky lg:top-4 lg:flex lg:min-h-[22rem] ${
        state === "ready" ? "hidden" : "flex"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id={titleId} className="font-medium">
          Your new voice
        </h2>
        <span
          aria-hidden
          data-testid="voice-stage-tag"
          className="rounded-full bg-muted px-2.5 py-1 font-mono text-xs text-muted-foreground"
        >
          {TAG[state]}
        </span>
      </div>
      <Shape state={state} peaks={peaks} progress={progress} />

      {state === "ready" && (
        <ol
          key="ready"
          className="list-decimal space-y-1 pl-5 text-sm text-muted-foreground motion-safe:animate-fade-in"
        >
          <li>Name the voice and add a clip (upload or record).</li>
          <li>Tick the two confirmations.</li>
          <li>Press Create voice. This takes under a minute.</li>
        </ol>
      )}
      {state === "uploading" && (
        <div role="status" aria-live="polite" className="space-y-2 text-sm">
          <progress
            value={progress}
            max={1}
            className="length-meter w-full"
            aria-label="Upload progress"
          />
          <p>Uploading… {Math.round(progress * 100)}%</p>
        </div>
      )}
      {state === "analysing" && (
        <div role="status" aria-live="polite" className="space-y-2 text-sm">
          <p>
            Analysing the voice.{" "}
            <span aria-hidden className="font-mono tabular-nums">
              {clock(seconds)}
            </span>
          </p>
          <p className="text-muted-foreground">
            This can take a minute; please keep this page open.
          </p>
          <div aria-hidden className="h-1 overflow-hidden rounded bg-muted">
            <div className="h-full w-1/3 animate-indeterminate rounded bg-primary motion-reduce:w-full motion-reduce:animate-none" />
          </div>
        </div>
      )}
      {state === "created" && created && (
        <div key="created" className="space-y-2 motion-safe:animate-fade-in">
          <Alert tone="success">Voice “{created.name}” created.</Alert>
          <VoiceQualityReport profile={created} />
          <Link
            href={`/generate?voice=${encodeURIComponent(created.id)}`}
            className={buttonVariants()}
          >
            Generate speech with “{created.name}”
          </Link>
        </div>
      )}
    </section>
  );
}
