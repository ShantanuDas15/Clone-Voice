"use client";

import { useEffect } from "react";

import { useObjectUrl } from "@/hooks/use-object-url";
import { useInputLevel } from "@/hooks/use-input-level";
import { useRecorder } from "@/hooks/use-recorder";
import {
  MAX_RECORDING_SECONDS,
  MIN_RECORDING_SECONDS,
  formatClock,
  recordingToFile,
} from "@/lib/recording";
import { Button } from "@/components/ui/button";
import { Take } from "@/components/take";

interface RecorderProps {
  /** Called with the finished take, or null when it is discarded or fails. */
  onChange: (file: File | null) => void;
  disabled?: boolean;
}

/** In-browser voice recorder with permission handling, a timer, preview and re-record. */
export function Recorder({ onChange, disabled }: RecorderProps) {
  const { state, seconds, stream, start, stop, discard } = useRecorder();
  const { level, silent } = useInputLevel(state.phase === "recording" ? stream : null);
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
            {/* The dot swells with the input level: it shows the microphone is live, not a timer. */}
            <span
              aria-hidden
              className="mr-2 inline-block h-2 w-2 rounded-full bg-danger"
              style={{ transform: `scale(${1 + level * 0.8})`, opacity: 0.5 + level * 0.5 }}
            />
            Recording {formatClock(seconds)} / {formatClock(MAX_RECORDING_SECONDS)}
          </p>
          <div
            role="meter"
            aria-label="Microphone level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(level * 100)}
            className="h-2 overflow-hidden rounded bg-muted"
          >
            <div className="h-full bg-primary" style={{ width: `${level * 100}%` }} />
          </div>
          {silent && (
            <p role="status" className="text-muted-foreground">
              We can&apos;t hear anything. Check that the right microphone is selected and not
              muted.
            </p>
          )}
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
