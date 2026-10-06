"use client";

import { useState } from "react";

interface AudioPlayerProps {
  src: string;
  filename: string;
  label: string;
}

/** Native, keyboard-accessible player plus a download link; surfaces load errors instead of failing silently. */
export function AudioPlayer({ src, filename, label }: AudioPlayerProps) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="space-y-2">
      {failed ? (
        <p role="alert" className="text-sm">
          This audio couldn&apos;t be played in your browser. You can still download it.
        </p>
      ) : (
        // eslint-disable-next-line jsx-a11y/media-has-caption -- synthesized speech; the source text is shown beside it
        <audio
          controls
          src={src}
          aria-label={label}
          onError={() => setFailed(true)}
          className="w-full"
        />
      )}
      <a href={src} download={filename} className="inline-flex min-h-11 items-center underline">
        Download WAV
      </a>
    </div>
  );
}
