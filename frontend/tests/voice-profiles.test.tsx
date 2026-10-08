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
    opts: { consent?: boolean; file?: File | null; name?: string } = {},
  ) {
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Voice name"), opts.name ?? "My voice");
    if (opts.file !== null)
      await user.upload(screen.getByLabelText("Voice sample"), opts.file ?? wav());
    if (opts.consent !== false) await user.click(screen.getByRole("checkbox"));
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
    expect(post).toHaveBeenCalledTimes(1);
    const [url, form, config] = post.mock.calls[0] as [string, FormData, { timeout: number }];
    expect(url).toBe("/voice/upload");
    expect(form.get("name")).toBe("My voice");
    expect(form.get("consent_confirmed")).toBe("true");
    expect(form.get("terms_version")).toBe("1");
    expect((form.get("file") as File).name).toBe("sample.wav");
    expect((form.get("file") as File).type).toBe("audio/wav"); // File's own type, never overridden
    expect(config.timeout).toBe(120_000);
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
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    await waitFor(() => expect(termsFetches).toBeGreaterThanOrEqual(2));
    expect(await screen.findByRole("link", { name: "read the terms" })).toHaveAttribute(
      "href",
      "https://example.com/terms",
    );
  });

  it("explains a missing terms page when url is null (G-18)", async () => {
    wrap(<UploadVoiceForm />);
    expect(await screen.findByText(/not published yet/i)).toBeInTheDocument();
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
    expect(screen.queryByText(/verify your email/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Create voice" })).toBeEnabled();
  });
});
