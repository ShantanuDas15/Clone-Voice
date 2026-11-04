"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { claimPlayback, releasePlayback } from "@/lib/exclusive-playback";
import type { HomeSample } from "@/lib/home-sample";
import { formatClock } from "@/lib/recording";

function PlayIcon({ playing }: { playing: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      aria-hidden
      focusable="false"
      fill="currentColor"
    >
      {playing ? <path d="M7 5h4v14H7zM13 5h4v14h-4z" /> : <path d="M8 5v14l11-7z" />}
    </svg>
  );
}

/**
 * The glass pill under the home stage (owner-approved mock, UX plan §12.25): the product's own
 * output, played only when the visitor presses Play (nothing loads or plays on arrival). It says
 * plainly that the speech is AI-generated and whose voice it is. The length comes from `sample`,
 * so the pill is complete before any audio is fetched. The waveform itself is the stage above it,
 * which follows `onProgress`.
 */
export function HomeSampleCard({
  sample,
  onPlayingChange,
  onProgress,
}: {
  sample: HomeSample;
  /** Lets the stage react while the clip plays. */
  onPlayingChange?: (playing: boolean) => void;
  /** The playhead as a fraction of the clip, 0..1, for the stage's sweep. */
  onProgress?: (progress: number) => void;
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

  useEffect(() => {
    onProgress?.(progress);
  }, [progress, onProgress]);

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
    <div role="group" aria-labelledby={titleId} className="hx-pill">
      <h2 id={titleId} className="sr-only">
        Hear a sample
      </h2>
      <Button
        onClick={toggle}
        aria-pressed={playing}
        aria-label={playing ? "Pause sample" : "Play sample"}
        data-testid="sample-play"
        className="hx-play"
      >
        <PlayIcon playing={playing} />
      </Button>
      <div className="min-w-0">
        <p className="text-balance text-base font-medium sm:text-lg">“{sample.text}”</p>
        <p className="text-sm text-muted-foreground">{sample.note}</p>
      </div>
      <div className="hx-pill-meta">
        <span className="rounded-full border border-border px-2.5 font-mono text-xs text-muted-foreground">
          AI-generated
        </span>
        <span
          className="font-mono text-xs tabular-nums text-muted-foreground"
          data-testid="sample-time"
        >
          {formatClock(time)} / {formatClock(duration)}
        </span>
      </div>
      {failed ? (
        <Alert tone="danger" className="hx-pill-alert">
          The sample could not be played. Try again.
        </Alert>
      ) : null}
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
