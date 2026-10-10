import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
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
    expect(screen.getByText(/failed — no audio/i)).toBeInTheDocument();
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
    await userEvent.click(await screen.findByRole("button", { name: "Play" }));
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
    await userEvent.click(await screen.findByRole("button", { name: "Play" }));
    expect(await screen.findByText(/audio has expired/i)).toBeInTheDocument();
  });

  it("shows expiry up front when audio_available is false", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/history`, () =>
        HttpResponse.json([gen({ audio_available: false })]),
      ),
    );
    wrap(<HistoryList />);
    expect(await screen.findByText(/audio has expired/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Play" })).not.toBeInTheDocument();
  });

  it("offers retry after a transient audio error", async () => {
    server.use(
      mswHttp.get(`${API}/synthesize/:id/audio`, () => new HttpResponse(null, { status: 503 })),
    );
    wrap(<HistoryList />);
    await userEvent.click(await screen.findByRole("button", { name: "Play" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
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
    expect(await screen.findByText(/audio has expired/i)).toBeInTheDocument();
    expect(screen.queryByText(/kept for/)).not.toBeInTheDocument();
  });

  it("states no figure when the terms request fails", async () => {
    server.use(mswHttp.get(`${API}/terms`, () => HttpResponse.error()));
    expiredHistory();
    wrap(<HistoryList />);
    expect(await screen.findByText(/audio has expired/i)).toBeInTheDocument();
    expect(screen.queryByText(/kept for/)).not.toBeInTheDocument();
  });
});
