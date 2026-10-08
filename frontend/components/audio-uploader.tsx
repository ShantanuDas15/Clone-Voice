"use client";

import { useId, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import { validateAudioFile } from "@/lib/validation/audio";

interface AudioUploaderProps {
  file: File | null;
  onChange: (file: File | null) => void;
  disabled?: boolean;
  error?: string;
}

/**
 * File picker with a visible button, drag-and-drop and client-side pre-validation (R6, R8). The
 * real `<input type="file">` stays in the page (visually hidden, still the only tab stop) so
 * keyboard, screen-reader and automation behaviour is the platform's; the button is its label.
 */
export function AudioUploader({ file, onChange, disabled, error }: AudioUploaderProps) {
  const id = useId();
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const shownError = localError ?? error;

  function accept(candidate: File | undefined) {
    if (!candidate) return;
    const problem = validateAudioFile(candidate);
    setLocalError(problem);
    onChange(problem ? null : candidate);
  }

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        Voice sample
      </label>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled) accept(e.dataTransfer.files[0]);
        }}
        className={`mt-1 space-y-2 rounded border border-dashed p-4 text-sm ${dragging ? "border-primary bg-muted" : "border-line"}`}
      >
        <input
          id={id}
          type="file"
          accept=".wav,.mp3,.webm,audio/wav,audio/mpeg,audio/webm"
          disabled={disabled}
          aria-invalid={shownError ? true : undefined}
          aria-describedby={`${id}-help${shownError ? ` ${id}-error` : ""}`}
          onChange={(e) => accept(e.target.files?.[0])}
          className="peer sr-only"
        />
        <label
          htmlFor={id}
          className={`${buttonVariants({ variant: "secondary" })} cursor-pointer peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary peer-disabled:cursor-not-allowed peer-disabled:opacity-60`}
        >
          {file ? "Choose a different file" : "Choose file"}
        </label>
        <p id={`${id}-help`} className="text-muted-foreground">
          Or drop a file here. WAV, MP3 or WEBM, up to 25 MB; at least a few seconds of clear
          speech.
        </p>
        {file && (
          <p data-testid="selected-file">
            <span className="font-mono tabular-nums">
              {file.name} · {formatBytes(file.size)}
            </span>
          </p>
        )}
      </div>
      {shownError && (
        <Alert tone="danger" id={`${id}-error`} className="mt-1">
          {shownError}
        </Alert>
      )}
    </div>
  );
}
