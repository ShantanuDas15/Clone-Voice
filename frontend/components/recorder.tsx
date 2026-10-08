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
import { Button } from "@/components/ui/button";

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
          <Button onClick={() => void start()} disabled={disabled}>
            Start recording
          </Button>
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
            <Button onClick={stop} disabled={!canStop}>
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
            // eslint-disable-next-line jsx-a11y/media-has-caption -- the user's own voice sample
            <audio controls src={previewUrl} aria-label="Recording preview" className="w-full" />
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
