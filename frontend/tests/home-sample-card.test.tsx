import { fireEvent, render, screen } from "@testing-library/react";
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

  it("reports the playhead as a fraction of the clip and advances the clock", () => {
    const onProgress = vi.fn();
    const { container } = render(<HomeSampleCard sample={sample} onProgress={onProgress} />);
    const el = audio(container);
    Object.defineProperty(el, "currentTime", { configurable: true, value: 1.45 });
    fireEvent.timeUpdate(el);
    expect(screen.getByTestId("sample-time")).toHaveTextContent("0:01 / 0:02");
    expect(onProgress).toHaveBeenLastCalledWith(0.5);
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
});
