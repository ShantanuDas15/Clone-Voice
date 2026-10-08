"use client";

import { useEffect } from "react";

import { useObjectUrl } from "@/hooks/use-object-url";
import { useRecorder } from "@/hooks/use-recorder";
import {
  MAX_RECORDING_SECONDS,
  MIN_RECORDING_SECONDS,
  formatClock,
  recordingToFile,
} from "@/lib/recording";

interface RecorderProps {
  /** Called with the finished take, or null when it is discarded or fails. */
  onChange: (file: File | null) => void;
  disabled?: boolean;
}

/** In-browser voice recorder with permission handling, a timer, preview and re-record. */
export function Recorder({ onChange, disabled }: RecorderProps) {
  const { state, seconds, start, stop, discard } = useRecorder();
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
            quiet room. 10–30 seconds works best.
          </p>
          <button
            type="button"
            onClick={() => void start()}
            disabled={disabled}
            className="min-h-11 rounded bg-primary px-4 text-primary-foreground disabled:opacity-60"
          >
            Start recording
          </button>
        </>
      )}

      {state.phase === "requesting" && (
        <>
          <p role="status">Waiting for microphone permission…</p>
          <button
            type="button"
            onClick={discard}
            className="min-h-11 rounded border border-line px-4"
          >
            Cancel
          </button>
        </>
      )}

      {state.phase === "recording" && (
        <>
          <p role="status" aria-live="off" className="font-mono font-medium tabular-nums">
            <span aria-hidden className="mr-2 inline-block h-2 w-2 rounded-full bg-danger" />
            Recording {formatClock(seconds)} / {formatClock(MAX_RECORDING_SECONDS)}
          </p>
          {!canStop && (
            <p className="text-muted-foreground">
              Keep going: at least {MIN_RECORDING_SECONDS} seconds are needed.
            </p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={stop}
              disabled={!canStop}
              className="min-h-11 rounded bg-primary px-4 text-primary-foreground disabled:opacity-60"
            >
              Stop recording
            </button>
            <button
              type="button"
              onClick={discard}
              className="min-h-11 rounded border border-line px-4"
            >
              Discard
            </button>
          </div>
        </>
      )}

      {state.phase === "stopped" && (
        <>
          <p role="status">Recorded {formatClock(state.seconds)}. Listen before you upload.</p>
          {previewUrl && (
            // eslint-disable-next-line jsx-a11y/media-has-caption -- the user's own voice sample
            <audio controls src={previewUrl} aria-label="Recording preview" className="w-full" />
          )}
          <button
            type="button"
            onClick={discard}
            disabled={disabled}
            className="min-h-11 rounded border border-line px-4 disabled:opacity-60"
          >
            Discard and re-record
          </button>
        </>
      )}

      {state.phase === "error" && (
        <>
          <p role="alert">{state.message}</p>
          <button
            type="button"
            onClick={() => void start()}
            className="min-h-11 rounded border border-line px-4"
          >
            Try again
          </button>
        </>
      )}
    </div>
  );
}
