"use client";

import { useId, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { formatBytes } from "@/lib/format";
import { MAX_CLIPS, sameFile, validateAudioFile, validateClipSet } from "@/lib/validation/audio";

interface AudioUploaderProps {
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
  error?: string;
}

/**
 * File picker with a visible button, drag-and-drop and client-side pre-validation (R6, R8). It
 * takes one clip, or several of the same speaker (more clips average out one bad take). The real
 * `<input type="file">` stays in the page (visually hidden, still the only tab stop) so keyboard,
 * screen-reader and automation behaviour is the platform's; the button is its label.
 */
export function AudioUploader({ files, onChange, disabled, error }: AudioUploaderProps) {
  const id = useId();
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const shownError = localError ?? error;

  /** Add the valid picks to the set; say why any were left out. */
  function accept(picked: FileList | File[] | null | undefined) {
    const candidates = Array.from(picked ?? []);
    if (candidates.length === 0) return;
    const next = [...files];
    let problem: string | null = null;
    for (const f of candidates) {
      const bad = validateAudioFile(f);
      if (bad) problem = candidates.length > 1 ? `${f.name}: ${bad}` : bad;
      else if (!next.some((n) => sameFile(n, f))) next.push(f);
    }
    const setProblem = validateClipSet(next);
    if (setProblem) {
      // The set itself is too big: keep what was there before this pick.
      setLocalError(setProblem);
      return;
    }
    setLocalError(problem);
    onChange(next);
  }

  function remove(index: number) {
    setLocalError(null);
    onChange(files.filter((_, i) => i !== index));
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
          if (!disabled) accept(e.dataTransfer.files);
        }}
        className={`mt-1 space-y-2 rounded border border-dashed p-4 text-sm ${dragging ? "border-primary bg-muted" : "border-line"}`}
      >
        <input
          id={id}
          type="file"
          multiple
          accept=".wav,.mp3,.webm,audio/wav,audio/mpeg,audio/webm"
          disabled={disabled}
          aria-invalid={shownError ? true : undefined}
          aria-describedby={`${id}-help${shownError ? ` ${id}-error` : ""}`}
          onChange={(e) => {
            accept(e.target.files);
            e.target.value = ""; // allow picking the same file again after removing it
          }}
          className="peer sr-only"
        />
        <label
          htmlFor={id}
          className={`${buttonVariants({ variant: "secondary" })} cursor-pointer peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary peer-disabled:cursor-not-allowed peer-disabled:opacity-60`}
        >
          {files.length > 0 ? "Add another clip" : "Choose file"}
        </label>
        <p id={`${id}-help`} className="text-muted-foreground">
          Or drop files here. WAV, MP3 or WEBM, up to 25 MB in total; at least a few seconds of
          clear speech. Several clips of the same person (up to {MAX_CLIPS}) usually clone better
          than one.
        </p>
        {files.length > 0 && (
          <ul className="space-y-1" aria-label="Selected clips">
            {files.map((f, i) => (
              <li
                key={`${f.name}-${f.size}-${f.lastModified}`}
                data-testid="selected-file"
                className="flex flex-wrap items-center gap-2"
              >
                <span className="font-mono tabular-nums">
                  {f.name} · {formatBytes(f.size)}
                </span>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={disabled}
                  onClick={() => remove(i)}
                  aria-label={`Remove ${f.name}`}
                >
                  Remove
                </Button>
              </li>
            ))}
          </ul>
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
