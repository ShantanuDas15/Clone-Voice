"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useObjectUrl } from "@/hooks/use-object-url";
import { useInputLevel } from "@/hooks/use-input-level";
import { useRecorder } from "@/hooks/use-recorder";
import { RECORDING_PROMPTS } from "@/lib/recording-prompts";
import {
  MAX_RECORDING_SECONDS,
  MIN_RECORDING_SECONDS,
  formatClock,
  recordingToFile,
} from "@/lib/recording";
import { Button } from "@/components/ui/button";
import { Take } from "@/components/take";
import { token } from "@/components/voice-canvas";

interface RecorderProps {
  /** Called with the finished take, or null when it is discarded or fails. */
  onChange: (file: File | null) => void;
  disabled?: boolean;
}

/** Seconds of speech that work best for a clone; shown as guidance while recording. */
const BEST_FROM_SECONDS = 10;
const BEST_TO_SECONDS = 30;

function MicIcon() {
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="currentColor"
    >
      <path d="M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4Zm6-4a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.9V19H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-2.1A6 6 0 0 0 18 11Z" />
    </svg>
  );
}

/** A line to read for someone who does not know what to say; "Show another line" steps through them. */
function ReadingPrompt({ recording }: { recording: boolean }) {
  const [index, setIndex] = useState(0);
  return (
    <div className="bx-tele">
      <p className="bx-tele-hint">
        {recording
          ? "Read this line, or say anything natural"
          : "If you're not sure what to say, try reading"}
      </p>
      <p className="bx-tele-text" data-testid="reading-prompt">
        “{RECORDING_PROMPTS[index]}”
      </p>
      <Button
        variant="quiet"
        size="sm"
        onClick={() => setIndex((i) => (i + 1) % RECORDING_PROMPTS.length)}
      >
        Show another line
      </Button>
    </div>
  );
}

/** Bars in the voiceprint and the seconds of speech that fill it. */
const PRINT_BARS = 150;
const PRINT_GOAL_SECONDS = 30;

/**
 * The voiceprint of the take: 150 resting bars that light up from the left as the take goes on, one
 * per fifth of a second of the 30 that work best, as tall as the microphone level was at that moment.
 * It keeps its bars after stopping (`keep`) and starts again from rest after a discard. Drawn on a
 * canvas, so no inline styles; decorative (the meter and the clock carry the information).
 */
function RecordPrint({ level, active, keep }: { level: number; active: boolean; keep: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const bars = useRef<number[]>([]);
  const latest = useRef(level);
  useEffect(() => {
    latest.current = level;
  }, [level]);

  const paint = useCallback(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const box = el.getBoundingClientRect();
    if (el.width !== Math.round(box.width * dpr)) {
      el.width = Math.round(box.width * dpr);
      el.height = Math.round(box.height * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, box.width, box.height);
    const step = box.width / PRINT_BARS;
    const rest = token("--border");
    const lit = token("--primary");
    const hot = token("--warning-foreground");
    const clip = token("--danger");
    for (let i = 0; i < PRINT_BARS; i++) {
      const v = bars.current[i];
      const h =
        v === undefined ? 5 + Math.abs(Math.sin(i * 0.35)) * 6 : Math.max(4, v * (box.height - 28));
      ctx.fillStyle = v === undefined ? rest : v > 0.96 ? clip : v > 0.86 ? hot : lit;
      ctx.fillRect(i * step + step * 0.2, (box.height - h) / 2, Math.max(1.5, step * 0.6), h);
    }
  }, []);

  useEffect(() => {
    if (!active && !keep) bars.current = [];
    paint();
  }, [active, keep, paint]);

  useEffect(() => {
    if (!active) return;
    bars.current = [];
    const started = performance.now();
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const id = setInterval(
      () => {
        const seconds = (performance.now() - started) / 1000;
        const at = Math.min(
          PRINT_BARS - 1,
          Math.floor((seconds / PRINT_GOAL_SECONDS) * PRINT_BARS),
        );
        const now = Math.max(0.06, latest.current);
        for (let i = 0; i < at; i++) bars.current[i] ??= now * 0.85;
        bars.current[at] = Math.max(bars.current[at] ?? 0, now);
        paint();
      },
      reduce ? 250 : 100,
    );
    return () => clearInterval(id);
  }, [active, paint]);

  useEffect(() => {
    const el = canvas.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const watcher = new ResizeObserver(paint);
    watcher.observe(el);
    return () => watcher.disconnect();
  }, [paint]);

  return <canvas ref={canvas} aria-hidden className="bx-print-canvas" />;
}

const METER_SEGMENTS = 12;

/** The record / stop button: a ring that fills toward the 30 seconds that work best, around a core. */
function RecButton({
  recording,
  seconds,
  label,
  onClick,
  disabled,
}: {
  recording: boolean;
  seconds: number;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  const circumference = 2 * Math.PI * 45;
  const filled = Math.min(1, seconds / PRINT_GOAL_SECONDS);
  return (
    <button
      type="button"
      className="bx-rec"
      data-rec={recording}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
    >
      <svg aria-hidden focusable="false" viewBox="0 0 96 96" className="bx-rec-ring">
        <circle className="bx-rec-track" cx="48" cy="48" r="45" fill="none" strokeWidth="3" />
        <circle
          className="bx-rec-fill"
          cx="48"
          cy="48"
          r="45"
          fill="none"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - filled)}
        />
      </svg>
      {recording && <span aria-hidden className="bx-rec-pulse" />}
      <span aria-hidden className="bx-rec-core">
        {recording ? null : <MicIcon />}
      </span>
    </button>
  );
}

/** How the recording is going, in words: too short, long enough, or the length that works best. */
function lengthGuidance(seconds: number): string {
  if (seconds < MIN_RECORDING_SECONDS) {
    return `Keep going: at least ${MIN_RECORDING_SECONDS} seconds are needed.`;
  }
  if (seconds < BEST_FROM_SECONDS) {
    return `Long enough to stop. ${BEST_FROM_SECONDS}–${BEST_TO_SECONDS} seconds works best.`;
  }
  if (seconds <= BEST_TO_SECONDS) {
    return `Good length. ${BEST_FROM_SECONDS}–${BEST_TO_SECONDS} seconds works best.`;
  }
  return "Long enough. You can stop whenever you like.";
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
  const recording = state.phase === "recording";
  const lit = Math.round((silent ? 0 : level) * METER_SEGMENTS);
  const printTag =
    state.phase === "recording"
      ? "Listening"
      : state.phase === "stopped"
        ? "Your take"
        : state.phase === "requesting"
          ? "Waiting for permission"
          : "Press record and start reading";

  return (
    <div className="bx-booth">
      {state.phase === "idle" && (
        <p className="bx-intro">
          Record {MIN_RECORDING_SECONDS}–{MAX_RECORDING_SECONDS} seconds of clear speech in a quiet
          room. {BEST_FROM_SECONDS}–{BEST_TO_SECONDS} seconds works best.
        </p>
      )}

      {state.phase !== "error" && (
        <div className="bx-print">
          <RecordPrint
            level={silent ? 0 : level}
            active={recording}
            keep={state.phase === "stopped"}
          />
          <span aria-hidden className="bx-print-tag">
            {printTag}
          </span>
          <span aria-hidden className="bx-print-goal">
            goal {BEST_TO_SECONDS} s
          </span>
        </div>
      )}

      {state.phase === "idle" && (
        <div className="bx-ctrl">
          <p aria-hidden className="bx-clock">
            0:00
          </p>
          <RecButton
            recording={false}
            seconds={0}
            label="Start recording"
            onClick={() => void start()}
            disabled={disabled}
          />
          <span />
        </div>
      )}

      {state.phase === "requesting" && (
        <div className="bx-row">
          <p role="status">Waiting for microphone permission…</p>
          <Button variant="secondary" onClick={discard}>
            Cancel
          </Button>
        </div>
      )}

      {recording && (
        <>
          <div className="bx-ctrl">
            <p role="status" aria-live="off" className="bx-clock">
              Recording {formatClock(seconds)} / {formatClock(MAX_RECORDING_SECONDS)}
            </p>
            <RecButton
              recording
              seconds={seconds}
              label="Stop recording"
              onClick={stop}
              disabled={!canStop}
            />
            {/* The segments are the meter: they are decorative, the role carries the level. */}
            <div
              role="meter"
              aria-label="Microphone level"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(level * 100)}
              className="bx-vu"
            >
              {Array.from({ length: METER_SEGMENTS }, (_, i) => (
                <span
                  key={i}
                  aria-hidden
                  data-on={i < lit}
                  data-zone={i >= 11 ? "clip" : i >= 10 ? "hot" : i >= 7 ? "band" : "low"}
                  className="bx-vu-seg"
                />
              ))}
            </div>
          </div>
          {silent && (
            <p role="status" className="bx-note">
              We can&apos;t hear anything. Check that the right microphone is selected and not
              muted.
            </p>
          )}
          <p className={canStop ? "bx-length bx-length-ok" : "bx-length"}>
            {lengthGuidance(seconds)}
          </p>
          <div className="bx-row">
            <Button variant="secondary" onClick={discard}>
              Discard
            </Button>
          </div>
        </>
      )}

      {state.phase === "stopped" && (
        <div className="space-y-3">
          <p role="status" className="bx-length bx-length-ok">
            Recorded {formatClock(state.seconds)}. Listen before you upload.
          </p>
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
        </div>
      )}

      {state.phase === "error" && (
        <div className="bx-row">
          <p role="alert">{state.message}</p>
          <Button variant="secondary" onClick={() => void start()}>
            Try again
          </Button>
        </div>
      )}

      {(state.phase === "idle" || recording) && <ReadingPrompt recording={recording} />}
      {state.phase === "idle" && (
        <ul className="bx-tips" aria-label="Recording tips">
          <li>Quiet room</li>
          <li>Hand&apos;s length from the mic</li>
          <li>No music or fans</li>
        </ul>
      )}
    </div>
  );
}
