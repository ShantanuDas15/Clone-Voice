"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { claimPlayback, releasePlayback } from "@/lib/exclusive-playback";
import { drawDelay } from "@/lib/home-backdrop";
import type { HomeSample } from "@/lib/home-sample";
import { formatClock } from "@/lib/recording";

/** Bar height range, in SVG units of a 32-high box (matches the History waveform preview). */
const MAX_BAR = 30;

function PlayIcon({ playing }: { playing: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      aria-hidden
      focusable="false"
      fill="currentColor"
    >
      {playing ? <path d="M7 5h4v14H7zM13 5h4v14h-4z" /> : <path d="M8 5v14l11-7z" />}
    </svg>
  );
}

/**
 * The clip's shape; bars up to the playhead take the accent colour. Each bar grows from its own
 * centre once, left to right, as the card appears. Decorative (`aria-hidden`).
 */
function Wave({ peaks, progress }: { peaks: readonly number[]; progress: number }) {
  const played = Math.floor(progress * peaks.length);
  return (
    <svg
      aria-hidden
      focusable="false"
      data-testid="sample-wave"
      viewBox={`0 0 ${peaks.length * 4} 32`}
      preserveAspectRatio="none"
      className="h-[72px] w-full"
    >
      {peaks.map((p, i) => {
        const h = Math.max(2, (Math.min(100, Math.max(0, p)) / 100) * MAX_BAR);
        return (
          <rect
            key={i}
            x={i * 4 + 0.5}
            y={16 - h / 2}
            width={3}
            height={h}
            rx={1.5}
            className={`origin-center [transform-box:fill-box] motion-safe:animate-bar-in ${drawDelay(i, 4)} ${
              i < played ? "fill-primary" : "fill-muted-foreground/50"
            }`}
          />
        );
      })}
    </svg>
  );
}

/**
 * A clip of the product's own output, played only when the visitor presses Play (nothing loads or
 * plays on arrival). It says plainly that the speech is AI-generated and whose voice it is. The
 * length and shape come from `sample`, so the card is complete before any audio is fetched.
 */
export function HomeSampleCard({
  sample,
  onPlayingChange,
}: {
  sample: HomeSample;
  /** Lets the page's background react while the clip plays. */
  onPlayingChange?: (playing: boolean) => void;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const titleId = useId();
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    onPlayingChange?.(playing);
  }, [playing, onPlayingChange]);

  useEffect(() => {
    const el = audio.current;
    return () => {
      if (el) releasePlayback(el);
    };
  }, []);

  // The element reports its own length once loaded; until then the configured length stands in.
  const [measured, setMeasured] = useState(0);
  const duration = measured > 0 ? measured : sample.durationSeconds;
  const progress = duration > 0 ? Math.min(1, time / duration) : 0;

  function toggle() {
    const el = audio.current;
    if (!el) return;
    if (el.paused) {
      claimPlayback(el);
      setFailed(false);
      void Promise.resolve(el.play()).catch(() => {
        setPlaying(false);
        setFailed(true);
      });
    } else {
      el.pause();
    }
  }

  return (
    <div
      role="group"
      aria-labelledby={titleId}
      className="rounded-lg border border-border bg-surface p-5 motion-safe:animate-rise motion-safe:[animation-delay:80ms] sm:p-6"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id={titleId} className="font-medium">
          Hear a sample
        </h2>
        <span className="rounded-full bg-muted px-2.5 py-1 font-mono text-xs text-muted-foreground">
          AI-generated
        </span>
      </div>
      <p className="mt-4 text-balance text-xl leading-snug">“{sample.text}”</p>
      <div className="mt-5">
        <Wave peaks={sample.peaks} progress={progress} />
      </div>
      <div className="mt-4 flex items-center gap-3">
        <Button onClick={toggle} aria-pressed={playing} data-testid="sample-play">
          <span className="mr-2 inline-flex">
            <PlayIcon playing={playing} />
          </span>
          {playing ? "Pause sample" : "Play sample"}
        </Button>
        <span
          className="font-mono text-sm tabular-nums text-muted-foreground"
          data-testid="sample-time"
        >
          {formatClock(time)} / {formatClock(duration)}
        </span>
      </div>
      {failed ? (
        <Alert tone="danger" className="mt-3">
          The sample could not be played. Try again.
        </Alert>
      ) : null}
      <p className="mt-4 text-sm text-muted-foreground">{sample.note}</p>
      <audio
        ref={audio}
        src={sample.src}
        preload="none"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false);
          setTime(0);
        }}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          if (Number.isFinite(e.currentTarget.duration)) setMeasured(e.currentTarget.duration);
        }}
        onError={() => {
          setPlaying(false);
          setFailed(true);
        }}
      />
    </div>
  );
}
