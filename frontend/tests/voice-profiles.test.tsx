import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { VoiceProfileList } from "@/components/voice-profile-list";
import { VoiceProfileSelect } from "@/components/voice-profile-select";
import { http } from "@/lib/api/http";
import { type VoiceProfile, sortProfiles } from "@/lib/api/voice";
import { __resetSessionForTests } from "@/lib/auth/session";
import { fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/voices",
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const API = "http://api.test/api/v1";
const profile = (over: Partial<VoiceProfile> = {}): VoiceProfile => ({
  ...fixtures.profile,
  ...over,
});

function wrap(ui: ReactNode) {
  const client = new QueryClient({
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
});

describe("sortProfiles", () => {
  it("sorts newest first regardless of server order", () => {
    const out = sortProfiles([
      profile({ id: "a", created_at: "2026-01-01T00:00:00Z" }),
      profile({ id: "c", created_at: "2026-03-01T00:00:00Z" }),
      profile({ id: "b", created_at: "2026-02-01T00:00:00Z" }),
    ]);
    expect(out.map((p) => p.id)).toEqual(["c", "b", "a"]);
  });
});

describe("VoiceProfileList", () => {
  it("renders profiles with status and the failed-row hint", async () => {
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () =>
        HttpResponse.json([
          profile({ name: "Good" }),
          profile({ id: "f1", name: "Broken", status: "failed" }),
        ]),
      ),
    );
    wrap(<VoiceProfileList />);
    expect(await screen.findByText("Good")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/couldn't be processed/i)).toBeInTheDocument();
  });

  it("shows an empty state, and an error state with retry", async () => {
    server.use(mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json([])));
    const { unmount } = wrap(<VoiceProfileList />);
    expect(await screen.findByText(/haven't created a voice/i)).toBeInTheDocument();
    unmount();
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    wrap(<VoiceProfileList />);
    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("deletes only after confirmation, then removes the row", async () => {
    let list = [profile()];
    let deletes = 0;
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json(list)),
      mswHttp.delete(
        `${API}/voice/profiles/:id`,
        () => ((deletes += 1), (list = []), HttpResponse.json({ status: "deleted" })),
      ),
    );
    wrap(<VoiceProfileList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete My voice" }));
    expect(deletes).toBe(0);
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      /permanently removes every audio clip/i,
    );
    await user.click(screen.getByRole("button", { name: "Delete voice" }));
    await waitFor(() => expect(screen.queryByText("My voice")).toBeNull());
    expect(deletes).toBe(1);
  });

  it("Cancel does nothing", async () => {
    let deletes = 0;
    server.use(
      mswHttp.delete(`${API}/voice/profiles/:id`, () => ((deletes += 1), HttpResponse.json({}))),
    );
    wrap(<VoiceProfileList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete My voice" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(deletes).toBe(0);
  });

  it("treats a 404 on delete as already gone", async () => {
    let list = [profile()];
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json(list)),
      mswHttp.delete(
        `${API}/voice/profiles/:id`,
        () => (
          (list = []),
          HttpResponse.json({ detail: "Voice profile not found" }, { status: 404 })
        ),
      ),
    );
    wrap(<VoiceProfileList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete My voice" }));
    await user.click(screen.getByRole("button", { name: "Delete voice" }));
    await waitFor(() => expect(screen.queryByText("My voice")).toBeNull());
  });

  it("rolls the row back when delete fails", async () => {
    server.use(
      mswHttp.delete(`${API}/voice/profiles/:id`, () =>
        HttpResponse.json({ detail: "x" }, { status: 500 }),
      ),
    );
    wrap(<VoiceProfileList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete My voice" }));
    await user.click(screen.getByRole("button", { name: "Delete voice" }));
    await waitFor(() => expect(screen.getByText("My voice")).toBeInTheDocument());
  });
});

describe("VoiceProfileSelect", () => {
  it("offers only ready profiles", async () => {
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () =>
        HttpResponse.json([
          profile({ name: "Ready one" }),
          profile({ id: "f", name: "Failed one", status: "failed" }),
        ]),
      ),
    );
    wrap(<VoiceProfileSelect value="" onChange={() => {}} />);
    const select = await screen.findByLabelText("Voice");
    await waitFor(() => expect(within(select).queryByText("Ready one")).not.toBeNull());
    expect(within(select).queryByText("Failed one")).toBeNull();
  });
});

describe("UploadVoiceForm", () => {
  const wav = () => new File([new Uint8Array(2000)], "sample.wav", { type: "audio/wav" });

  async function fillAndSubmit(
    opts: { consent?: boolean; adult?: boolean; file?: File | null; name?: string } = {},
  ) {
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Voice name"), opts.name ?? "My voice");
    if (opts.file !== null)
      await user.upload(screen.getByLabelText("Voice sample"), opts.file ?? wav());
    if (opts.consent !== false)
      await user.click(screen.getByRole("checkbox", { name: /right to use this voice/ }));
    if (opts.adult !== false)
      await user.click(screen.getByRole("checkbox", { name: /speaker is 18 or older/ }));
    await user.click(screen.getByRole("button", { name: "Create voice" }));
    return user;
  }

  it("refreshes the voice list after a successful upload (found by the e2e run)", async () => {
    let created = false;
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () =>
        HttpResponse.json(created ? [profile({ name: "Fresh voice" })] : []),
      ),
    );
    const post = vi.spyOn(http, "post").mockImplementation(async () => {
      created = true;
      return { data: fixtures.profile };
    });
    wrap(
      <>
        <UploadVoiceForm />
        <VoiceProfileList />
      </>,
    );
    expect(await screen.findByText(/haven't created a voice/i)).toBeInTheDocument();
    await fillAndSubmit({ name: "Fresh voice" });
    expect(await screen.findByText("Fresh voice", { selector: "p" })).toBeInTheDocument();
    post.mockRestore();
  });

  it("uploads multipart with consent and the terms version, then confirms", async () => {
    // jsdom's XHR hands MSW an unserialisable FormData, so inspect the request at the client instead.
    const post = vi.spyOn(http, "post").mockResolvedValue({ data: fixtures.profile });
    wrap(<UploadVoiceForm />);
    await fillAndSubmit();
    expect(await screen.findByText(/created\./i)).toBeInTheDocument();
    // The next step is one click away, with the new voice preselected.
    const next = screen.getByRole("link", { name: "Generate speech with “My voice”" });
    expect(next).toHaveAttribute("href", `/generate?voice=${fixtures.profile.id}`);
    expect(post).toHaveBeenCalledTimes(1);
    const [url, form, config] = post.mock.calls[0] as [string, FormData, { timeout: number }];
    expect(url).toBe("/voice/upload");
    expect(form.get("name")).toBe("My voice");
    expect(form.get("consent_confirmed")).toBe("true");
    expect(form.get("speaker_is_adult")).toBe("true");
    expect(form.get("terms_version")).toBe("1");
    expect((form.get("file") as File).name).toBe("sample.wav");
    expect((form.get("file") as File).type).toBe("audio/wav"); // File's own type, never overridden
    expect(config.timeout).toBe(120_000);
    post.mockRestore();
  });

  it("sends several clips as `files`, one clip as `file`", async () => {
    const post = vi.spyOn(http, "post").mockResolvedValue({ data: fixtures.profile });
    wrap(<UploadVoiceForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Voice name"), "Trio");
    await user.upload(screen.getByLabelText("Voice sample"), [
      wav(),
      new File([new Uint8Array(3000)], "b.wav", { type: "audio/wav" }),
    ]);
    await user.click(screen.getByRole("checkbox", { name: /right to use this voice/ }));
    await user.click(screen.getByRole("checkbox", { name: /speaker is 18 or older/ }));
    await user.click(screen.getByRole("button", { name: "Create voice" }));
    expect(await screen.findByText(/created\./i)).toBeInTheDocument();
    const form = post.mock.calls[0]![1] as FormData;
    expect(form.getAll("files").map((f) => (f as File).name)).toEqual(["sample.wav", "b.wav"]);
    expect(form.get("file")).toBeNull();
    post.mockRestore();
  });

  it("shows the recording advice and a different-speaker warning after the upload", async () => {
    const post = vi.spyOn(http, "post").mockResolvedValue({
      data: {
        ...fixtures.profile,
        quality: {
          rating: "fair",
          hints: [{ code: "noisy", severity: "warning", message: "Background noise is audible." }],
        },
        samples: [
          { position: 0, agreement: 0.9, mismatch: false },
          { position: 1, agreement: 0.5, mismatch: true },
        ],
      },
    });
    wrap(<UploadVoiceForm />);
    await fillAndSubmit();
    const report = await screen.findByRole("region", { name: "Recording quality" });
    expect(within(report).getByText("Fair recording")).toBeInTheDocument();
    expect(within(report).getByText("Background noise is audible.")).toBeInTheDocument();
    expect(within(report).getByText(/Clip 2 may be a different speaker/)).toBeInTheDocument();
    post.mockRestore();
  });

  it("tells the owner of a one-clip voice to add more clips, and a three-clip voice nothing", async () => {
    const ok = { agreement: 1, mismatch: false };
    const post = vi
      .spyOn(http, "post")
      .mockResolvedValueOnce({ data: { ...fixtures.profile, samples: [{ position: 0, ...ok }] } })
      .mockResolvedValueOnce({
        data: {
          ...fixtures.profile,
          samples: [0, 1, 2].map((position) => ({ position, ...ok })),
        },
      });
    const first = wrap(<UploadVoiceForm />);
    await fillAndSubmit();
    const report = await screen.findByRole("region", { name: "Recording quality" });
    expect(within(report).getByText(/Add more clips of the same person/)).toBeInTheDocument();
    first.unmount();
    wrap(<UploadVoiceForm />);
    await fillAndSubmit();
    await screen.findByText(/created\./i);
    expect(screen.queryByRole("region", { name: "Recording quality" })).not.toBeInTheDocument();
    post.mockRestore();
  });

  it("suggests more clips as soon as one file is chosen, and not before", async () => {
    wrap(<UploadVoiceForm />);
    const user = userEvent.setup();
    await screen.findByLabelText("Voice name");
    expect(screen.queryByText(/Tip: add 2 or 3 more clips/)).not.toBeInTheDocument();
    await user.upload(screen.getByLabelText("Voice sample"), wav());
    expect(screen.getByText(/Tip: add 2 or 3 more clips/)).toBeInTheDocument();
  });

  it("shows no quality section when the server sent none", async () => {
    const post = vi.spyOn(http, "post").mockResolvedValue({ data: fixtures.profile });
    wrap(<UploadVoiceForm />);
    await fillAndSubmit();
    await screen.findByText(/created\./i);
    expect(screen.queryByRole("region", { name: "Recording quality" })).not.toBeInTheDocument();
    post.mockRestore();
  });

  it("uploads a Firefox-style audio/vnd.wave file as audio/wav (found by the Firefox e2e run)", async () => {
    const post = vi.spyOn(http, "post").mockResolvedValue({ data: fixtures.profile });
    wrap(<UploadVoiceForm />);
    await fillAndSubmit({
      file: new File([new Uint8Array(2000)], "firefox.wav", { type: "audio/vnd.wave" }),
    });
    expect(await screen.findByText(/created\./i)).toBeInTheDocument();
    const form = post.mock.calls[0]![1] as FormData;
    expect((form.get("file") as File).type).toBe("audio/wav");
    post.mockRestore();
  });

  it("cannot bypass consent, a missing file, or a blank name (no request)", async () => {
    let calls = 0;
    server.use(
      mswHttp.post(
        `${API}/voice/upload`,
        () => ((calls += 1), HttpResponse.json({}, { status: 201 })),
      ),
    );
    wrap(<UploadVoiceForm />);
    await fillAndSubmit({ consent: false, file: null, name: "  " });
    expect(await screen.findByText(/confirm you have the right/i)).toBeInTheDocument();
    expect(screen.getByText("Choose an audio file")).toBeInTheDocument();
    expect(screen.getByText("Enter a name for this voice")).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("rejects a bad file client-side without a request", async () => {
    let calls = 0;
    server.use(
      mswHttp.post(
        `${API}/voice/upload`,
        () => ((calls += 1), HttpResponse.json({}, { status: 201 })),
      ),
    );
    wrap(<UploadVoiceForm />);
    const user = userEvent.setup();
    await user.upload(
      await screen.findByLabelText("Voice sample"),
      new File(["x"], "notes.txt", { type: "text/plain" }),
    );
    expect(await screen.findByText(/WAV, MP3 or WEBM/)).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("refuses a voice whose speaker is not confirmed as an adult, and says so", async () => {
    let calls = 0;
    server.use(
      mswHttp.post(
        `${API}/voice/upload`,
        () => ((calls += 1), HttpResponse.json({}, { status: 201 })),
      ),
    );
    wrap(<UploadVoiceForm />);
    await fillAndSubmit({ adult: false });
    expect(await screen.findByText("Confirm the speaker is 18 or older")).toBeInTheDocument();
    const adult = screen.getByRole("checkbox", { name: /speaker is 18 or older/ });
    expect(adult).toHaveAttribute("aria-invalid", "true");
    expect(adult).toHaveFocus();
    expect(calls).toBe(0);
  });

  it("on 409 terms-changed, resets consent and refetches the terms", async () => {
    let termsFetches = 0;
    server.use(
      mswHttp.get(
        `${API}/terms`,
        () => (
          (termsFetches += 1),
          HttpResponse.json({ version: "2", url: "https://example.com/terms" })
        ),
      ),
      mswHttp.post(`${API}/voice/upload`, () =>
        HttpResponse.json(
          { detail: "The terms have changed (current version 2). Review them and confirm again." },
          { status: 409 },
        ),
      ),
    );
    wrap(<UploadVoiceForm />);
    await fillAndSubmit();
    expect(await screen.findByText(/terms have changed\. Please review/i)).toBeInTheDocument();
    for (const box of screen.getAllByRole("checkbox")) expect(box).not.toBeChecked();
    await waitFor(() => expect(termsFetches).toBeGreaterThanOrEqual(2));
    expect(await screen.findByRole("link", { name: "read the terms" })).toHaveAttribute(
      "href",
      "https://example.com/terms",
    );
  });

  it("explains a missing terms page when url is null (G-18)", async () => {
    wrap(<UploadVoiceForm />);
    expect(await screen.findByText(/terms are being finalised/i)).toBeInTheDocument();
  });

  it.each([
    ["403", 403, { detail: "Email address not verified" }, /verify your email/i],
    [
      "422 file",
      422,
      { detail: "Invalid file signature (magic bytes)." },
      /invalid file signature/i,
    ],
    [
      "422 field",
      422,
      {
        detail: [
          { loc: ["body", "name"], msg: "String should have at most 255 characters", type: "x" },
        ],
      },
      /at most 255/i,
    ],
    ["429 busy", 429, { detail: "Service busy, try again shortly" }, /busy/i],
    ["429 rate", 429, { error: "Rate limit exceeded: 10 per 1 minute" }, /too many attempts/i],
    ["503", 503, { detail: "Server overloaded" }, /busy/i],
    ["500", 500, "oops", /something went wrong/i],
  ] as const)(
    "shows a clear message for %s and resyncs the list",
    async (_label, status, body, expected) => {
      let uploads = 0;
      let listFetches = 0;
      server.use(
        mswHttp.get(`${API}/voice/profiles`, () => ((listFetches += 1), HttpResponse.json([]))),
        mswHttp.post(
          `${API}/voice/upload`,
          () => ((uploads += 1), HttpResponse.json(body, { status })),
        ),
      );
      wrap(
        <>
          <UploadVoiceForm />
          <VoiceProfileList />
        </>,
      );
      await fillAndSubmit();
      expect(await screen.findByText(expected)).toBeInTheDocument();
      expect(uploads).toBe(1); // R5: never auto-retried
      await waitFor(() => expect(listFetches).toBeGreaterThanOrEqual(2));
    },
  );

  it("treats a network drop during upload as 'file may be too large' (R8)", async () => {
    server.use(mswHttp.post(`${API}/voice/upload`, () => HttpResponse.error()));
    wrap(<UploadVoiceForm />);
    await fillAndSubmit();
    expect(await screen.findByText(/may be too large/i)).toBeInTheDocument();
  });

  it("sends one request even when submitted twice quickly (R4)", async () => {
    let uploads = 0;
    server.use(
      mswHttp.post(`${API}/voice/upload`, async () => {
        uploads += 1;
        await new Promise((r) => setTimeout(r, 40));
        return HttpResponse.json(fixtures.profile, { status: 201 });
      }),
    );
    wrap(<UploadVoiceForm />);
    const user = await fillAndSubmit();
    await user.keyboard("{Enter}");
    await screen.findByText(/created\./i);
    expect(uploads).toBe(1);
  });

  it("warns on page unload only while an upload is running (R9)", async () => {
    server.use(
      mswHttp.post(`${API}/voice/upload`, async () => {
        await new Promise((r) => setTimeout(r, 60));
        return HttpResponse.json(fixtures.profile, { status: 201 });
      }),
    );
    wrap(<UploadVoiceForm />);
    const idle = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(idle);
    expect(idle.defaultPrevented).toBe(false);
    await fillAndSubmit();
    await screen.findByText(/analysing|uploading/i);
    const busy = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(busy);
    expect(busy.defaultPrevented).toBe(true);
    await screen.findByText(/created\./i);
  });

  it("leaves the verification notice to the page-level alert (no duplicate in the form)", async () => {
    server.use(
      mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token)),
      mswHttp.get(`${API}/auth/me`, () =>
        HttpResponse.json({ ...fixtures.user, email_verified_at: null }),
      ),
    );
    wrap(<UploadVoiceForm />);
    await screen.findByLabelText("Voice name");
    const button = screen.getByRole("button", { name: "Create voice" });
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAccessibleDescription("Verify your email first.");
  });
});

describe("AudioUploader", () => {
  const wav = () => new File([new Uint8Array(2000)], "sample.wav", { type: "audio/wav" });

  it("has a visible Choose file button labelling the real input, and names the pick", async () => {
    wrap(<UploadVoiceForm />);
    const input = (await screen.findByLabelText("Voice sample")) as HTMLInputElement;
    expect(input.type).toBe("file");
    expect(input.className).toContain("sr-only");
    const button = screen.getByText("Choose file");
    expect(button.tagName).toBe("LABEL");
    expect(button).toHaveAttribute("for", input.id);
    await userEvent.setup().upload(input, wav());
    expect(await screen.findByTestId("selected-file")).toHaveTextContent("sample.wav");
    expect(screen.getByText("Add another clip")).toBeInTheDocument();
  });
  it("collects several clips, ignores a repeat, and removes one", async () => {
    wrap(<UploadVoiceForm />);
    const input = (await screen.findByLabelText("Voice sample")) as HTMLInputElement;
    const user = userEvent.setup();
    const b = new File([new Uint8Array(3000)], "second.wav", { type: "audio/wav" });
    const a = wav();
    await user.upload(input, [a, b]);
    expect(await screen.findAllByTestId("selected-file")).toHaveLength(2);
    await user.upload(input, a); // the same clip again
    expect(screen.getAllByTestId("selected-file")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Remove sample.wav" }));
    const left = screen.getAllByTestId("selected-file");
    expect(left).toHaveLength(1);
    expect(left[0]).toHaveTextContent("second.wav");
  });

  it("refuses a pick that would push the clips past the size limit, keeping the earlier ones", async () => {
    wrap(<UploadVoiceForm />);
    const input = (await screen.findByLabelText("Voice sample")) as HTMLInputElement;
    const user = userEvent.setup();
    const big = (name: string) => {
      const f = new File([new Uint8Array(1)], name, { type: "audio/wav" });
      Object.defineProperty(f, "size", { value: 20 * 1024 * 1024 });
      return f;
    };
    await user.upload(input, big("one.wav"));
    await user.upload(input, big("two.wav"));
    expect(await screen.findByText(/together are larger than 25 MB/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("selected-file")).toHaveLength(1);
  });

  it("keeps the clips already chosen when another pick is invalid", async () => {
    wrap(<UploadVoiceForm />);
    const input = (await screen.findByLabelText("Voice sample")) as HTMLInputElement;
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(input, wav());
    await user.upload(input, new File([new Uint8Array(10)], "notes.txt", { type: "text/plain" }));
    expect(await screen.findByText(/WAV, MP3 or WEBM audio file/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("selected-file")).toHaveLength(1);
  });
});

describe("ProfileClips", () => {
  const clip = (position: number, over: Record<string, unknown> = {}) => ({
    position,
    agreement: 0.9,
    mismatch: false,
    quality: { rating: "good", hints: [] },
    ...over,
  });
  const withClips = (samples: unknown[]) =>
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () =>
        HttpResponse.json([{ ...fixtures.profile, samples }]),
      ),
    );

  it("lists each clip's stored quality, hints and different-speaker flag", async () => {
    withClips([
      clip(0),
      clip(1, {
        agreement: 0.5,
        mismatch: true,
        quality: {
          rating: "fair",
          hints: [{ code: "noisy", severity: "warning", message: "Background noise." }],
        },
      }),
    ]);
    wrap(<VoiceProfileList />);
    const list = await screen.findByRole("list", { name: "Clips of My voice" });
    expect(within(list).getByText("Clip 1")).toBeInTheDocument();
    expect(within(list).getByText("Fair")).toBeInTheDocument();
    expect(within(list).getByText("Background noise.")).toBeInTheDocument();
    expect(within(list).getByText("May be a different speaker")).toBeInTheDocument();
    expect(within(list).getByText("Matches the others 50%")).toBeInTheDocument();
  });

  it("removes a clip by position, and offers no removal for the only clip", async () => {
    let deleted: string | null = null;
    withClips([clip(0), clip(1)]);
    server.use(
      mswHttp.delete(`${API}/voice/profiles/:id/samples/:position`, ({ params }) => {
        deleted = String(params.position);
        return HttpResponse.json({ ...fixtures.profile, samples: [clip(0)] });
      }),
    );
    wrap(<VoiceProfileList />);
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Remove clip 2 of My voice" }));
    await waitFor(() => expect(deleted).toBe("1"));
  });

  it("hides Remove when one clip is left", async () => {
    withClips([clip(0)]);
    wrap(<VoiceProfileList />);
    await screen.findByText("Clip 1");
    expect(screen.queryByRole("button", { name: /Remove clip/ })).not.toBeInTheDocument();
  });

  it("explains a voice from before clips were tracked", async () => {
    withClips([]);
    wrap(<VoiceProfileList />);
    expect(await screen.findByText(/made before clips were tracked/i)).toBeInTheDocument();
  });

  it("adds clips with consent and the terms version, and needs consent first", async () => {
    withClips([clip(0)]);
    const post = vi
      .spyOn(http, "post")
      .mockResolvedValue({ data: { ...fixtures.profile, samples: [clip(0), clip(1)] } });
    wrap(<VoiceProfileList />);
    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: "Add clips to My voice" });
    await user.upload(
      within(form).getByLabelText("Voice sample"),
      new File([new Uint8Array(2000)], "more.wav", { type: "audio/wav" }),
    );
    await user.click(within(form).getByRole("button", { name: "Add clips" }));
    expect(await within(form).findByText(/confirm you have the right/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalled();
    await user.click(within(form).getByRole("checkbox", { name: /right to use these samples/ }));
    await user.click(within(form).getByRole("button", { name: "Add clips" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "Confirm the speaker is 18 or older",
    );
    expect(post).not.toHaveBeenCalled();
    await user.click(within(form).getByRole("checkbox", { name: /speaker is 18 or older/ }));
    await user.click(within(form).getByRole("button", { name: "Add clips" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [url, body] = post.mock.calls[0] as [string, FormData];
    expect(url).toBe(`/voice/profiles/${fixtures.profile.id}/samples`);
    expect(body.get("consent_confirmed")).toBe("true");
    expect(body.get("speaker_is_adult")).toBe("true");
    expect(body.get("terms_version")).toBe("1");
    expect((body.get("file") as File).name).toBe("more.wav");
    post.mockRestore();
  });

  it("says a voice is full at the clip limit", async () => {
    withClips(Array.from({ length: 10 }, (_, i) => clip(i)));
    wrap(<VoiceProfileList />);
    expect(await screen.findByText(/most clips it can hold/i)).toBeInTheDocument();
  });
});

describe("VoiceProfileList actions and advice", () => {
  const list = (profiles: unknown[]) =>
    server.use(mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json(profiles)));
  const ok = { position: 0, agreement: 1, mismatch: false, quality: { rating: "good", hints: [] } };

  it("offers Generate on a ready voice, with that voice preselected, and not on a failed one", async () => {
    list([
      profile({ id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "Ready one" }),
      profile({ id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", name: "Broken one", status: "failed" }),
    ]);
    wrap(<VoiceProfileList />);
    const link = await screen.findByRole("link", { name: "Generate speech with Ready one" });
    expect(link).toHaveAttribute("href", "/generate?voice=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    expect(screen.queryByRole("link", { name: /Generate speech with Broken one/ })).toBeNull();
  });

  it("surfaces clip advice on the card without opening the Clips panel", async () => {
    list([
      profile({
        samples: [
          ok,
          { ...ok, position: 1, mismatch: true, quality: { rating: "fair", hints: [] } },
          { ...ok, position: 2 },
        ],
      }),
    ]);
    wrap(<VoiceProfileList />);
    expect(
      await screen.findByText(
        "Clip 2 may be a different speaker. A recording could be cleaner. Open Clips for tips.",
      ),
    ).toBeInTheDocument();
  });

  it("shows no advice line for a voice whose clips are fine", async () => {
    list([profile({ samples: [ok, { ...ok, position: 1 }, { ...ok, position: 2 }] })]);
    wrap(<VoiceProfileList />);
    await screen.findByText("Clips (3)");
    expect(screen.queryByText(/Open Clips for tips/)).toBeNull();
  });

  it("nudges a voice made from one clip to add more, on the card", async () => {
    list([profile({ samples: [ok] })]);
    wrap(<VoiceProfileList />);
    expect(await screen.findByText(/Add more clips of the same person/)).toBeInTheDocument();
  });

  it("calls a voice with no clip rows just Clips, not Clips (0)", async () => {
    list([profile({ samples: [] })]);
    wrap(<VoiceProfileList />);
    expect(await screen.findByText("Clips")).toBeInTheDocument();
    expect(screen.queryByText("Clips (0)")).toBeNull();
  });
});
