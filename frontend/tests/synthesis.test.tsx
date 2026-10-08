import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { TextToSpeechForm } from "@/components/text-to-speech-form";
import { parseFilename, parseGenerationId } from "@/lib/api/synthesize";
import { clearDraft } from "@/lib/draft";
import { __resetSessionForTests } from "@/lib/auth/session";
import { hasLikelyUnsupportedChars, synthesisTextSchema } from "@/lib/validation/text";
import { fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/generate",
}));

const API = "http://api.test/api/v1";
const GEN_ID = "33333333-3333-4333-8333-333333333333";
const wavResponse = (headers: Record<string, string> = {}) =>
  new HttpResponse(new Uint8Array([82, 73, 70, 70]), {
    headers: { "Content-Type": "audio/wav", ...headers },
  });

let client: QueryClient;
function wrap(ui: ReactNode) {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
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
  vi.mocked(URL.createObjectURL).mockClear();
  vi.mocked(URL.revokeObjectURL).mockClear();
});

async function generate(text = "Hello there.") {
  const user = userEvent.setup();
  const select = await screen.findByLabelText("Voice");
  await waitFor(() => expect(select).not.toBeDisabled());
  await user.selectOptions(select, fixtures.profile.id);
  if (text) await user.type(screen.getByLabelText("Text"), text);
  await user.click(screen.getByRole("button", { name: "Generate speech" }));
  return user;
}

describe("helpers", () => {
  it("parses the filename and generation id from Content-Disposition", () => {
    const cd = `attachment; filename="synthesized_${GEN_ID}.wav"`;
    expect(parseFilename(cd)).toBe(`synthesized_${GEN_ID}.wav`);
    expect(parseGenerationId(parseFilename(cd))).toBe(GEN_ID);
    expect(parseFilename(undefined)).toBeNull();
    expect(parseGenerationId("other.wav")).toBeNull();
  });
  it("validates text length and trims", () => {
    expect(synthesisTextSchema.safeParse("   ").success).toBe(false);
    expect(synthesisTextSchema.parse("  hi  ")).toBe("hi");
    expect(synthesisTextSchema.safeParse("x".repeat(500)).success).toBe(true);
    expect(synthesisTextSchema.safeParse("x".repeat(501)).success).toBe(false);
  });
  it("flags emoji but not accented Latin text", () => {
    expect(hasLikelyUnsupportedChars("hello 😀")).toBe(true);
    expect(hasLikelyUnsupportedChars("café, naïve — 42")).toBe(false);
  });
});

describe("TextToSpeechForm", () => {
  it("generates once, shows a labelled player and download, and invalidates history", async () => {
    let calls = 0;
    let body: unknown;
    server.use(
      mswHttp.post(`${API}/synthesize`, async ({ request }) => {
        calls += 1;
        body = await request.json();
        return wavResponse({
          "Content-Disposition": `attachment; filename="synthesized_${GEN_ID}.wav"`,
        });
      }),
    );
    wrap(<TextToSpeechForm />);
    const spy = vi.spyOn(client, "invalidateQueries");
    await generate();
    const link = await screen.findByRole("link", { name: "Download WAV" });
    expect(link).toHaveAttribute("download", `synthesized_${GEN_ID}.wav`);
    expect(link.getAttribute("href")).toMatch(/^blob:mock-/);
    expect(screen.getByText(/AI-generated voice/)).toBeInTheDocument();
    expect(calls).toBe(1);
    expect(body).toEqual({ voice_profile_id: fixtures.profile.id, text: "Hello there." });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["history"] });
  });

  it("falls back to a client filename when the header is unavailable", async () => {
    wrap(<TextToSpeechForm />);
    await generate();
    expect(await screen.findByRole("link", { name: "Download WAV" })).toHaveAttribute(
      "download",
      "clonevoice-speech.wav",
    );
  });

  it("revokes the previous object URL when regenerating, keeping the voice selected", async () => {
    wrap(<TextToSpeechForm />);
    const user = await generate("First.");
    await screen.findByRole("link", { name: "Download WAV" });
    const first = vi.mocked(URL.createObjectURL).mock.results[0]?.value;
    await user.clear(screen.getByLabelText("Text"));
    await user.type(screen.getByLabelText("Text"), "Second.");
    await user.click(screen.getByRole("button", { name: "Generate speech" }));
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith(first));
    expect(screen.getByLabelText("Voice")).toHaveValue(fixtures.profile.id);
  });

  it("offers Edit text and Generate again on a result", async () => {
    const bodies: unknown[] = [];
    server.use(
      mswHttp.post(`${API}/synthesize`, async ({ request }) => {
        bodies.push(await request.json());
        return wavResponse();
      }),
    );
    wrap(<TextToSpeechForm />);
    const user = await generate("Say it twice.");
    await screen.findByRole("link", { name: "Download WAV" });

    await user.click(screen.getByRole("button", { name: "Edit text" }));
    expect(screen.getByLabelText("Text")).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Generate again" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toEqual({ voice_profile_id: fixtures.profile.id, text: "Say it twice." });
  });

  it("generates again with the original text even if the box was edited meanwhile", async () => {
    const bodies: Array<{ text: string }> = [];
    server.use(
      mswHttp.post(`${API}/synthesize`, async ({ request }) => {
        bodies.push((await request.json()) as { text: string });
        return wavResponse();
      }),
    );
    wrap(<TextToSpeechForm />);
    const user = await generate("Original.");
    await screen.findByRole("link", { name: "Download WAV" });
    await user.clear(screen.getByLabelText("Text"));
    await user.type(screen.getByLabelText("Text"), "Changed.");
    await user.click(screen.getByRole("button", { name: "Generate again" }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]?.text).toBe("Original.");
    expect(screen.getByLabelText("Text")).toHaveValue("Original.");
  });

  it("shows an honest, quiet progress state: a bar and a ticking clock hidden from screen readers", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, async () => {
        await new Promise((r) => setTimeout(r, 300));
        return wavResponse();
      }),
    );
    wrap(<TextToSpeechForm />);
    await generate();
    const status = await screen.findByText(/This can take a minute/);
    const clock = status.querySelector("span");
    expect(clock).toHaveAttribute("aria-hidden", "true");
    expect(clock?.className).toContain("font-mono");
    expect(status.parentElement?.querySelector(".animate-indeterminate")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("revokes the object URL on unmount (R15)", async () => {
    const { unmount } = wrap(<TextToSpeechForm />);
    await generate();
    await screen.findByRole("link", { name: "Download WAV" });
    const url = vi.mocked(URL.createObjectURL).mock.results[0]?.value;
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(url);
  });

  it("makes no request without a voice or with blank text", async () => {
    let calls = 0;
    server.use(mswHttp.post(`${API}/synthesize`, () => ((calls += 1), wavResponse())));
    wrap(<TextToSpeechForm />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Generate speech" }));
    expect(await screen.findByText("Choose a voice first.")).toBeInTheDocument();
    const select = screen.getByLabelText("Voice");
    await waitFor(() => expect(select).not.toBeDisabled());
    await user.selectOptions(select, fixtures.profile.id);
    await user.type(screen.getByLabelText("Text"), "   ");
    await user.click(screen.getByRole("button", { name: "Generate speech" }));
    expect(await screen.findByText("Enter some text to speak")).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("shows a live counter and an emoji pre-warning", async () => {
    wrap(<TextToSpeechForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Text"), "hi 😀");
    expect(screen.getByText("5 / 500")).toBeInTheDocument();
    expect(screen.getByText(/emoji and symbols/i)).toBeInTheDocument();
  });

  it("sends one request when submitted twice quickly (R4)", async () => {
    let calls = 0;
    server.use(
      mswHttp.post(`${API}/synthesize`, async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 50));
        return wavResponse();
      }),
    );
    wrap(<TextToSpeechForm />);
    await generate();
    // A second submit event while the first is in flight (e.g. a repeated key press) must be ignored.
    fireEvent.submit(screen.getByRole("form", { name: "Generate speech" }));
    await screen.findByRole("link", { name: "Download WAV" });
    expect(calls).toBe(1);
  });

  it.each([
    ["404", 404, { detail: "Voice profile not found" }, /no longer exists/i, true],
    [
      "403",
      403,
      { detail: "Not authorized to use this voice profile" },
      /can't use that voice/i,
      true,
    ],
    ["409", 409, { detail: "Voice profile is not ready" }, /isn't ready/i, true],
    ["403 unverified", 403, { detail: "Email address not verified" }, /verify your email/i, false],
    ["503", 503, { detail: "Server overloaded" }, /busy/i, false],
    ["500", 500, "oops", /something went wrong/i, false],
  ] as const)(
    "handles %s with a clear message",
    async (_l, status, body, expected, refetchesProfiles) => {
      let profileFetches = 0;
      server.use(
        mswHttp.get(
          `${API}/voice/profiles`,
          () => ((profileFetches += 1), HttpResponse.json([fixtures.profile])),
        ),
        mswHttp.post(`${API}/synthesize`, () => HttpResponse.json(body, { status })),
      );
      wrap(<TextToSpeechForm />);
      await generate();
      expect(await screen.findByText(expected)).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Download WAV" })).toBeNull();
      if (refetchesProfiles) await waitFor(() => expect(profileFetches).toBeGreaterThanOrEqual(2));
    },
  );

  it("parses a JSON error delivered inside a Blob body", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, () =>
        HttpResponse.json({ detail: "Voice profile is not ready" }, { status: 409 }),
      ),
    );
    wrap(<TextToSpeechForm />);
    await generate();
    expect(await screen.findByText(/isn't ready/i)).toBeInTheDocument();
  });

  it("maps a 422 list-detail to the text field", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, () =>
        HttpResponse.json(
          {
            detail: [
              {
                loc: ["body", "text"],
                msg: "Value error, Text contains characters unsupported: '{'",
                type: "value_error",
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    wrap(<TextToSpeechForm />);
    await generate("braces {{");
    expect(await screen.findByText(/characters unsupported/i)).toBeInTheDocument();
  });

  it("disables generation during a 429 cooldown for both error shapes", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, () =>
        HttpResponse.json({ error: "Rate limit exceeded: 5 per 1 minute" }, { status: 429 }),
      ),
    );
    wrap(<TextToSpeechForm />);
    await generate();
    expect(await screen.findByText(/you can try again in \d+ s/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate speech" })).toBeDisabled();
  });

  it("uses Retry-After and treats 'service busy' as a short cooldown", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, () =>
        HttpResponse.json(
          { detail: "Service busy" },
          { status: 429, headers: { "Retry-After": "7" } },
        ),
      ),
    );
    wrap(<TextToSpeechForm />);
    await generate();
    expect(await screen.findByText("You can try again in 7 s.")).toBeInTheDocument();
  });

  it("treats a dropped connection as ambiguous: no 'failed' claim, history refetched", async () => {
    server.use(mswHttp.post(`${API}/synthesize`, () => HttpResponse.error()));
    wrap(<TextToSpeechForm />);
    const spy = vi.spyOn(client, "invalidateQueries");
    await generate();
    expect(await screen.findByText(/may still have been generated/i)).toBeInTheDocument();
    expect(spy).toHaveBeenCalledWith({ queryKey: ["history"] });
  });

  it("cancel aborts the browser request, returns to idle, and refreshes history (R7)", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, async () => {
        await new Promise((r) => setTimeout(r, 2000));
        return wavResponse();
      }),
    );
    wrap(<TextToSpeechForm />);
    const spy = vi.spyOn(client, "invalidateQueries");
    const user = await generate();
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await screen.findByText(/cancelled/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate speech" })).toBeEnabled();
    expect(spy).toHaveBeenCalledWith({ queryKey: ["history"] });
  });

  it("warns on unload only while generating (R9)", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, async () => {
        await new Promise((r) => setTimeout(r, 80));
        return wavResponse();
      }),
    );
    wrap(<TextToSpeechForm />);
    const idle = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(idle);
    expect(idle.defaultPrevented).toBe(false);
    await generate();
    expect((await screen.findAllByText(/generating…/i)).length).toBeGreaterThan(0);
    const busy = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(busy);
    expect(busy.defaultPrevented).toBe(true);
    await screen.findByRole("link", { name: "Download WAV" });
  });

  it("restores the draft after a remount (R2)", async () => {
    const { unmount } = wrap(<TextToSpeechForm />);
    await generate("Keep me");
    unmount();
    wrap(<TextToSpeechForm />);
    expect(await screen.findByLabelText("Text")).toHaveValue("Keep me");
  });

  it("shows a player error state when the audio can't be decoded", async () => {
    wrap(<TextToSpeechForm />);
    await generate();
    const audio = (await screen.findByLabelText("Generated speech")) as HTMLAudioElement;
    audio.dispatchEvent(new Event("error"));
    expect(await screen.findByText(/couldn't be played/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download WAV" })).toBeInTheDocument();
  });

  it("disables Generate for an unverified user and says why next to the button", async () => {
    server.use(
      mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token)),
      mswHttp.get(`${API}/auth/me`, () =>
        HttpResponse.json({ ...fixtures.user, email_verified_at: null }),
      ),
    );
    wrap(<TextToSpeechForm />);
    const button = await screen.findByRole("button", { name: "Generate speech" });
    await waitFor(() => expect(button).toBeDisabled());
    expect(screen.getByText("Verify your email first.")).toBeInTheDocument();
    expect(button).toHaveAccessibleDescription("Verify your email first.");
  });
});
