"use client";

import { useEffect, useState } from "react";

/** Below this (0..1) the microphone is treated as silent. */
export const SILENT_LEVEL = 0.02;
/** How long it must stay silent before we say so. */
export const SILENT_AFTER_MS = 3000;

/** Loudness 0..1 of one analyser frame (unsigned 8-bit time-domain samples centred on 128). */
export function rmsLevel(data: Uint8Array): number {
  if (data.length === 0) return 0;
  let sum = 0;
  for (const v of data) {
    const centred = (v - 128) / 128;
    sum += centred * centred;
  }
  // Speech sits around 0.05-0.2 RMS; scale so normal talking fills most of the meter.
  return Math.min(1, Math.sqrt(sum / data.length) * 4);
}

type AudioContextCtor = typeof AudioContext;

/**
 * Live input level of a microphone stream, for a meter. It reads an `AnalyserNode` once per
 * animation frame (every 250 ms when the user prefers reduced motion), keeps a short decay so the
 * meter does not flicker, and reports `silent` when nothing has been heard for a few seconds.
 * Without Web Audio the level stays 0 and the recorder works as before.
 */
export function useInputLevel(stream: MediaStream | null): { level: number; silent: boolean } {
  const [level, setLevel] = useState(0);
  const [silent, setSilent] = useState(false);

  useEffect(() => {
    setLevel(0);
    setSilent(false);
    if (!stream) return;
    const Ctor: AudioContextCtor | undefined =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
    if (!Ctor) return;

    let ctx: AudioContext;
    try {
      ctx = new Ctor();
    } catch {
      return;
    }
    const source = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    source.connect(analyser);
    void ctx.resume().catch(() => undefined);

    const data = new Uint8Array(analyser.fftSize);
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    let frame = 0;
    let last = -Infinity;
    let smoothed = 0;
    let quietSince: number | null = null;

    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      if (reduce && now - last < 250) return;
      last = now;
      analyser.getByteTimeDomainData(data);
      const raw = rmsLevel(data);
      smoothed = Math.max(raw, smoothed * 0.85);
      setLevel(Math.round(smoothed * 20) / 20); // 20 steps: fewer renders, no visible loss
      if (raw < SILENT_LEVEL) {
        quietSince ??= now;
        setSilent(now - quietSince >= SILENT_AFTER_MS);
      } else {
        quietSince = null;
        setSilent(false);
      }
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      source.disconnect();
      void ctx.close().catch(() => undefined);
    };
  }, [stream]);

  return { level, silent };
}
