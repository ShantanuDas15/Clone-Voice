import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountSection } from "@/components/account-section";
import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { HistoryList } from "@/components/history-list";
import { flattenHistory } from "@/hooks/use-history";
import {
  type Generation,
  type HistoryPage,
  hasMoreHistory,
  isFailedGeneration,
} from "@/lib/api/history";
import { __resetSessionForTests } from "@/lib/auth/session";
import { fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/voices",
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const API = "http://api.test/api/v1";
const gen = (over: Partial<Generation> = {}): Generation => ({ ...fixtures.generation, ...over });
const page = (n: number, total: number | null, offset = 0): HistoryPage => ({
  items: Array.from({ length: n }, (_, i) => gen({ id: `id-${offset + i}` })),
  total,
  offset,
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
  replace.mockClear();
  vi.mocked(URL.createObjectURL).mockClear();
  vi.mocked(URL.revokeObjectURL).mockClear();
});

describe("history helpers", () => {
  it("hasMoreHistory uses the total when known and page fullness otherwise", () => {
    expect(hasMoreHistory(page(0, 0))).toBe(false);
    expect(hasMoreHistory(page(50, 50))).toBe(false);
    expect(hasMoreHistory(page(50, 51))).toBe(true);
    expect(hasMoreHistory(page(50, null))).toBe(true);
    expect(hasMoreHistory(page(7, null))).toBe(false);
    expect(hasMoreHistory(page(0, 5, 50))).toBe(false); // stale total, empty page: stop
  });

  it("flattenHistory drops duplicate ids across pages", () => {
    const merged = flattenHistory([page(2, 4, 0), { ...page(2, 4, 1), offset: 1 }]);
    expect(merged.map((g) => g.id)).toEqual(["id-0", "id-1", "id-2"]);
  });

  it("classifies failed rows", () => {
    expect(isFailedGeneration(gen())).toBe(false);
    expect(isFailedGeneration(gen({ status: "failed", output_filename: "" }))).toBe(true);
    expect(isFailedGeneration(gen({ output_filename: "" }))).toBe(true);
  });
});

describe("HistoryList", () => {
  it("shows how a generation was made, on completed and failed rows, and nothing for a plain one", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () =>
        HttpResponse.json([
          gen({ id: "a", emotion: "sad", intensity: 0.4, style_applied: true, seed: 7 }),
          gen({
            id: "b",
            status: "failed",
            output_filename: "",
            audio_available: false,
            emotion: "happy",
            intensity: 0.9,
          }),
          gen({ id: "c" }),
        ]),
      ),
    );
    wrap(<HistoryList />);
    const shown = await screen.findAllByTestId("generation-details");
    expect(shown.map((n) => n.textContent)).toEqual([
      "Delivery: Sad at 40% · Seed 7",
      "Delivery: Happy at 90%",
    ]);
  });

  it("shows an empty state", async () => {
    server.use(mswHttp.get(`${API}/synthesize/history`, () => HttpResponse.json([])));
    wrap(<HistoryList />);
    expect(await screen.findByText(/nothing generated yet/i)).toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () => new HttpResponse(null, { status: 500 })),
    );
    wrap(<HistoryList />);
    expect(await screen.findByText(/couldn't load your history/i)).toBeInTheDocument();
    server.use(mswHttp.get(`${API}/synthesize/history`, () => HttpResponse.json([gen()])));
    await userEvent.click(screen.getByRole("button", { name: /^Try again/ }));
    expect(await screen.findByText("Hello there.")).toBeInTheDocument();
  });

  it("renders rows, truncating long text with an expander and marking failed rows", async () => {
    const long = "word ".repeat(80).trim();
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () =>
        HttpResponse.json([
          gen({ id: "a", input_text: long }),
          gen({
            id: "b",
            input_text: "Broke",
            status: "failed",
            output_filename: "",
            duration_seconds: null,
          }),
        ]),
      ),
    );
    wrap(<HistoryList />);
    const more = await screen.findByRole("button", { name: "Show more" });
    expect(screen.queryByText(long)).not.toBeInTheDocument();
    await userEvent.click(more);
    expect(screen.getByText(long)).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/No audio was produced/)).toBeInTheDocument();
  });

  it("loads more pages with offset and never duplicates rows", async () => {
    const offsets: string[] = [];
    server.use(
      mswHttp.get(`${API}/synthesize/history`, ({ request }) => {
        const offset = new URL(request.url).searchParams.get("offset") ?? "0";
        offsets.push(offset);
        const rows =
          offset === "0"
            ? Array.from({ length: 50 }, (_, i) => gen({ id: `g${i}`, input_text: `Row ${i}` }))
            : [gen({ id: "g49", input_text: "Row 49" }), gen({ id: "g50", input_text: "Row 50" })];
        return HttpResponse.json(rows, { headers: { "X-Total-Count": "51" } });
      }),
    );
    wrap(<HistoryList />);
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Row 50")).toBeInTheDocument();
    expect(screen.getAllByText("Row 49")).toHaveLength(1);
    expect(offsets).toEqual(["0", "50"]);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("fetches audio with auth on play and revokes the object URL on unmount", async () => {
    const view = wrap(<HistoryList />);
    await userEvent.click(await screen.findByRole("button", { name: /^Play:/ }));
    expect(
      await screen.findByLabelText(/generated audio from/i, { selector: "audio" }),
    ).toBeInTheDocument();
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("explains expiry when the audio is gone (410) or flagged unavailable", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/:id/audio`, () =>
        HttpResponse.json({ detail: "The audio for this generation has expired" }, { status: 410 }),
      ),
    );
    wrap(<HistoryList />);
    await userEvent.click(await screen.findByRole("button", { name: /^Play:/ }));
    expect(await screen.findByText(/audio is no longer available/i)).toBeInTheDocument();
  });

  it("shows expiry up front when audio_available is false", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () =>
        HttpResponse.json([gen({ audio_available: false })]),
      ),
    );
    wrap(<HistoryList />);
    expect(await screen.findByText(/audio is no longer available/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Play:/ })).not.toBeInTheDocument();
  });

  it("offers retry after a transient audio error", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/:id/audio`, () => new HttpResponse(null, { status: 503 })),
    );
    wrap(<HistoryList />);
    await userEvent.click(await screen.findByRole("button", { name: /^Play:/ }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Try again/ })).toBeInTheDocument();
  });
});

describe("AccountSection: name", () => {
  it("saves a new name and sends only the name", async () => {
    let body: unknown;
    server.use(
      mswHttp.patch(`${API}/auth/me`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...fixtures.user, name: "Grace" });
      }),
    );
    wrap(<AccountSection />);
    const input = await screen.findByLabelText("Display name");
    await userEvent.clear(input);
    await userEvent.type(input, "  Grace ");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(body).toEqual({ name: "Grace" }));
  });

  it("rejects a blank name client-side without a request", async () => {
    const patch = vi.fn();
    server.use(mswHttp.patch(`${API}/auth/me`, () => (patch(), HttpResponse.json(fixtures.user))));
    wrap(<AccountSection />);
    const input = await screen.findByLabelText("Display name");
    await userEvent.clear(input);
    await userEvent.type(input, "   ");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(await screen.findByText("Enter your name")).toBeInTheDocument();
    expect(patch).not.toHaveBeenCalled();
  });

  it("shows the server's 422 on the field and keeps the old name", async () => {
    server.use(
      mswHttp.patch(`${API}/auth/me`, () =>
        HttpResponse.json(
          {
            detail: [{ loc: ["body", "name"], msg: "Name must not be blank", type: "value_error" }],
          },
          { status: 422 },
        ),
      ),
    );
    wrap(<AccountSection />);
    const input = await screen.findByLabelText("Display name");
    await userEvent.type(input, "x");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(await screen.findByText("Name must not be blank")).toBeInTheDocument();
  });
});

describe("AccountSection: delete", () => {
  async function openDialog() {
    await screen.findByLabelText("Display name");
    await userEvent.click(screen.getByRole("button", { name: /delete my account/i }));
  }

  it("requires the typed word and a password before enabling deletion", async () => {
    wrap(<AccountSection />);
    await openDialog();
    const button = screen.getByRole("button", { name: "Delete account" });
    expect(button).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/type delete/i), "DELETE");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(await screen.findByText(/enter your password/i)).toBeInTheDocument();
  });

  it("sends a JSON body with the password, then signs out and clears the cache", async () => {
    let body: unknown;
    server.use(
      mswHttp.delete(`${API}/auth/me`, async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    wrap(<AccountSection />);
    await openDialog();
    client.setQueryData(["history"], "cached");
    await userEvent.type(screen.getByLabelText(/type delete/i), "DELETE");
    await userEvent.type(screen.getByLabelText("Password"), "hunter2hunter2");
    await userEvent.click(screen.getByRole("button", { name: "Delete account" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(body).toEqual({ password: "hunter2hunter2" });
    expect(client.getQueryData(["history"])).toBeUndefined();
  });

  it("omits the password for a Google-only account", async () => {
    let body: unknown;
    server.use(
      mswHttp.get(`${API}/auth/me`, () =>
        HttpResponse.json({ ...fixtures.user, provider: "google", has_password: false }),
      ),
      mswHttp.delete(`${API}/auth/me`, async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    wrap(<AccountSection />);
    await openDialog();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/type delete/i), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: "Delete account" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(body).toEqual({});
  });

  it("shows a wrong-password error and stays signed in", async () => {
    server.use(
      mswHttp.delete(`${API}/auth/me`, () =>
        HttpResponse.json({ detail: "Incorrect password" }, { status: 403 }),
      ),
    );
    wrap(<AccountSection />);
    await openDialog();
    await userEvent.type(screen.getByLabelText(/type delete/i), "DELETE");
    await userEvent.type(screen.getByLabelText("Password"), "wrongwrong");
    await userEvent.click(screen.getByRole("button", { name: "Delete account" }));
    expect(await screen.findByText("That password is incorrect.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows the throttle countdown on 429 with Retry-After", async () => {
    server.use(
      mswHttp.delete(`${API}/auth/me`, () =>
        HttpResponse.json(
          { detail: "Too many attempts" },
          { status: 429, headers: { "Retry-After": "600" } },
        ),
      ),
    );
    wrap(<AccountSection />);
    await openDialog();
    await userEvent.type(screen.getByLabelText(/type delete/i), "DELETE");
    await userEvent.type(screen.getByLabelText("Password"), "whatever1");
    await userEvent.click(screen.getByRole("button", { name: "Delete account" }));
    expect(await screen.findByText(/try again in 10 minutes/i)).toBeInTheDocument();
  });

  it("after a network failure, treats a 401 on /me as a completed deletion", async () => {
    let meCalls = 0;
    server.use(
      mswHttp.delete(`${API}/auth/me`, () => HttpResponse.error()),
      mswHttp.get(`${API}/auth/me`, () => {
        meCalls += 1;
        return meCalls === 1
          ? HttpResponse.json(fixtures.user)
          : HttpResponse.json({ detail: "Not authenticated" }, { status: 401 });
      }),
      mswHttp.post(`${API}/auth/refresh`, ({ request }) => {
        void request;
        return meCalls === 0
          ? HttpResponse.json(fixtures.token)
          : HttpResponse.json({ detail: "gone" }, { status: 401 });
      }),
    );
    wrap(<AccountSection />);
    await openDialog();
    await userEvent.type(screen.getByLabelText(/type delete/i), "DELETE");
    await userEvent.type(screen.getByLabelText("Password"), "whatever1");
    await userEvent.click(screen.getByRole("button", { name: "Delete account" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  });

  it("after a network failure with the account still present, says so and stays", async () => {
    server.use(mswHttp.delete(`${API}/auth/me`, () => HttpResponse.error()));
    wrap(<AccountSection />);
    await openDialog();
    await userEvent.type(screen.getByLabelText(/type delete/i), "DELETE");
    await userEvent.type(screen.getByLabelText("Password"), "whatever1");
    await userEvent.click(screen.getByRole("button", { name: "Delete account" }));
    expect(await screen.findByText(/account still exists/i)).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("retention comes from the server (FE-UX39)", () => {
  const terms = (body: Record<string, unknown>) =>
    server.use(mswHttp.get(`${API}/terms`, () => HttpResponse.json(body)));
  const expiredHistory = () =>
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () =>
        HttpResponse.json([gen({ audio_available: false })]),
      ),
    );

  it("states the configured period in the note and in the expiry message", async () => {
    terms({ version: "1", url: null, output_retention_days: 14 });
    expiredHistory();
    wrap(<HistoryList />);
    expect(await screen.findByText(/Audio is kept for 14 days\./)).toBeInTheDocument();
    expect(screen.getByText(/clips are kept for 14 days/)).toBeInTheDocument();
  });

  it.each([
    ["null (kept until deleted)", { version: "1", url: null, output_retention_days: null }],
    ["a field an older backend does not send", { version: "1", url: null }],
  ])("states no figure when the server gives %s", async (_n, body) => {
    terms(body);
    expiredHistory();
    wrap(<HistoryList />);
    expect(await screen.findByText(/audio is no longer available/i)).toBeInTheDocument();
    expect(screen.queryByText(/kept for/)).not.toBeInTheDocument();
  });

  it("states no figure when the terms request fails", async () => {
    server.use(mswHttp.get(`${API}/terms`, () => HttpResponse.error()));
    expiredHistory();
    wrap(<HistoryList />);
    expect(await screen.findByText(/audio is no longer available/i)).toBeInTheDocument();
    expect(screen.queryByText(/kept for/)).not.toBeInTheDocument();
  });
});

describe("History rows: names, focus, exclusive playback, count, expiry, download", () => {
  const rows = (items: unknown[], total?: number) =>
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () =>
        HttpResponse.json(items, {
          headers: total === undefined ? {} : { "X-Total-Count": String(total) },
        }),
      ),
    );

  it("tells identical buttons apart by the row's text", async () => {
    rows([
      gen({ id: "a", input_text: "First line" }),
      gen({ id: "b", input_text: "Second line that is considerably longer than forty characters" }),
    ]);
    wrap(<HistoryList />);
    expect(await screen.findByRole("button", { name: "Play: First line" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Play: Second line that is considerably longer…" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download: First line" })).toBeInTheDocument();
  });

  it("moves focus to the player's play control when Play is pressed", async () => {
    wrap(<HistoryList />);
    await userEvent.click(await screen.findByRole("button", { name: /^Play:/ }));
    const control = await screen.findByRole("button", { name: /Generated audio from/ });
    await waitFor(() => expect(control).toHaveFocus());
  });

  it("pauses the take that was playing when another starts", async () => {
    const { claimPlayback } = await import("@/lib/exclusive-playback");
    const a = document.createElement("audio");
    const b = document.createElement("audio");
    const pauseA = vi.spyOn(a, "pause").mockImplementation(() => {});
    const pauseB = vi.spyOn(b, "pause").mockImplementation(() => {});
    claimPlayback(a);
    claimPlayback(b);
    expect(pauseA).toHaveBeenCalledTimes(1);
    claimPlayback(b); // the same one again pauses nothing
    expect(pauseB).not.toHaveBeenCalled();
  });

  it("says where you are in the history, and announces what Load more added", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/history`, ({ request }) => {
        const offset = new URL(request.url).searchParams.get("offset") ?? "0";
        const items =
          offset === "0"
            ? Array.from({ length: 50 }, (_, i) => gen({ id: `g${i}`, input_text: `Row ${i}` }))
            : [gen({ id: "g50", input_text: "Row 50" })];
        return HttpResponse.json(items, { headers: { "X-Total-Count": "51" } });
      }),
    );
    wrap(<HistoryList />);
    expect(await screen.findByText("Showing 50 of 51.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Loaded 1 more. Showing 51 of 51.")).toBeInTheDocument();
    expect(screen.getByText("51 generations.")).toBeInTheDocument();
  });

  it("states a single generation in the singular and nothing when the total is unknown", async () => {
    rows([gen()], 1);
    const view = wrap(<HistoryList />);
    expect(await screen.findByText("1 generation.")).toBeInTheDocument();
    view.unmount();
    rows([gen()]);
    wrap(<HistoryList />);
    await screen.findByRole("button", { name: /^Play:/ });
    expect(screen.queryByText(/generations?\.$/)).toBeNull();
  });

  it("marks an expired row with a badge", async () => {
    rows([gen({ audio_available: false })]);
    wrap(<HistoryList />);
    expect(await screen.findByText("Expired")).toBeInTheDocument();
  });

  it("warns that audio is about to expire, only when the server gave a retention period", async () => {
    const created = new Date(Date.now() - 28 * 86_400_000).toISOString(); // 30-day retention: 2 left
    server.use(
      mswHttp.get(`${API}/terms`, () =>
        HttpResponse.json({ version: "1", text: "", url: null, output_retention_days: 30 }),
      ),
    );
    rows([gen({ created_at: created })]);
    wrap(<HistoryList />);
    expect(
      await screen.findByText(/Expires in [12] days?\. Download it to keep it\./),
    ).toBeInTheDocument();
  });

  it("does not warn about expiry without a retention period", async () => {
    server.use(
      mswHttp.get(`${API}/terms`, () =>
        HttpResponse.json({ version: "1", text: "", url: null, output_retention_days: null }),
      ),
    );
    rows([gen({ created_at: new Date(Date.now() - 86_400_000).toISOString() })]);
    wrap(<HistoryList />);
    await screen.findByRole("button", { name: /^Play:/ });
    expect(screen.queryByText(/Expires in/)).toBeNull();
  });

  it("downloads without playing first, and says so when the audio has expired", async () => {
    const saved: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved.push(this.download);
    });
    wrap(<HistoryList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Download:/ }));
    await waitFor(() => expect(saved).toEqual([`clonevoice-${fixtures.generation.id}.wav`]));
    expect(screen.queryByLabelText(/generated audio from/i, { selector: "audio" })).toBeNull();
    server.use(
      mswHttp.get(`${API}/synthesize/:id/audio`, () =>
        HttpResponse.json({ detail: "expired" }, { status: 410 }),
      ),
    );
    await user.click(screen.getByRole("button", { name: /^Download:/ }));
    expect(await screen.findByText(/audio is no longer available/i)).toBeInTheDocument();
    click.mockRestore();
  });
});

describe("Deleting a generation from History", () => {
  const two = [
    gen({ id: "g1", input_text: "First one" }),
    gen({ id: "g2", input_text: "Second one" }),
  ];
  /** A mutable server-side list, so a refetch after the delete sees it gone. */
  function serve(initial: Generation[], onDelete?: (id: string) => Response | undefined) {
    let rows = [...initial];
    const deleted: string[] = [];
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () =>
        HttpResponse.json(rows, { headers: { "X-Total-Count": String(rows.length) } }),
      ),
      mswHttp.delete(`${API}/synthesize/:id`, ({ params }) => {
        const id = String(params.id);
        const custom = onDelete?.(id);
        if (custom) return custom;
        deleted.push(id);
        rows = rows.filter((r) => r.id !== id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    return deleted;
  }

  it("asks first, names the text, and does nothing on Cancel", async () => {
    const deleted = serve(two);
    wrap(<HistoryList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete: Second one" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Delete this audio?")).toBeInTheDocument();
    expect(within(dialog).getByText("“Second one”")).toBeInTheDocument();
    expect(
      within(dialog).getByText(/permanently deletes the audio and the text/i),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(deleted).toEqual([]);
    expect(screen.getByText("Second one")).toBeInTheDocument();
  });

  it("deletes after confirmation: the row goes, the count updates, and it is announced", async () => {
    const deleted = serve(two);
    wrap(<HistoryList />);
    const user = userEvent.setup();
    expect(await screen.findByText("2 generations.")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Delete: First one" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete audio" }),
    );
    await waitFor(() => expect(screen.queryByText("First one")).toBeNull());
    expect(deleted).toEqual(["g1"]);
    expect(await screen.findByText("1 generation.")).toBeInTheDocument();
    expect(await screen.findByText("Deleted.")).toBeInTheDocument();
  });

  it("moves focus to the next row's first control", async () => {
    serve(two);
    wrap(<HistoryList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete: First one" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete audio" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Play: Second one" })).toHaveFocus(),
    );
  });

  it("moves focus to the row before when the last row is deleted", async () => {
    serve(two);
    wrap(<HistoryList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete: Second one" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete audio" }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Play: First one" })).toHaveFocus(),
    );
  });

  it("shows the empty state after the only generation is deleted", async () => {
    serve([gen({ id: "only", input_text: "Lonely" })]);
    wrap(<HistoryList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete: Lonely" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete audio" }),
    );
    expect(await screen.findByText(/nothing generated yet/i)).toBeInTheDocument();
    expect(await screen.findByText("Deleted.")).toBeInTheDocument();
  });

  it("treats a 404 as already gone", async () => {
    serve(two, () => HttpResponse.json({ detail: "Generation not found" }, { status: 404 }));
    wrap(<HistoryList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete: First one" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete audio" }),
    );
    expect(await screen.findByText("Deleted.")).toBeInTheDocument();
  });

  it("puts the row back and says so when the delete fails", async () => {
    serve(two, () =>
      HttpResponse.json({ detail: "Failed to delete the generation" }, { status: 500 }),
    );
    wrap(<HistoryList />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Delete: First one" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete audio" }),
    );
    await waitFor(() => expect(screen.getByText("First one")).toBeInTheDocument());
    expect(screen.getByText("2 generations.")).toBeInTheDocument();
    expect(screen.queryByText("Deleted.")).toBeNull();
  });

  it("offers Delete on a failed row too", async () => {
    serve([
      gen({
        id: "bad",
        input_text: "Broke",
        status: "failed",
        output_filename: "",
        duration_seconds: null,
      }),
    ]);
    wrap(<HistoryList />);
    expect(await screen.findByRole("button", { name: "Delete: Broke" })).toBeInTheDocument();
  });
});

describe("withoutGeneration", () => {
  const data = (total: number | null) => ({
    pageParams: [0],
    pages: [{ items: [gen({ id: "a" }), gen({ id: "b" })], total, offset: 0 }],
  });

  it("drops the row and one from the total", async () => {
    const { withoutGeneration } = await import("@/hooks/use-history");
    const out = withoutGeneration(data(2), "a");
    expect(out.pages[0]!.items.map((g) => g.id)).toEqual(["b"]);
    expect(out.pages[0]!.total).toBe(1);
  });

  it("changes nothing for an id that is not loaded, keeps an unknown total unknown, never goes below 0", async () => {
    const { withoutGeneration } = await import("@/hooks/use-history");
    const same = data(2);
    expect(withoutGeneration(same, "zzz")).toBe(same);
    expect(withoutGeneration(data(null), "a").pages[0]!.total).toBeNull();
    expect(withoutGeneration(data(0), "a").pages[0]!.total).toBe(0);
  });
});

describe("AccountSection: details", () => {
  const me = (over: Record<string, unknown>) =>
    server.use(
      mswHttp.get(`${API}/auth/me`, () => HttpResponse.json({ ...fixtures.user, ...over })),
    );

  it("shows a verified email, the date joined without a time, and the password row", async () => {
    wrap(<AccountSection />);
    await screen.findByLabelText("Display name");
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.queryByText("Not verified")).toBeNull();
    expect(screen.getByText("Oct 1, 2026")).toBeInTheDocument(); // no "12:00 AM"
    expect(screen.getByText(/^Set\./)).toBeInTheDocument();
    const reset = screen.getByRole("link", { name: "Reset it by email" });
    expect(reset).toHaveAttribute("href", "/forgot-password");
    expect(reset).toHaveClass("min-h-11");
  });

  it("says an unverified email is unverified, what it blocks, and offers to resend", async () => {
    me({ email_verified_at: null });
    wrap(<AccountSection />);
    expect(await screen.findByText("Not verified")).toBeInTheDocument();
    expect(
      screen.getByText(/can't create voices or generate speech until you verify/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resend verification email" })).toBeInTheDocument();
    expect(screen.queryByText("Verified")).toBeNull();
  });

  it("offers a Google-only account to set a password by email", async () => {
    me({ provider: "google", has_password: false });
    wrap(<AccountSection />);
    expect(await screen.findByText(/^Not set\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set one by email" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("lays the details out as one aligned list, with the danger section as an h2", async () => {
    wrap(<AccountSection />);
    await screen.findByLabelText("Display name");
    const labels = screen.getAllByRole("term").map((t) => t.textContent);
    expect(labels).toEqual(["Email", "Verification", "Sign-in", "Password", "Member since"]);
    expect(screen.getByRole("heading", { level: 2, name: "Delete account" })).toBeInTheDocument();
  });

  it("restates what is erased inside the delete dialog", async () => {
    wrap(<AccountSection />);
    await screen.findByLabelText("Display name");
    await userEvent.click(screen.getByRole("button", { name: /delete my account/i }));
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText(
        /permanently erases your account, every voice and every generated clip/i,
      ),
    ).toBeInTheDocument();
  });
});
