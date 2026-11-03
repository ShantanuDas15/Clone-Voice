import { type RefObject, useEffect } from "react";

import type { Envelope } from "@/lib/audio-peaks";
import {
  PULSE_FRAME_MS,
  PULSE_REACH,
  WAVE_HEIGHT,
  levelAt,
  pulseBar,
  smoothLevel,
} from "@/lib/playback-pulse";

/** True when the user asked the system for less motion; the pulse then never starts. */
export function prefersReducedMotion(): boolean {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

/**
 * Drive the playback pulse (UX plan §12.22). While `active`, about 30 times a second, it reads the
 * playhead from the `<audio>` element, looks up how loud the take is there (`envelope`, computed
 * from the same decode that draws the waveform, so the player's audio path is never touched), and
 * moves the `<rect>` children (one per pulse bar) of `layer` accordingly.
 *
 * The bars are changed through SVG attributes (`x`, `y`, `height`, `opacity`), straight on the DOM:
 * no React render per frame, no `style` attribute (the site's Content-Security-Policy forbids
 * those in server-rendered markup), no layout. The loop runs only while the take plays and the tab
 * is visible, stops at once when it pauses or ends, and does not start at all under
 * `prefers-reduced-motion`. When it stops, every bar is hidden again.
 */
export function usePlaybackPulse({
  audio,
  layer,
  envelope,
  peaks,
  active,
}: {
  audio: RefObject<HTMLAudioElement | null>;
  layer: RefObject<SVGGElement | null>;
  envelope: Envelope | null;
  peaks: number[] | null;
  /** True while the take is playing and the pulse is wanted. */
  active: boolean;
}): void {
  useEffect(() => {
    const element = audio.current;
    const group = layer.current;
    if (!active || !element || !group || !envelope || !peaks || peaks.length === 0) return;
    if (prefersReducedMotion()) return;

    const bars = Array.from(group.children) as SVGRectElement[];
    const hide = () => bars.forEach((bar) => bar.setAttribute("opacity", "0"));
    let frameId = 0;
    let lastDraw = 0;
    let level = 0;
    let stopped = false;

    const draw = () => {
      const duration = element.duration;
      if (!Number.isFinite(duration) || duration <= 0) return;
      const seconds = element.currentTime;
      level = smoothLevel(level, levelAt(envelope, seconds));
      const centre = (seconds / duration) * peaks.length;
      const first = Math.floor(centre) - PULSE_REACH;
      bars.forEach((bar, slot) => {
        const index = first + slot;
        const peak = peaks[index];
        if (peak === undefined) {
          bar.setAttribute("opacity", "0");
          return;
        }
        const shape = pulseBar(index, centre, level, peak);
        bar.setAttribute("x", String(index * 4 + 0.5));
        bar.setAttribute("y", (WAVE_HEIGHT / 2 - shape.height / 2).toFixed(2));
        bar.setAttribute("height", shape.height.toFixed(2));
        bar.setAttribute("opacity", shape.opacity.toFixed(2));
      });
    };

    const frame = (now: number) => {
      if (stopped || document.hidden) return; // resumed by `onVisible`
      if (now - lastDraw >= PULSE_FRAME_MS) {
        lastDraw = now;
        draw();
      }
      frameId = requestAnimationFrame(frame);
    };
    const onVisible = () => {
      if (document.hidden || stopped) return;
      cancelAnimationFrame(frameId);
      frameId = requestAnimationFrame(frame);
    };
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const onMotionChange = () => {
      if (!query?.matches) return;
      stopped = true;
      cancelAnimationFrame(frameId);
      hide();
    };

    document.addEventListener("visibilitychange", onVisible);
    query?.addEventListener?.("change", onMotionChange);
    frameId = requestAnimationFrame(frame);
    return () => {
      stopped = true;
      cancelAnimationFrame(frameId);
      document.removeEventListener("visibilitychange", onVisible);
      query?.removeEventListener?.("change", onMotionChange);
      hide();
    };
  }, [audio, layer, envelope, peaks, active]);
}
