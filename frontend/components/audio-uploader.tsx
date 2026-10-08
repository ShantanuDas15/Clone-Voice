"use client";

import { useId, useRef, useState } from "react";

import { formatBytes } from "@/lib/format";
import { validateAudioFile } from "@/lib/validation/audio";

interface AudioUploaderProps {
  file: File | null;
  onChange: (file: File | null) => void;
  disabled?: boolean;
  error?: string;
}

/** Keyboard-operable file picker with drag-and-drop and client-side pre-validation (R6, R8). */
export function AudioUploader({ file, onChange, disabled, error }: AudioUploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
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
        className={`mt-1 rounded border border-dashed p-4 text-sm ${dragging ? "border-primary bg-muted" : "border-line"}`}
      >
        <input
          ref={inputRef}
          id={id}
          type="file"
          accept=".wav,.mp3,.webm,audio/wav,audio/mpeg,audio/webm"
          disabled={disabled}
          aria-invalid={shownError ? true : undefined}
          aria-describedby={`${id}-help${shownError ? ` ${id}-error` : ""}`}
          onChange={(e) => accept(e.target.files?.[0])}
          className="block min-h-11 w-full"
        />
        <p id={`${id}-help`} className="mt-2 text-muted-foreground">
          Drop a file here or choose one. WAV, MP3 or WEBM, up to 25 MB; at least a few seconds of
          clear speech.
        </p>
        {file && (
          <p className="mt-2" data-testid="selected-file">
            {file.name} · {formatBytes(file.size)}
          </p>
        )}
      </div>
      {shownError && (
        <p id={`${id}-error`} role="alert" className="mt-1 text-sm text-danger">
          {shownError}
        </p>
      )}
    </div>
  );
}
