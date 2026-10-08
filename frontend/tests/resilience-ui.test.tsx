import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GlobalError from "@/app/global-error";
import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { ErrorFallback } from "@/components/error-fallback";
import { HistoryList } from "@/components/history-list";
import { OfflineBanner } from "@/components/offline-banner";
import { TextToSpeechForm } from "@/components/text-to-speech-form";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { VoiceProfileList } from "@/components/voice-profile-list";
import { useOnline } from "@/hooks/use-online";
import { clearDraft } from "@/lib/draft";
import { __resetSessionForTests } from "@/lib/auth/session";
import { createQueryClient } from "@/lib/query";
import { fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/generate",
}));
vi.mock("@/lib/observability/lazy", () => ({ reportErrorLazy: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const API = "http://api.test/api/v1";

function setOnline(value: boolean) {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => value });
  act(() => {
    window.dispatchEvent(new Event(value ? "online" : "offline"));
  });
}

function wrap(
  ui: ReactNode,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
  clearDraft();
  setOnline(true);
});
afterEach(() => setOnline(true));

describe("useOnline / OfflineBanner", () => {
  it("follows the browser's online and offline events", () => {
    const { result } = renderHook(() => useOnline());
    expect(result.current).toBe(true);
    setOnline(false);
    expect(result.current).toBe(false);
    setOnline(true);
    expect(result.current).toBe(true);
  });

  it("shows a polite notice only while offline", () => {
    render(<OfflineBanner />);
    expect(screen.queryByRole("status")).toBeNull();
    setOnline(false);
    expect(screen.getByRole("status")).toHaveTextContent(/you're offline/i);
    setOnline(true);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("network actions while offline", () => {
  beforeEach(() =>
    server.use(
      mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token)),
      mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json([fixtures.profile])),
    ),
  );

  it("disables Generate with the reason, and re-enables it when back online", async () => {
    wrap(<TextToSpeechForm />);
    const select = await screen.findByLabelText("Voice");
    await waitFor(() => expect(select).not.toBeDisabled());
    const button = screen.getByRole("button", { name: "Generate speech" });
    expect(button).toBeEnabled();
    setOnline(false);
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAccessibleDescription("You're offline.");
    setOnline(true);
    await waitFor(() => expect(button).toBeEnabled());
  });

  it("disables Create voice with the reason while offline", async () => {
    wrap(<UploadVoiceForm />);
    const button = await screen.findByRole("button", { name: "Create voice" });
    setOnline(false);
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAccessibleDescription("You're offline.");
  });

  it("refetches active queries when the connection returns (built into the app's query client)", async () => {
    let calls = 0;
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () => {
        calls += 1;
        return HttpResponse.json([fixtures.profile]);
      }),
    );
    wrap(<VoiceProfileList />, createQueryClient());
    await screen.findByText("My voice");
    const before = calls;
    setOnline(false);
    setOnline(true);
    await waitFor(() => expect(calls).toBeGreaterThan(before));
  });
});

describe("error screens always offer a way out", () => {
  it("route fallback: try again and go to Generate", async () => {
    const reset = vi.fn();
    render(<ErrorFallback reset={reset} />);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(reset).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("link", { name: "Go to Generate" })).toHaveAttribute(
      "href",
      "/generate",
    );
  });

  it("never prints the raw error", () => {
    const { container } = render(<ErrorFallback reset={() => undefined} />);
    expect(container.textContent).not.toMatch(/stack|undefined|TypeError/i);
  });

  it("global fallback is never blank: wordmark, message, recovery and footer", () => {
    // The component renders its own <html>; render the body part by reading the document it creates.
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { container } = render(<GlobalError error={new Error("boom")} reset={() => undefined} />);
    err.mockRestore();
    const text = document.documentElement.textContent ?? container.textContent ?? "";
    expect(text).toContain("CloneVoice");
    expect(text).toContain("Something went wrong");
    expect(text).toContain("Use only voices you have consent to clone");
    expect(text).not.toContain("boom");
  });
});

describe("empty states point at the next action", () => {
  beforeEach(() =>
    server.use(mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token))),
  );

  it("voices: a button that moves to the create form", async () => {
    server.use(mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json([])));
    wrap(
      <>
        <input id="voice-name" aria-label="Voice name" />
        <VoiceProfileList />
      </>,
    );
    expect(await screen.findByText(/haven't created a voice yet/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create a voice" }));
    expect(screen.getByLabelText("Voice name")).toHaveFocus();
  });

  it("history: a link to Generate and no mention of a dashboard", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () =>
        HttpResponse.json([], { headers: { "X-Total-Count": "0" } }),
      ),
    );
    wrap(<HistoryList />);
    expect(await screen.findByText(/nothing generated yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Generate speech" })).toHaveAttribute(
      "href",
      "/generate",
    );
    expect(screen.queryByText(/dashboard/i)).toBeNull();
  });
});
