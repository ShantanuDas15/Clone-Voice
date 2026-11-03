"use client";

import { useEffect, useState } from "react";

import { useObjectUrl } from "@/hooks/use-object-url";
import { useInputLevel, useLevelTrace } from "@/hooks/use-input-level";
import { useRecorder } from "@/hooks/use-recorder";
import { RECORDING_PROMPTS } from "@/lib/recording-prompts";
import {
  MAX_RECORDING_SECONDS,
  MIN_RECORDING_SECONDS,
  formatClock,
  recordingToFile,
} from "@/lib/recording";
import { Button } from "@/components/ui/button";
import { MicOrb } from "@/components/mic-orb";
import { Take } from "@/components/take";

interface RecorderProps {
  /** Called with the finished take, or null when it is discarded or fails. */
  onChange: (file: File | null) => void;
  disabled?: boolean;
}

/** Seconds of speech that work best for a clone; shown as guidance while recording. */
const BEST_FROM_SECONDS = 10;
const BEST_TO_SECONDS = 30;

function MicIcon() {
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="currentColor"
    >
      <path d="M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4Zm6-4a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.9V19H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-2.1A6 6 0 0 0 18 11Z" />
    </svg>
  );
}

/** A line to read for someone who does not know what to say; "Show another line" steps through them. */
function ReadingPrompt() {
  const [index, setIndex] = useState(0);
  return (
    <div className="rounded bg-muted p-3">
      <p className="text-sm font-medium text-muted-foreground">
        If you&apos;re not sure what to say, try reading
      </p>
      <p className="mt-1" data-testid="reading-prompt">
        “{RECORDING_PROMPTS[index]}”
      </p>
      <Button
        variant="quiet"
        size="sm"
        className="mt-1"
        onClick={() => setIndex((i) => (i + 1) % RECORDING_PROMPTS.length)}
      >
        Show another line
      </Button>
    </div>
  );
}

/** How the recording is going, in words: too short, long enough, or the length that works best. */
function lengthGuidance(seconds: number): string {
  if (seconds < MIN_RECORDING_SECONDS) {
    return `Keep going: at least ${MIN_RECORDING_SECONDS} seconds are needed.`;
  }
  if (seconds < BEST_FROM_SECONDS) {
    return `Long enough to stop. ${BEST_FROM_SECONDS}–${BEST_TO_SECONDS} seconds works best.`;
  }
  if (seconds <= BEST_TO_SECONDS) {
    return `Good length. ${BEST_FROM_SECONDS}–${BEST_TO_SECONDS} seconds works best.`;
  }
  return "Long enough. You can stop whenever you like.";
}

/** In-browser voice recorder with permission handling, a timer, preview and re-record. */
export function Recorder({ onChange, disabled }: RecorderProps) {
  const { state, seconds, stream, start, stop, discard } = useRecorder();
  const { level, silent } = useInputLevel(state.phase === "recording" ? stream : null);
  const trace = useLevelTrace(level, state.phase === "recording");
  const previewUrl = useObjectUrl(state.phase === "stopped" ? state.blob : null);

  useEffect(() => {
    onChange(state.phase === "stopped" ? recordingToFile(state.blob) : null);
    // `onChange` is intentionally excluded: callers pass an unstable setter wrapper.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const canStop = seconds >= MIN_RECORDING_SECONDS;

  return (
    <div className="space-y-3 rounded border border-border p-4 text-sm">
      {state.phase === "idle" && (
        <>
          <p className="text-muted-foreground">
            Record {MIN_RECORDING_SECONDS}–{MAX_RECORDING_SECONDS} seconds of clear speech in a
            quiet room. {BEST_FROM_SECONDS}–{BEST_TO_SECONDS} seconds works best.
          </p>
          <Button
            className="min-h-14 gap-2 px-6 text-base"
            onClick={() => void start()}
            disabled={disabled}
          >
            <MicIcon />
            Start recording
          </Button>
          <ReadingPrompt />
        </>
      )}

      {state.phase === "requesting" && (
        <>
          <p role="status">Waiting for microphone permission…</p>
          <Button variant="secondary" onClick={discard}>
            Cancel
          </Button>
        </>
      )}

      {state.phase === "recording" && (
        <>
          <p
            role="status"
            aria-live="off"
            className="flex items-center font-mono text-xl font-medium tabular-nums"
          >
            {/* The ring swells with the input level: it shows the microphone is live, not a timer. */}
            <MicOrb level={level} silent={silent} />
            Recording {formatClock(seconds)} / {formatClock(MAX_RECORDING_SECONDS)}
          </p>
          {/* The trace is the meter: the bars are decorative, the role carries the level. */}
          <div
            role="meter"
            aria-label="Microphone level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(level * 100)}
            className="flex h-16 items-center gap-[3px]"
          >
            {trace.map((value, i) => (
              <span
                key={i}
                aria-hidden
                className="min-w-[2px] flex-1 rounded bg-primary"
                style={{
                  height: `${Math.max(6, Math.round(value * 100))}%`,
                  opacity: 0.35 + 0.65 * (i / (trace.length - 1)),
                }}
              />
            ))}
          </div>
          <div aria-hidden className="relative h-1.5 rounded bg-muted">
            <div
              className="h-full rounded bg-primary"
              style={{ width: `${Math.min(100, (seconds / MAX_RECORDING_SECONDS) * 100)}%` }}
            />
            <span
              className="absolute -bottom-0.5 -top-0.5 w-0.5 bg-line"
              style={{ left: `${(MIN_RECORDING_SECONDS / MAX_RECORDING_SECONDS) * 100}%` }}
            />
          </div>
          {silent && (
            <p role="status" className="text-muted-foreground">
              We can&apos;t hear anything. Check that the right microphone is selected and not
              muted.
            </p>
          )}
          <p className={canStop ? "font-medium text-success" : "text-muted-foreground"}>
            {lengthGuidance(seconds)}
          </p>
          <div className="flex gap-2">
            <Button className="min-h-12 px-5" onClick={stop} disabled={!canStop}>
              Stop recording
            </Button>
            <Button variant="secondary" onClick={discard}>
              Discard
            </Button>
          </div>
        </>
      )}

      {state.phase === "stopped" && (
        <>
          <p role="status">Recorded {formatClock(state.seconds)}. Listen before you upload.</p>
          {previewUrl && (
            <Take
              src={previewUrl}
              blob={state.blob}
              filename="recording.webm"
              label="Recording preview"
              hideDownload
            />
          )}
          <Button variant="secondary" onClick={discard} disabled={disabled}>
            Discard and re-record
          </Button>
        </>
      )}

      {state.phase === "error" && (
        <>
          <p role="alert">{state.message}</p>
          <Button variant="secondary" onClick={() => void start()}>
            Try again
          </Button>
        </>
      )}
    </div>
  );
}
