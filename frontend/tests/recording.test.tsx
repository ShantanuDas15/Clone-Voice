import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { Recorder } from "@/components/recorder";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { __resetSessionForTests } from "@/lib/auth/session";
import {
  MAX_RECORDING_SECONDS,
  detectRecordingSupport,
  formatClock,
  micErrorMessage,
  recordingToFile,
} from "@/lib/recording";
import { server } from "@/mocks/server";

class FakeTrack {
  stop = vi.fn();
  onended: (() => void) | null = null;
}
class FakeStream {
  track = new FakeTrack();
  getTracks = () => [this.track];
  getAudioTracks = () => [this.track];
}
class FakeRecorder {
  static supported: string[] = ["audio/webm;codecs=opus", "audio/webm"];
  static instances: FakeRecorder[] = [];
  static isTypeSupported = (t: string) => FakeRecorder.supported.includes(t);
  state: "inactive" | "recording" = "inactive";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(
    public stream: FakeStream,
    public options: { mimeType: string },
  ) {
    FakeRecorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    if (this.state === "inactive") return;
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

let stream: FakeStream;
const getUserMedia = vi.fn();

function installBrowser() {
  stream = new FakeStream();
  getUserMedia.mockReset().mockResolvedValue(stream);
  FakeRecorder.instances = [];
  FakeRecorder.supported = ["audio/webm;codecs=opus", "audio/webm"];
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
}

beforeEach(() => {
  installBrowser();
  __resetSessionForTests();
  __resetBootstrapForTests();
  vi.mocked(URL.revokeObjectURL).mockClear();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("recording helpers", () => {
  it("detects support and prefers opus WEBM", () => {
    expect(detectRecordingSupport()).toEqual({
      supported: true,
      mimeType: "audio/webm;codecs=opus",
    });
    FakeRecorder.supported = ["audio/webm"];
    expect(detectRecordingSupport()).toEqual({ supported: true, mimeType: "audio/webm" });
  });

  it("explains why recording is unavailable", () => {
    FakeRecorder.supported = ["audio/mp4"]; // Safari/iOS
    const safari = detectRecordingSupport();
    expect(safari.supported).toBe(false);
    expect(!safari.supported && safari.reason).toMatch(/safari/i);

    vi.stubGlobal("MediaRecorder", undefined);
    const none = detectRecordingSupport();
    expect(none.supported).toBe(false);
  });

  it("reports an insecure context", () => {
    vi.stubGlobal("isSecureContext", false);
    const result = detectRecordingSupport();
    expect(!result.supported && result.reason).toMatch(/secure/i);
  });

  it("maps microphone errors to distinct copy", () => {
    const messages = ["NotAllowedError", "NotFoundError", "NotReadableError", "Other"].map((n) =>
      micErrorMessage(new DOMException("x", n)),
    );
    expect(new Set(messages).size).toBe(4);
    expect(messages[0]).toMatch(/blocked/i);
  });

  it("formats the clock and builds a plain audio/webm File", () => {
    expect(formatClock(0)).toBe("0:00");
    expect(formatClock(75.9)).toBe("1:15");
    const file = recordingToFile(new Blob(["x"], { type: "audio/webm;codecs=opus" }));
    expect(file.type).toBe("audio/webm");
    expect(file.name).toBe("recording.webm");
  });
});

describe("Recorder", () => {
  async function begin(onChange = vi.fn()) {
    render(<Recorder onChange={onChange} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start recording" }));
    });
    return onChange;
  }

  it.each([
    ["NotAllowedError", /blocked/i],
    ["NotFoundError", /no microphone/i],
    ["NotReadableError", /busy or unavailable/i],
  ])("shows a recoverable message for %s", async (name, pattern) => {
    getUserMedia.mockRejectedValue(new DOMException("denied", name));
    await begin();
    expect(screen.getByRole("alert")).toHaveTextContent(pattern);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("records, enforces the minimum length, then offers a preview and a webm File", async () => {
    vi.useFakeTimers();
    const onChange = await begin();
    expect(FakeRecorder.instances[0]?.options.mimeType).toBe("audio/webm;codecs=opus");
    const stop = screen.getByRole("button", { name: "Stop recording" });
    expect(stop).toBeDisabled();

    await act(async () => void vi.advanceTimersByTime(6000));
    expect(stop).toBeEnabled();
    await act(async () => {
      fireEvent.click(stop);
    });

    expect(screen.getByLabelText("Recording preview")).toBeInTheDocument();
    expect(stream.track.stop).toHaveBeenCalled(); // mic indicator off
    const last = onChange.mock.calls.at(-1)?.[0] as File;
    expect(last).toBeInstanceOf(File);
    expect(last.type).toBe("audio/webm");
  });

  it("shows a labelled microphone meter while recording, and no false 'silent' warning", async () => {
    vi.useFakeTimers();
    await begin();
    await act(async () => void vi.advanceTimersByTime(1000));
    const meter = screen.getByRole("meter", { name: "Microphone level" });
    expect(meter).toHaveAttribute("aria-valuemin", "0");
    expect(meter).toHaveAttribute("aria-valuemax", "100");
    expect(meter).toHaveAttribute("aria-valuenow", "0"); // no Web Audio in jsdom: stays at 0
    expect(screen.queryByText(/can't hear anything/i)).toBeNull();
  });

  it("discard releases the microphone and clears the file", async () => {
    vi.useFakeTimers();
    const onChange = await begin();
    await act(async () => void vi.advanceTimersByTime(1000));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    });
    expect(stream.track.stop).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Start recording" })).toBeInTheDocument();
    expect(onChange.mock.calls.at(-1)?.[0]).toBeNull();
  });

  it("auto-stops at the maximum length", async () => {
    vi.useFakeTimers();
    await begin();
    await act(async () => void vi.advanceTimersByTime((MAX_RECORDING_SECONDS + 1) * 1000));
    expect(screen.getByLabelText("Recording preview")).toBeInTheDocument();
    expect(FakeRecorder.instances[0]?.state).toBe("inactive");
  });

  it("does not upload a partial take when the microphone is unplugged", async () => {
    vi.useFakeTimers();
    const onChange = await begin();
    await act(async () => void vi.advanceTimersByTime(8000));
    await act(async () => void stream.track.onended?.());
    expect(screen.getByRole("alert")).toHaveTextContent(/disconnected/i);
    expect(stream.track.stop).toHaveBeenCalled();
    expect(onChange.mock.calls.every(([f]) => f === null)).toBe(true);
  });

  it("stops when the tab is hidden and rejects a too-short take", async () => {
    vi.useFakeTimers();
    await begin();
    await act(async () => void vi.advanceTimersByTime(2000));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    await act(async () => void document.dispatchEvent(new Event("visibilitychange")));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    expect(screen.getByRole("alert")).toHaveTextContent(/too short/i);
  });

  it("releases the stream when unmounted mid-recording", async () => {
    const view = render(<Recorder onChange={vi.fn()} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start recording" }));
    });
    view.unmount();
    expect(stream.track.stop).toHaveBeenCalled();
  });

  it("releases a stream granted after the prompt was cancelled", async () => {
    let grant: (s: FakeStream) => void = () => {};
    getUserMedia.mockReturnValue(new Promise<FakeStream>((resolve) => (grant = resolve)));
    await begin();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    });
    await act(async () => grant(stream));
    expect(stream.track.stop).toHaveBeenCalled();
    expect(FakeRecorder.instances).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Start recording" })).toBeInTheDocument();
  });
});

describe("UploadVoiceForm recording", () => {
  const API = "http://api.test/api/v1";
  function wrap() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <UploadVoiceForm />
        </AuthProvider>
      </QueryClientProvider>,
    );
  }

  it("offers Record now and uploads the take exactly once", async () => {
    let uploads = 0;
    server.use(
      mswHttp.post(`${API}/voice/upload`, () => {
        uploads += 1;
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    wrap();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("radio", { name: "Record now" }));
    await user.click(await screen.findByRole("button", { name: "Start recording" }));

    // Real timers: wait out the minimum with a patched clock instead of sleeping 5 s.
    const realNow = Date.now;
    const offset = 6000;
    vi.spyOn(Date, "now").mockImplementation(() => realNow() + offset);
    const stop = await screen.findByRole("button", { name: "Stop recording" });
    await vi.waitFor(() => expect(stop).toBeEnabled());
    await user.click(stop);
    vi.restoreAllMocks();

    await user.type(screen.getByLabelText("Voice name"), "Mine");
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Create voice" }));
    await vi.waitFor(() => expect(uploads).toBe(1));
  });

  it("hides recording and explains why where it is unsupported", async () => {
    FakeRecorder.supported = ["audio/mp4"];
    wrap();
    expect(await screen.findByText(/safari/i)).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Record now" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Voice sample")).toBeInTheDocument(); // file upload remains
  });
});
