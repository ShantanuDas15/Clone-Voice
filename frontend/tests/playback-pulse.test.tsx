import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Take } from "@/components/take";
import { ENVELOPE_HOP_S, analyseBlob, bucketEnvelope } from "@/lib/audio-peaks";
import {
  PULSE_BARS,
  PULSE_REACH,
  PULSE_REST_BAR,
  WAVE_HEIGHT,
  levelAt,
  pulseBar,
  smoothLevel,
} from "@/lib/playback-pulse";

describe("bucketEnvelope", () => {
  it("measures loudness per slice and scales the loudest slice to 1", () => {
    // 4 samples per slice at 100 Hz (hop 0.04 s): quiet, loud, quiet.
    const samples = new Float32Array([0.1, 0.1, 0.1, 0.1, 0.8, 0.8, 0.8, 0.8, 0.1, 0.1, 0.1, 0.1]);
    const envelope = bucketEnvelope(samples, 100, 0.04);
    expect(envelope?.hop).toBeCloseTo(0.04);
    expect(envelope?.levels).toHaveLength(3);
    expect(envelope?.levels[1]).toBe(1);
    expect(envelope!.levels[0]).toBeCloseTo((0.1 / 0.8) ** 0.7, 5);
    expect(envelope!.levels[0]).toBeGreaterThan(0.1 / 0.8); // eased, so quiet speech still moves it
  });

  it("is null for silence, no samples or a nonsense rate", () => {
    expect(bucketEnvelope(new Float32Array(50), 100)).toBeNull();
    expect(bucketEnvelope(new Float32Array(0), 100)).toBeNull();
    expect(bucketEnvelope(new Float32Array([1]), 0)).toBeNull();
    expect(bucketEnvelope(new Float32Array([1]), 100, 0)).toBeNull();
  });

  it("keeps a final short slice and uses the default hop", () => {
    const envelope = bucketEnvelope(new Float32Array(55).fill(0.5), 1000);
    expect(envelope?.levels).toHaveLength(3); // 25 + 25 + 5 samples
    expect(envelope?.hop).toBeCloseTo(ENVELOPE_HOP_S);
    expect(envelope?.levels.every((v) => v === 1)).toBe(true);
  });
});

describe("analyseBlob", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("returns the bars and the loudness from one decode", async () => {
    const decode = vi.fn(() =>
      Promise.resolve({
        sampleRate: 100,
        getChannelData: () => new Float32Array([0.5, 1, 0.25, 0.5]),
      }),
    );
    vi.stubGlobal(
      "AudioContext",
      class {
        decodeAudioData = decode;
        close() {
          return Promise.resolve();
        }
      },
    );
    window.AudioContext = globalThis.AudioContext;
    const out = await analyseBlob(new Blob([new Uint8Array(10)]), 2);
    expect(out?.peaks).toEqual([1, 0.5]);
    expect(out?.envelope?.levels.length).toBeGreaterThan(0);
    expect(decode).toHaveBeenCalledTimes(1);
  });

  it("is null, and never throws, when the audio cannot be decoded", async () => {
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
    window.AudioContext = globalThis.AudioContext;
    expect(await analyseBlob(new Blob([new Uint8Array(10)]))).toBeNull();
    expect(await analyseBlob(new Blob([]))).toBeNull();
  });
});

describe("the pulse maths", () => {
  const envelope = { hop: 1, levels: [0, 1, 0.5] };

  it("reads the loudness at a time, interpolating and clamping", () => {
    expect(levelAt(envelope, 0)).toBe(0);
    expect(levelAt(envelope, 0.5)).toBeCloseTo(0.5);
    expect(levelAt(envelope, 1)).toBe(1);
    expect(levelAt(envelope, 1.5)).toBeCloseTo(0.75);
    expect(levelAt(envelope, 99)).toBe(0.5); // past the end: the last slice
    expect(levelAt(envelope, -3)).toBe(0);
    expect(levelAt(envelope, Number.NaN)).toBe(0);
    expect(levelAt({ hop: 1, levels: [] }, 1)).toBe(0);
  });

  it("rises quickly and falls slowly", () => {
    const up = smoothLevel(0, 1);
    const down = 1 - smoothLevel(1, 0);
    expect(up).toBeGreaterThan(0.5);
    expect(down).toBeLessThan(0.2);
    expect(smoothLevel(0.4, 0.4)).toBe(0.4);
  });

  it("lifts the bar at the playhead most, and hides bars out of reach", () => {
    const at = pulseBar(10, 10.5, 1, 1);
    const near = pulseBar(13, 10.5, 1, 1);
    const far = pulseBar(10 + PULSE_REACH + 2, 10.5, 1, 1);
    expect(at.height).toBeGreaterThan(PULSE_REST_BAR);
    expect(at.height).toBeGreaterThan(near.height);
    expect(at.opacity).toBeGreaterThan(near.opacity);
    expect(far).toEqual({ height: 0, opacity: 0 });
  });

  it("does nothing to a quiet moment but stays visible, and never outgrows the box", () => {
    const quiet = pulseBar(10, 10.5, 0, 1);
    expect(quiet.height).toBeCloseTo(PULSE_REST_BAR);
    expect(quiet.opacity).toBeGreaterThan(0);
    expect(pulseBar(10, 10.5, 1, 99).height).toBeLessThanOrEqual(WAVE_HEIGHT);
    expect(pulseBar(10, 10.5, 1, 0).height).toBeGreaterThanOrEqual(2);
  });
});

describe("Take with the playback pulse", () => {
  let queue: Array<[number, FrameRequestCallback]>;
  let nextId: number;
  let now: number;

  beforeEach(() => {
    queue = [];
    nextId = 1;
    now = 0;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      const id = nextId++;
      queue.push([id, cb]);
      return id;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => {
      queue = queue.filter(([i]) => i !== id);
    });
    // A 2 s take at 1 kHz: loud for the first second, quiet (a tenth) for the second.
    const samples = new Float32Array(2000);
    samples.fill(1, 0, 1000);
    samples.fill(0.1, 1000);
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
    Object.defineProperty(HTMLMediaElement.prototype, "play", {
      configurable: true,
      value: vi.fn(() => Promise.resolve()),
    });
    Object.defineProperty(HTMLMediaElement.prototype, "pause", {
      configurable: true,
      value: vi.fn(),
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  const audioEl = (c: HTMLElement) => c.querySelector("audio") as HTMLAudioElement;
  const bars = () => Array.from(screen.getByTestId("take-pulse").children) as SVGRectElement[];
  const num = (el: Element, attr: string) => Number(el.getAttribute(attr));
  /** Run the animation loop for `ms` of simulated time. */
  function run(ms: number) {
    act(() => {
      for (let t = 0; t < ms; t += 40) {
        now += 40;
        const due = queue;
        queue = [];
        due.forEach(([, cb]) => cb(now));
      }
    });
  }
  function setup(props: { pulse?: boolean } = { pulse: true }) {
    const view = render(
      <Take
        src="blob:x"
        blob={new Blob([new Uint8Array(20)])}
        filename="a.wav"
        label="Speech"
        {...props}
      />,
    );
    const el = audioEl(view.container);
    Object.defineProperty(el, "duration", { configurable: true, value: 2 });
    fireEvent.loadedMetadata(el);
    return { ...view, el };
  }
  const play = (el: HTMLAudioElement, at: number) => {
    el.currentTime = at;
    fireEvent.play(el);
  };

  it("has the pulse layer only when asked, and no inline style anywhere", async () => {
    const off = setup({});
    await waitFor(() => expect(off.container.querySelector("svg")).not.toBeNull());
    expect(screen.queryByTestId("take-pulse")).not.toBeInTheDocument();
    off.unmount();

    const on = setup();
    await waitFor(() => expect(screen.getByTestId("take-pulse")).toBeInTheDocument());
    expect(bars()).toHaveLength(PULSE_BARS);
    expect(bars().every((b) => b.getAttribute("opacity") === "0")).toBe(true);
    // The slider's own inline playhead position is the player's (set from script); the pulse adds none.
    expect(screen.getByTestId("take-pulse").querySelectorAll("[style]")).toHaveLength(0);
    expect(on.container.querySelector("svg [style]")).toBeNull();
  });

  it("leaves headroom: bars rest shorter when the pulse is on, and at the usual height when off", async () => {
    const on = setup();
    await waitFor(() => expect(screen.getByTestId("take-pulse")).toBeInTheDocument());
    const restOn = Math.max(
      ...Array.from(on.container.querySelectorAll("svg g.fill-border rect")).map((r) =>
        num(r, "height"),
      ),
    );
    expect(restOn).toBeCloseTo(PULSE_REST_BAR);
    on.unmount();
    const off = setup({});
    await waitFor(() =>
      expect(off.container.querySelector("svg g.fill-border rect")).not.toBeNull(),
    );
    const restOff = Math.max(
      ...Array.from(off.container.querySelectorAll("svg g.fill-border rect")).map((r) =>
        num(r, "height"),
      ),
    );
    expect(restOff).toBeCloseTo(44);
  });

  it("rises with a loud moment and barely moves at a quiet one: it follows the audio", async () => {
    const { el } = setup();
    await waitFor(() => expect(screen.getByTestId("take-pulse")).toBeInTheDocument());
    const rest = (centre: number) => PULSE_REST_BAR * (centre < 32 ? 1 : 0.1);

    play(el, 0.5); // loud: the playhead is at bar 16
    run(400);
    const loud = bars().filter((b) => num(b, "opacity") > 0);
    expect(loud.length).toBeGreaterThan(5);
    const tallLoud = Math.max(...loud.map((b) => num(b, "height")));
    expect(tallLoud).toBeGreaterThan(rest(16) * 1.4); // lifted well above its resting height

    el.currentTime = 1.5; // quiet: bar 48
    run(800); // the level eases down
    const quiet = bars().filter((b) => num(b, "opacity") > 0);
    const tallQuiet = Math.max(...quiet.map((b) => num(b, "height")));
    expect(tallQuiet).toBeLessThan(rest(48) * 1.3 + 0.01);
    expect(tallQuiet).toBeLessThan(tallLoud);
  });

  it("keeps the bars around the playhead, moving with it", async () => {
    const { el } = setup();
    await waitFor(() => expect(screen.getByTestId("take-pulse")).toBeInTheDocument());
    play(el, 0.5);
    run(80);
    const xs1 = bars()
      .filter((b) => num(b, "opacity") > 0)
      .map((b) => num(b, "x"));
    el.currentTime = 1.0;
    run(80);
    const xs2 = bars()
      .filter((b) => num(b, "opacity") > 0)
      .map((b) => num(b, "x"));
    expect(Math.min(...xs2)).toBeGreaterThan(Math.min(...xs1));
    expect(xs1.every((x) => x >= 0 && x <= 63 * 4 + 0.5)).toBe(true);
  });

  it("hides every bar and stops the loop the moment the take pauses, and when it ends", async () => {
    const { el } = setup();
    await waitFor(() => expect(screen.getByTestId("take-pulse")).toBeInTheDocument());
    play(el, 0.5);
    run(200);
    expect(bars().some((b) => num(b, "opacity") > 0)).toBe(true);
    fireEvent.pause(el);
    expect(bars().every((b) => b.getAttribute("opacity") === "0")).toBe(true);
    expect(queue).toHaveLength(0);

    play(el, 0.5);
    run(200);
    fireEvent.ended(el);
    expect(bars().every((b) => b.getAttribute("opacity") === "0")).toBe(true);
    expect(queue).toHaveLength(0);
  });

  it("draws about 30 frames a second however fast the screen refreshes", async () => {
    const { el } = setup();
    await waitFor(() => expect(screen.getByTestId("take-pulse")).toBeInTheDocument());
    play(el, 0.5);
    const written = vi.spyOn(Element.prototype, "setAttribute");
    act(() => {
      for (let t = 0; t < 160; t += 8) {
        now += 8; // a 125 Hz screen
        const due = queue;
        queue = [];
        due.forEach(([, cb]) => cb(now));
      }
    });
    const frames = written.mock.calls.filter(([name]) => name === "height").length / PULSE_BARS;
    expect(frames).toBeGreaterThanOrEqual(4);
    expect(frames).toBeLessThanOrEqual(6); // 160 ms at 32 ms a frame
    written.mockRestore();
  });

  it("does not start at all under reduced motion", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: /reduce/.test(q),
      media: q,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    const { el } = setup();
    await waitFor(() => expect(screen.getByTestId("take-pulse")).toBeInTheDocument());
    play(el, 0.5);
    run(400);
    expect(queue).toHaveLength(0);
    expect(bars().every((b) => b.getAttribute("opacity") === "0")).toBe(true);
    // The playing state and the clock are untouched: only the extra motion is off.
    expect(screen.getByRole("button", { name: "Pause Speech" })).toBeInTheDocument();
  });

  it("stops while the tab is hidden and resumes when it is shown again", async () => {
    const { el } = setup();
    await waitFor(() => expect(screen.getByTestId("take-pulse")).toBeInTheDocument());
    play(el, 0.5);
    run(80);
    let hidden = true;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    run(120); // the pending frame sees a hidden tab and does not schedule another
    expect(queue).toHaveLength(0);
    hidden = false;
    act(() => void document.dispatchEvent(new Event("visibilitychange")));
    expect(queue).toHaveLength(1);
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
  });

  it("does nothing, and does not throw, when the take could not be decoded", async () => {
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
    window.AudioContext = globalThis.AudioContext;
    const { el, container } = setup();
    await new Promise((r) => setTimeout(r, 20));
    play(el, 0.5);
    run(200);
    expect(screen.queryByTestId("take-pulse")).not.toBeInTheDocument(); // no waveform, so no pulse
    expect(container.querySelector("audio")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause Speech" })).toBeInTheDocument();
  });
});
