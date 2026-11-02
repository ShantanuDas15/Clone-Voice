import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SILENT_AFTER_MS,
  TRACE_BARS,
  TRACE_STEP_MS,
  TRACE_STEP_REDUCED_MS,
  rmsLevel,
  useInputLevel,
  useLevelTrace,
} from "@/hooks/use-input-level";

describe("rmsLevel", () => {
  it("is 0 for silence and for no data", () => {
    expect(rmsLevel(new Uint8Array(64).fill(128))).toBe(0);
    expect(rmsLevel(new Uint8Array(0))).toBe(0);
  });

  it("grows with loudness and is capped at 1", () => {
    const quiet = new Uint8Array(64).fill(128).map((_, i) => (i % 2 ? 136 : 120));
    const loud = new Uint8Array(64).fill(128).map((_, i) => (i % 2 ? 250 : 6));
    expect(rmsLevel(quiet)).toBeGreaterThan(0);
    expect(rmsLevel(loud)).toBeGreaterThan(rmsLevel(quiet));
    expect(rmsLevel(loud)).toBe(1);
  });
});

describe("useInputLevel", () => {
  let frames: Array<(t: number) => void>;
  let amplitude: number;
  let closed: ReturnType<typeof vi.fn>;
  let disconnected: ReturnType<typeof vi.fn>;
  const stream = {} as MediaStream;

  /** Run one animation frame at `t` ms. */
  const frame = (t: number) => act(() => frames.shift()?.(t));

  beforeEach(() => {
    frames = [];
    amplitude = 0;
    closed = vi.fn(() => Promise.resolve());
    disconnected = vi.fn();
    vi.stubGlobal("requestAnimationFrame", (cb: (t: number) => void) => frames.push(cb));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    class Ctx {
      createMediaStreamSource() {
        return { connect: vi.fn(), disconnect: disconnected };
      }
      createAnalyser() {
        return {
          fftSize: 0,
          getByteTimeDomainData: (data: Uint8Array) =>
            data.forEach((_, i) => (data[i] = i % 2 ? 128 + amplitude : 128 - amplitude)),
        };
      }
      resume = () => Promise.resolve();
      close = closed;
    }
    window.AudioContext = Ctx as unknown as typeof AudioContext;
    window.matchMedia = vi.fn(() => ({ matches: false })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => vi.unstubAllGlobals());

  it("stays at 0 with no stream, and without Web Audio", () => {
    expect(renderHook(() => useInputLevel(null)).result.current).toEqual({
      level: 0,
      silent: false,
    });
    window.AudioContext = undefined as unknown as typeof AudioContext;
    expect(renderHook(() => useInputLevel(stream)).result.current).toEqual({
      level: 0,
      silent: false,
    });
  });

  it("follows the microphone and decays instead of flickering", () => {
    const { result } = renderHook(() => useInputLevel(stream));
    amplitude = 60;
    frame(16);
    const loud = result.current.level;
    expect(loud).toBeGreaterThan(0.5);
    amplitude = 0;
    frame(32);
    expect(result.current.level).toBeLessThan(loud);
    expect(result.current.level).toBeGreaterThan(0);
  });

  it("reports silence only after it has lasted a few seconds, and clears when sound returns", () => {
    const { result } = renderHook(() => useInputLevel(stream));
    frame(0);
    frame(SILENT_AFTER_MS - 100);
    expect(result.current.silent).toBe(false);
    frame(SILENT_AFTER_MS + 100);
    expect(result.current.silent).toBe(true);
    amplitude = 60;
    frame(SILENT_AFTER_MS + 200);
    expect(result.current.silent).toBe(false);
  });

  it("samples only every 250 ms under reduced motion", () => {
    window.matchMedia = vi.fn(() => ({ matches: true })) as unknown as typeof window.matchMedia;
    const { result } = renderHook(() => useInputLevel(stream));
    amplitude = 60;
    frame(0);
    const first = result.current.level;
    amplitude = 0;
    frame(100); // skipped
    expect(result.current.level).toBe(first);
    frame(300);
    expect(result.current.level).toBeLessThan(first);
  });

  it("releases the audio graph when the stream goes away", () => {
    const { unmount } = renderHook(() => useInputLevel(stream));
    unmount();
    expect(disconnected).toHaveBeenCalled();
    expect(closed).toHaveBeenCalled();
  });
});

describe("useLevelTrace", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    window.matchMedia = vi.fn(() => ({ matches: false })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => vi.useRealTimers());

  it("is flat while not active, and has a fixed number of bars", () => {
    const { result } = renderHook(() => useLevelTrace(0.8, false));
    act(() => void vi.advanceTimersByTime(TRACE_STEP_MS * 5));
    expect(result.current).toHaveLength(TRACE_BARS);
    expect(result.current.every((v) => v === 0)).toBe(true);
  });

  it("scrolls: the newest level enters on the right and the oldest drops off the left", () => {
    const { result, rerender } = renderHook(({ level }) => useLevelTrace(level, true, 4), {
      initialProps: { level: 0.5 },
    });
    act(() => void vi.advanceTimersByTime(TRACE_STEP_MS));
    expect(result.current).toEqual([0, 0, 0, 0.5]);
    rerender({ level: 1 });
    act(() => void vi.advanceTimersByTime(TRACE_STEP_MS));
    expect(result.current).toEqual([0, 0, 0.5, 1]);
    act(() => void vi.advanceTimersByTime(TRACE_STEP_MS * 3));
    expect(result.current).toEqual([1, 1, 1, 1]);
  });

  it("clears when it stops being active", () => {
    const { result, rerender } = renderHook(({ on }) => useLevelTrace(0.6, on, 3), {
      initialProps: { on: true },
    });
    act(() => void vi.advanceTimersByTime(TRACE_STEP_MS * 3));
    expect(result.current).toEqual([0.6, 0.6, 0.6]);
    rerender({ on: false });
    expect(result.current).toEqual([0, 0, 0]);
  });

  it("steps more slowly when the user prefers reduced motion", () => {
    window.matchMedia = vi.fn(() => ({ matches: true })) as unknown as typeof window.matchMedia;
    const { result } = renderHook(() => useLevelTrace(0.7, true, 3));
    act(() => void vi.advanceTimersByTime(TRACE_STEP_MS * 3));
    expect(result.current).toEqual([0, 0, 0]);
    act(() => void vi.advanceTimersByTime(TRACE_STEP_REDUCED_MS));
    expect(result.current).toEqual([0, 0, 0.7]);
  });
});
