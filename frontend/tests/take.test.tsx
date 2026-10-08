import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Take } from "@/components/take";
import { MAX_DECODE_BYTES, bucketPeaks, computePeaks } from "@/lib/audio-peaks";

describe("bucketPeaks", () => {
  it("takes the loudest sample per slice and scales the loudest bar to 1", () => {
    const samples = new Float32Array([0.1, -0.2, 0.4, 0.0, -0.8, 0.2, 0.0, 0.1]);
    expect(bucketPeaks(samples, 4)).toEqual([0.25, 0.5, 1, 0.125]);
  });

  it("returns null for silence, no data, or no buckets", () => {
    expect(bucketPeaks(new Float32Array(100), 8)).toBeNull();
    expect(bucketPeaks(new Float32Array(0), 8)).toBeNull();
    expect(bucketPeaks(new Float32Array([0.5]), 0)).toBeNull();
  });

  it("copes with fewer samples than bars", () => {
    const out = bucketPeaks(new Float32Array([0.5, 1]), 6);
    expect(out).toHaveLength(6);
    expect(Math.max(...(out ?? []))).toBe(1);
  });
});

describe("computePeaks", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns null instead of throwing when decoding is unavailable or impossible", async () => {
    expect(await computePeaks(new Blob([]))).toBeNull();
    expect(await computePeaks(new Blob([new Uint8Array(MAX_DECODE_BYTES + 1)]))).toBeNull();
    vi.stubGlobal("AudioContext", undefined);
    expect(await computePeaks(new Blob([new Uint8Array(10)]))).toBeNull();
    vi.stubGlobal(
      "AudioContext",
      class {
        decodeAudioData() {
          return Promise.reject(new Error("unsupported codec"));
        }
        close() {
          return Promise.resolve();
        }
      },
    );
    expect(await computePeaks(new Blob([new Uint8Array(10)]))).toBeNull();
  });

  it("decodes through Web Audio and closes the context", async () => {
    const close = vi.fn(() => Promise.resolve());
    vi.stubGlobal(
      "AudioContext",
      class {
        decodeAudioData() {
          return Promise.resolve({ getChannelData: () => new Float32Array([0.5, 1, 0.25, 0.5]) });
        }
        close = close;
      },
    );
    window.AudioContext = globalThis.AudioContext;
    expect(await computePeaks(new Blob([new Uint8Array(10)]), 2)).toEqual([1, 0.5]);
    expect(close).toHaveBeenCalled();
  });
});

describe("Take", () => {
  let play: ReturnType<typeof vi.fn>;
  let pause: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    play = vi.fn(() => Promise.resolve());
    pause = vi.fn();
    Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value: play });
    Object.defineProperty(HTMLMediaElement.prototype, "pause", {
      configurable: true,
      value: pause,
    });
    Object.defineProperty(HTMLMediaElement.prototype, "paused", {
      configurable: true,
      get: () => true,
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  const audioEl = (c: HTMLElement) => c.querySelector("audio") as HTMLAudioElement;
  function setDuration(el: HTMLAudioElement, d: number) {
    Object.defineProperty(el, "duration", { configurable: true, value: d });
    fireEvent.loadedMetadata(el);
  }

  it("shows a play button, a disabled slider and 0:00 / 0:00 until the length is known", () => {
    render(<Take src="blob:x" filename="a.wav" label="Generated speech" />);
    expect(screen.getByRole("button", { name: "Play Generated speech" })).toBeInTheDocument();
    expect(screen.getByRole("slider", { name: "Seek Generated speech" })).toBeDisabled();
    expect(screen.getByTestId("take-time")).toHaveTextContent("0:00 / 0:00");
  });

  it("tracks the playhead in the monospaced timecode and the slider's spoken value", () => {
    const { container } = render(<Take src="blob:x" filename="a.wav" label="Speech" />);
    const el = audioEl(container);
    setDuration(el, 7.4);
    const slider = screen.getByRole("slider", { name: "Seek Speech" });
    expect(slider).toBeEnabled();
    expect(slider).toHaveAttribute("max", "7.4");
    el.currentTime = 3.2;
    fireEvent.timeUpdate(el);
    expect(screen.getByTestId("take-time")).toHaveTextContent("0:03 / 0:07");
    expect(screen.getByTestId("take-time").className).toContain("font-mono");
    expect(slider).toHaveAttribute("aria-valuetext", "0:03 / 0:07");
  });

  it("plays and pauses from the button and reflects the element's state", async () => {
    const { container } = render(<Take src="blob:x" filename="a.wav" label="Speech" />);
    const el = audioEl(container);
    await userEvent.click(screen.getByRole("button", { name: "Play Speech" }));
    expect(play).toHaveBeenCalledTimes(1);
    fireEvent.play(el);
    expect(screen.getByRole("button", { name: "Pause Speech" })).toBeInTheDocument();
    Object.defineProperty(el, "paused", { configurable: true, value: false });
    await userEvent.click(screen.getByRole("button", { name: "Pause Speech" }));
    expect(pause).toHaveBeenCalledTimes(1);
    fireEvent.pause(el);
    expect(screen.getByRole("button", { name: "Play Speech" })).toBeInTheDocument();
  });

  it("seeks the audio from the slider, and resets when it ends", () => {
    const { container } = render(<Take src="blob:x" filename="a.wav" label="Speech" />);
    const el = audioEl(container);
    setDuration(el, 10);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "4" } });
    expect(el.currentTime).toBe(4);
    expect(screen.getByTestId("take-time")).toHaveTextContent("0:04 / 0:10");
    fireEvent.play(el);
    fireEvent.ended(el);
    expect(screen.getByTestId("take-time")).toHaveTextContent("0:00 / 0:10");
    expect(screen.getByRole("button", { name: "Play Speech" })).toBeInTheDocument();
  });

  it("draws the waveform in only when asked, and gives every take its own clip id", async () => {
    vi.stubGlobal(
      "AudioContext",
      class {
        decodeAudioData() {
          return Promise.resolve({ getChannelData: () => new Float32Array([0.2, 1, 0.5, 0.1]) });
        }
        close() {
          return Promise.resolve();
        }
      },
    );
    window.AudioContext = globalThis.AudioContext;
    const blob = () => new Blob([new Uint8Array(10)]);
    const { container } = render(
      <>
        <Take src="blob:a" blob={blob()} filename="a.wav" label="A" animateIn />
        <Take src="blob:b" blob={blob()} filename="b.wav" label="B" />
      </>,
    );
    await waitFor(() => expect(container.querySelectorAll("svg")).toHaveLength(2));
    const [first, second] = [...container.querySelectorAll("svg")];
    expect(first?.getAttribute("class")).toContain("animate-draw-in");
    expect(second?.getAttribute("class")).not.toContain("animate-draw-in");
    const ids = [...container.querySelectorAll("clipPath")].map((c) => c.id);
    expect(new Set(ids).size).toBe(2);
    for (const svg of [first, second]) {
      const id = svg?.querySelector("clipPath")?.id;
      expect(svg?.querySelector(`[clip-path="url(#${id})"]`)).not.toBeNull();
    }
  });

  it("jumps 2 s with the arrow keys and stays within the clip", () => {
    const { container } = render(<Take src="blob:x" filename="a.wav" label="Speech" />);
    const el = audioEl(container);
    setDuration(el, 5);
    const slider = screen.getByRole("slider");
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(el.currentTime).toBe(2);
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(el.currentTime).toBe(5);
    fireEvent.keyDown(slider, { key: "ArrowLeft" });
    expect(el.currentTime).toBe(3);
    for (let i = 0; i < 5; i += 1) fireEvent.keyDown(slider, { key: "ArrowLeft" });
    expect(el.currentTime).toBe(0);
  });

  it("says it cannot play and keeps the download when the audio errors", () => {
    const { container } = render(<Take src="blob:x" filename="a.wav" label="Speech" />);
    fireEvent.error(audioEl(container));
    expect(screen.getByRole("alert")).toHaveTextContent(/couldn't be played/i);
    expect(screen.getByRole("link", { name: "Download WAV" })).toHaveAttribute("download", "a.wav");
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("can omit the download link", () => {
    render(<Take src="blob:x" filename="a.wav" label="Speech" hideDownload />);
    expect(screen.queryByRole("link", { name: "Download WAV" })).toBeNull();
  });

  it("draws a decorative waveform when the audio can be decoded, and works without one", async () => {
    vi.stubGlobal(
      "AudioContext",
      class {
        decodeAudioData() {
          return Promise.resolve({ getChannelData: () => new Float32Array([0.2, 1, 0.5, 0.1]) });
        }
        close() {
          return Promise.resolve();
        }
      },
    );
    window.AudioContext = globalThis.AudioContext;
    const { container, rerender } = render(
      <Take src="blob:x" blob={new Blob([new Uint8Array(10)])} filename="a.wav" label="Speech" />,
    );
    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull());
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelectorAll("svg rect").length).toBeGreaterThan(64);

    vi.stubGlobal("AudioContext", undefined);
    window.AudioContext = undefined as unknown as typeof AudioContext;
    rerender(
      <Take src="blob:y" blob={new Blob([new Uint8Array(11)])} filename="a.wav" label="Speech" />,
    );
    await waitFor(() => expect(container.querySelector("svg")).toBeNull());
    expect(screen.getByRole("button", { name: "Play Speech" })).toBeInTheDocument();
  });
});
