"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { claimPlayback, releasePlayback } from "@/lib/exclusive-playback";
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
  /** Draw the waveform in once when it first appears (a finished generation); off for replays. */
  animateIn?: boolean;
  /** Move keyboard focus to the play control on mount (a take that replaced the control that was pressed). */
  focusPlay?: boolean;
  /** Add skip back and forward ({@link SKIP_SECONDS} s) and a playback-speed choice beside play.
   * The visible labels are inside the accessible names (WCAG 2.5.3). */
  extraControls?: boolean;
  /** Put the waveform above the controls (the Generate stage, where it continues the resting line). */
  waveformFirst?: boolean;
}

const BARS = 64;
const SKIP_SECONDS = 15;
const SPEEDS = [1, 1.25, 1.5] as const;
type Speed = (typeof SPEEDS)[number];

/**
 * One take of audio: a waveform with a playhead, play/pause, a seek slider and a monospaced
 * timecode, over a native `<audio>` element (so codecs, decoding and media-key behaviour stay the
 * browser's). The waveform is decorative (`aria-hidden`): the accessible controls are the button
 * and the slider. If the shape cannot be computed the controls still work; if the audio cannot be
 * played the take says so and keeps the download.
 */
export function Take({
  src,
  blob,
  filename,
  label,
  autoPlay,
  hideDownload,
  animateIn,
  focusPlay,
  extraControls,
  waveformFirst,
}: TakeProps) {
  const audio = useRef<HTMLAudioElement>(null);
  const playButton = useRef<HTMLButtonElement>(null);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [duration, setDuration] = useState(0);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);
  const [speed, setSpeed] = useState<Speed>(1);
  // Where the mouse is over the waveform, 0..1; null when it is not (and always on touch).
  const [hover, setHover] = useState<number | null>(null);
  // True while we are seeking past the end of a clip of unknown length to make the browser measure it.
  const measuring = useRef(false);
  // Measure a clip at most once, so a browser that cannot do it is not asked again and again.
  const attempted = useRef(false);

  // Loading a new source resets the element's rate to its default, so set both: the chosen speed
  // then also holds when the same Take shows a regenerated clip.
  useEffect(() => {
    const el = audio.current;
    if (!el) return;
    el.defaultPlaybackRate = speed;
    el.playbackRate = speed;
  }, [speed, src]);

  useEffect(() => {
    if (focusPlay) playButton.current?.focus();
    const el = audio.current;
    return () => {
      if (el) releasePlayback(el);
    };
  }, [focusPlay]);

  useEffect(() => {
    attempted.current = false;
    measuring.current = false;
  }, [src]);

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

  /**
   * Read the clip's length. A clip recorded in chunks (MediaRecorder with a timeslice) has no length
   * in its header, so the browser reports Infinity and the seek bar would stay disabled at 0:00.
   * Seeking far past the end makes it measure the clip; once it reports a real length we go back
   * to the start.
   */
  function measure(el: HTMLAudioElement) {
    if (Number.isFinite(el.duration)) {
      setDuration(el.duration);
      if (measuring.current) {
        measuring.current = false;
        el.currentTime = 0;
        setTime(0);
      }
      return;
    }
    setDuration(0);
    if (el.duration === Infinity && !attempted.current) {
      attempted.current = true;
      measuring.current = true;
      el.currentTime = 1e101;
    }
  }

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
    <div className={waveformFirst ? "flex flex-col gap-2" : "space-y-2"}>
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- synthesized speech; the source text is shown beside it */}
      <audio
        ref={audio}
        src={src}
        preload="metadata"
        autoPlay={autoPlay}
        aria-label={label}
        onLoadedMetadata={(e) => measure(e.currentTarget)}
        onDurationChange={(e) => measure(e.currentTarget)}
        onTimeUpdate={(e) => {
          const el = e.currentTarget;
          if (measuring.current) {
            // The jump past the end has landed: it is not the playhead. Take the length if the
            // browser now knows it; either way return to the start and carry on.
            if (Number.isFinite(el.duration)) measure(el);
            else {
              measuring.current = false;
              el.currentTime = 0;
            }
            return;
          }
          setTime(el.currentTime);
        }}
        onPlay={(e) => {
          claimPlayback(e.currentTarget);
          setPlaying(true);
        }}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setTime(0);
        }}
        onError={() => setFailed(true)}
      />
      <div className="flex flex-wrap items-center gap-2">
        {extraControls && (
          <Button
            variant="secondary"
            size="sm"
            disabled={duration === 0}
            onClick={() => seekTo(time - SKIP_SECONDS)}
            aria-label={`Back ${SKIP_SECONDS} seconds`}
          >
            Back {SKIP_SECONDS} s
          </Button>
        )}
        <Button
          ref={playButton}
          variant="secondary"
          size="sm"
          onClick={toggle}
          aria-label={`${playing ? "Pause" : "Play"} ${label}`}
        >
          {playing ? "Pause" : "Play"}
        </Button>
        {extraControls && (
          <Button
            variant="secondary"
            size="sm"
            disabled={duration === 0}
            onClick={() => seekTo(time + SKIP_SECONDS)}
            aria-label={`Forward ${SKIP_SECONDS} seconds`}
          >
            Forward {SKIP_SECONDS} s
          </Button>
        )}
        <span className="ml-1 font-mono text-sm tabular-nums" data-testid="take-time">
          {stamp}
        </span>
      </div>
      {extraControls && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span aria-hidden>Speed</span>
          <div role="group" aria-label="Playback speed" className="flex gap-1">
            {SPEEDS.map((value) => (
              <Button
                key={value}
                variant="secondary"
                size="sm"
                className={`font-mono tabular-nums text-foreground ${speed === value ? "bg-muted" : ""}`.trim()}
                aria-pressed={speed === value}
                onClick={() => setSpeed(value)}
              >
                {value}x
              </Button>
            ))}
          </div>
        </div>
      )}
      <div
        className={`relative h-12 rounded focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-primary ${
          waveformFirst ? "order-first" : ""
        }`}
        onPointerMove={(e) => {
          if (e.pointerType !== "mouse" || duration === 0) return;
          const box = e.currentTarget.getBoundingClientRect();
          if (box.width === 0) return;
          setHover(Math.min(1, Math.max(0, (e.clientX - box.left) / box.width)));
        }}
        onPointerLeave={() => setHover(null)}
      >
        {peaks && <Waveform peaks={peaks} progress={progress} animateIn={animateIn} />}
        {!peaks && <div aria-hidden className="absolute inset-x-0 top-1/2 h-0.5 bg-border" />}
        {duration > 0 && (
          <span
            aria-hidden
            data-testid="take-playhead"
            className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 rounded bg-foreground"
            style={{ left: `${progress * 100}%` }}
          />
        )}
        {hover !== null && duration > 0 && (
          <>
            <span
              aria-hidden
              data-testid="take-hover-line"
              className="pointer-events-none absolute inset-y-0 w-px -translate-x-1/2 bg-muted-foreground"
              style={{ left: `${hover * 100}%` }}
            />
            <span
              aria-hidden
              data-testid="take-hover-time"
              className="pointer-events-none absolute top-0 -translate-x-1/2 rounded border border-border bg-background px-1 font-mono text-xs tabular-nums"
              style={{ left: `${Math.min(92, Math.max(8, hover * 100))}%` }}
            >
              {formatClock(hover * duration)}
            </span>
          </>
        )}
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
function Waveform({
  peaks,
  progress,
  animateIn,
}: {
  peaks: number[];
  progress: number;
  animateIn?: boolean;
}) {
  // Unique per take: several takes can share a page (History), and clip ids are document-global.
  const clipId = `take-played-${useId().replace(/:/g, "")}`;
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
      className={`absolute inset-0 h-full w-full ${animateIn ? "animate-draw-in" : ""}`.trim()}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={0} width={w * progress} height={48} />
        </clipPath>
      </defs>
      <g className="fill-border">{bars}</g>
      <g className="fill-primary" clipPath={`url(#${clipId})`}>
        {bars}
      </g>
    </svg>
  );
}
