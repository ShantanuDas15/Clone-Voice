"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { formatClock } from "@/lib/recording";

interface TakeProps {
  /** Object URL of the audio. */
  src: string;
  /** The same audio as a Blob; lets us draw its waveform. Without it there is simply no waveform. */
  blob?: Blob;
  filename: string;
  /** Accessible name, e.g. "Generated speech". */
  label: string;
  autoPlay?: boolean;
  /** Omit the download link (e.g. a preview of a recording that is about to be uploaded). */
  hideDownload?: boolean;
}

const BARS = 64;

/**
 * One take of audio: a waveform with a playhead, play/pause, a seek slider and a monospaced
 * timecode, over a native `<audio>` element (so codecs, decoding and media-key behaviour stay the
 * browser's). The waveform is decorative (`aria-hidden`): the accessible controls are the button
 * and the slider. If the shape cannot be computed the controls still work; if the audio cannot be
 * played the take says so and keeps the download.
 */
export function Take({ src, blob, filename, label, autoPlay, hideDownload }: TakeProps) {
  const audio = useRef<HTMLAudioElement>(null);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setPeaks(null);
    if (!blob) return;
    let live = true;
    // Loaded on demand so the decoder is not part of any page's first-load JavaScript.
    void import("@/lib/audio-peaks").then(async ({ computePeaks }) => {
      const result = await computePeaks(blob, BARS);
      if (live) setPeaks(result);
    });
    return () => {
      live = false;
    };
  }, [blob]);

  function seekTo(next: number) {
    const clamped = Math.min(duration, Math.max(0, next));
    setTime(clamped);
    if (audio.current) audio.current.currentTime = clamped;
  }

  function toggle() {
    const el = audio.current;
    if (!el) return;
    if (el.paused) void el.play().catch(() => setPlaying(false));
    else el.pause();
  }

  const progress = duration > 0 ? Math.min(1, time / duration) : 0;
  const stamp = `${formatClock(time)} / ${formatClock(duration)}`;

  if (failed) {
    return (
      <div className="space-y-2">
        <p role="alert" className="text-sm">
          This audio couldn&apos;t be played in your browser. You can still download it.
        </p>
        {!hideDownload && <DownloadLink src={src} filename={filename} />}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- synthesized speech; the source text is shown beside it */}
      <audio
        ref={audio}
        src={src}
        preload="metadata"
        autoPlay={autoPlay}
        aria-label={label}
        onLoadedMetadata={(e) =>
          setDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : 0)
        }
        onDurationChange={(e) =>
          setDuration(Number.isFinite(e.currentTarget.duration) ? e.currentTarget.duration : 0)
        }
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setTime(0);
        }}
        onError={() => setFailed(true)}
      />
      <div className="flex items-center gap-3">
        <Button
          variant="secondary"
          size="sm"
          onClick={toggle}
          aria-label={`${playing ? "Pause" : "Play"} ${label}`}
        >
          {playing ? "Pause" : "Play"}
        </Button>
        <span className="font-mono text-sm tabular-nums" data-testid="take-time">
          {stamp}
        </span>
      </div>
      <div className="relative h-12 rounded focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary">
        {peaks && <Waveform peaks={peaks} progress={progress} />}
        {!peaks && <div aria-hidden className="absolute inset-x-0 top-1/2 h-0.5 bg-border" />}
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.05}
          value={time}
          disabled={duration === 0}
          aria-label={`Seek ${label}`}
          aria-valuetext={stamp}
          onChange={(e) => seekTo(Number(e.target.value))}
          onKeyDown={(e) => {
            // Takes are short, so the arrow keys jump 2 s instead of the slider's tiny step.
            if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
            e.preventDefault();
            seekTo(time + (e.key === "ArrowRight" ? 2 : -2));
          }}
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
        />
      </div>
      {!hideDownload && <DownloadLink src={src} filename={filename} />}
    </div>
  );
}

function DownloadLink({ src, filename }: { src: string; filename: string }) {
  return (
    <a href={src} download={filename} className="inline-flex min-h-11 items-center underline">
      Download WAV
    </a>
  );
}

/** Bars in two colours: the played part (accent) over the rest (muted), split at the playhead. */
function Waveform({ peaks, progress }: { peaks: number[]; progress: number }) {
  const w = peaks.length * 4;
  const bars = peaks.map((p, i) => {
    const h = Math.max(2, p * 44);
    return <rect key={i} x={i * 4 + 0.5} y={24 - h / 2} width={3} height={h} rx={1.5} />;
  });
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox={`0 0 ${w} 48`}
      preserveAspectRatio="none"
      className="absolute inset-0 h-full w-full"
    >
      <defs>
        <clipPath id="take-played">
          <rect x={0} y={0} width={w * progress} height={48} />
        </clipPath>
      </defs>
      <g className="fill-border">{bars}</g>
      <g className="fill-primary" clipPath="url(#take-played)">
        {bars}
      </g>
    </svg>
  );
}
