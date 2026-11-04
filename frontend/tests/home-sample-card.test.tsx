import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HomeSampleCard } from "@/components/home-sample-card";
import type { HomeSample } from "@/lib/home-sample";

const sample: HomeSample = {
  src: "/samples/home-sample.wav",
  text: "Hello, this is a voice made from a short sample.",
  durationSeconds: 2.9,
  peaks: [10, 50, 100, 50, 10, 0, 30, 80],
  note: "Cloned from an 8-second recording, with the speaker's consent.",
};

describe("HomeSampleCard", () => {
  let play: ReturnType<typeof vi.fn>;
  let pause: ReturnType<typeof vi.fn>;
  let paused = true;

  beforeEach(() => {
    paused = true;
    play = vi.fn(() => {
      paused = false;
      return Promise.resolve();
    });
    pause = vi.fn(() => {
      paused = true;
    });
    Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value: play });
    Object.defineProperty(HTMLMediaElement.prototype, "pause", {
      configurable: true,
      value: pause,
    });
    Object.defineProperty(HTMLMediaElement.prototype, "paused", {
      configurable: true,
      get: () => paused,
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  const audio = (c: HTMLElement) => c.querySelector("audio") as HTMLAudioElement;

  it("says what it is: a quote, an AI-generated tag, the source, and the length before any audio loads", () => {
    const { container } = render(<HomeSampleCard sample={sample} />);
    expect(screen.getByRole("group", { name: "Hear a sample" })).toBeInTheDocument();
    expect(screen.getByText(`“${sample.text}”`)).toBeInTheDocument();
    expect(screen.getByText("AI-generated")).toBeInTheDocument();
    expect(screen.getByText(sample.note)).toBeInTheDocument();
    expect(screen.getByTestId("sample-time")).toHaveTextContent("0:00 / 0:02");
    // Nothing is fetched or played until Play is pressed.
    expect(audio(container)).toHaveAttribute("preload", "none");
    expect(audio(container)).not.toHaveAttribute("autoplay");
    expect(play).not.toHaveBeenCalled();
  });

  it("draws its waveform in, bar by bar from the left, and only where motion is allowed", () => {
    render(<HomeSampleCard sample={sample} />);
    const bars = [...screen.getByTestId("sample-wave").querySelectorAll(":scope > rect")];
    expect(bars).toHaveLength(sample.peaks.length);
    for (const bar of bars) {
      const cls = bar.getAttribute("class")!;
      expect(cls).toContain("motion-safe:animate-bar-in");
      expect(cls).toContain("[transform-box:fill-box]"); // each bar grows from its own centre
      expect(bar.getAttribute("style")).toBeNull(); // the site's CSP forbids inline styles
    }
    const delay = (el: Element) =>
      Number(/animation-delay:(\d+)ms/.exec(el.getAttribute("class")!)?.[1]);
    expect(delay(bars[0]!)).toBe(160);
    expect(delay(bars[bars.length - 1]!)).toBeGreaterThanOrEqual(delay(bars[0]!));
  });

  it("plays on a press, shows Pause, and tells the page it is playing", async () => {
    const onPlayingChange = vi.fn();
    const { container } = render(
      <HomeSampleCard sample={sample} onPlayingChange={onPlayingChange} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Play sample" }));
    expect(play).toHaveBeenCalledTimes(1);
    fireEvent.play(audio(container));
    expect(screen.getByRole("button", { name: "Pause sample" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(onPlayingChange).toHaveBeenLastCalledWith(true);

    await userEvent.click(screen.getByRole("button", { name: "Pause sample" }));
    expect(pause).toHaveBeenCalledTimes(1);
    fireEvent.pause(audio(container));
    expect(screen.getByRole("button", { name: "Play sample" })).toBeInTheDocument();
    expect(onPlayingChange).toHaveBeenLastCalledWith(false);
  });

  it("fills the played bars and advances the clock with the playhead", () => {
    const { container } = render(<HomeSampleCard sample={sample} />);
    const el = audio(container);
    Object.defineProperty(el, "currentTime", { configurable: true, value: 1.45 });
    fireEvent.timeUpdate(el);
    expect(screen.getByTestId("sample-time")).toHaveTextContent("0:01 / 0:02");
    const filled = screen.getByTestId("sample-wave").querySelectorAll("rect.fill-primary");
    expect(filled).toHaveLength(4); // half of the 8 bars
  });

  it("uses the browser's own length once it is known, and resets when the clip ends", () => {
    const { container } = render(<HomeSampleCard sample={sample} />);
    const el = audio(container);
    Object.defineProperty(el, "duration", { configurable: true, value: 3.4 });
    fireEvent.loadedMetadata(el);
    expect(screen.getByTestId("sample-time")).toHaveTextContent("0:00 / 0:03");
    Object.defineProperty(el, "currentTime", { configurable: true, value: 3.4 });
    fireEvent.timeUpdate(el);
    fireEvent.ended(el);
    expect(screen.getByTestId("sample-time")).toHaveTextContent("0:00 / 0:03");
    expect(screen.getByRole("button", { name: "Play sample" })).toBeInTheDocument();
  });

  it("says so, and stays usable, when the clip cannot be played", async () => {
    play.mockImplementationOnce(() => Promise.reject(new Error("blocked")));
    render(<HomeSampleCard sample={sample} />);
    await userEvent.click(screen.getByRole("button", { name: "Play sample" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The sample could not be played");
    expect(screen.getByRole("button", { name: "Play sample" })).toBeEnabled();
  });

  it("pauses the clip another take claims, so two never play at once", async () => {
    const { container } = render(<HomeSampleCard sample={sample} />);
    await userEvent.click(screen.getByRole("button", { name: "Play sample" }));
    const other = document.createElement("audio");
    const { claimPlayback } = await import("@/lib/exclusive-playback");
    claimPlayback(other);
    expect(pause).toHaveBeenCalled();
    expect(audio(container)).toBeTruthy();
  });

  describe("the playback pulse", () => {
    let queue: Array<[number, FrameRequestCallback]>;
    let now: number;
    beforeEach(() => {
      queue = [];
      now = 0;
      let id = 1;
      vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
        queue.push([id, cb]);
        return id++;
      });
      vi.stubGlobal("cancelAnimationFrame", (n: number) => {
        queue = queue.filter(([i]) => i !== n);
      });
      vi.stubGlobal(
        "fetch",
        vi.fn(() =>
          Promise.resolve({ blob: () => Promise.resolve(new Blob([new Uint8Array(8)])) }),
        ),
      );
      const samples = new Float32Array(2000).fill(1);
      vi.stubGlobal(
        "AudioContext",
        class {
          decodeAudioData() {
            return Promise.resolve({ sampleRate: 1000, getChannelData: () => samples });
          }
          close() {
            return Promise.resolve();
          }
        },
      );
      window.AudioContext = globalThis.AudioContext;
    });
    const lit = () =>
      [...screen.getByTestId("sample-pulse").children].filter(
        (b) => Number(b.getAttribute("opacity")) > 0,
      );

    it("is hidden until the clip plays, then lights the bars at the playhead, and hides on pause", async () => {
      const { container } = render(<HomeSampleCard sample={sample} />);
      expect(lit()).toHaveLength(0);
      expect(screen.getByTestId("sample-pulse").querySelectorAll("[style]")).toHaveLength(0);
      const el = audio(container);
      Object.defineProperty(el, "duration", { configurable: true, value: 2.9 });
      fireEvent.loadedMetadata(el);
      await userEvent.click(screen.getByRole("button", { name: "Play sample" }));
      fireEvent.play(el);
      expect(fetch).toHaveBeenCalledWith(sample.src);
      // The loudness is read once the clip has been analysed; then the loop runs.
      await waitFor(() => {
        act(() => {
          now += 40;
          const due = queue;
          queue = [];
          due.forEach(([, cb]) => cb(now));
        });
        expect(lit().length).toBeGreaterThan(0);
      });
      fireEvent.pause(el);
      expect(lit()).toHaveLength(0);
    });

    it("plays on without the pulse when the clip cannot be analysed", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.reject(new Error("offline"))),
      );
      const { container } = render(<HomeSampleCard sample={sample} />);
      await userEvent.click(screen.getByRole("button", { name: "Play sample" }));
      fireEvent.play(audio(container));
      expect(screen.getByRole("button", { name: "Pause sample" })).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(lit()).toHaveLength(0);
    });
  });
});
