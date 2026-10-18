import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { HistoryList } from "@/components/history-list";
import { type Generation, fetchHistory } from "@/lib/api/history";
import { __resetSessionForTests } from "@/lib/auth/session";
import { fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/history",
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const API = "http://api.test/api/v1";
const ADA = fixtures.profile;
const BOB = { ...fixtures.profile, id: "55555555-5555-4555-8555-555555555555", name: "Bob" };
const gen = (over: Partial<Generation>): Generation => ({ ...fixtures.generation, ...over });
const ROWS = [
  gen({ id: "a1", input_text: "Happy birthday Sam" }),
  gen({ id: "a2", input_text: "The weather today" }),
  gen({
    id: "b1",
    input_text: "Birthday cake for Bob",
    voice_profile_id: BOB.id,
    voice_profile_name: "Bob",
  }),
];

interface Ask {
  q: string | null;
  voice: string | null;
}

/** Serves profiles and a history that honours `q` and `voice_profile_id`; records each request. */
function serve(rows: Generation[] = ROWS, profiles: unknown[] = [ADA, BOB]) {
  const asked: Ask[] = [];
  server.use(
    mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json(profiles)),
    mswHttp.get(`${API}/synthesize/history`, ({ request }) => {
      const params = new URL(request.url).searchParams;
      const q = params.get("q");
      const voice = params.get("voice_profile_id");
      asked.push({ q, voice });
      const shown = rows
        .filter((r) => !voice || r.voice_profile_id === voice)
        .filter((r) => !q || r.input_text.toLowerCase().includes(q.toLowerCase()));
      return HttpResponse.json(shown, { headers: { "X-Total-Count": String(shown.length) } });
    }),
  );
  return asked;
}

function wrap() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <HistoryList />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

const box = () => screen.getByLabelText("Search your text");

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
});

describe("fetchHistory search", () => {
  it("sends q only when one is given", async () => {
    const asked = serve();
    await fetchHistory(0);
    await fetchHistory(0, undefined, undefined, undefined, "birthday");
    expect(asked.map((a) => a.q)).toEqual([null, "birthday"]);
  });
});

describe("History search", () => {
  it("is offered while there is history, limited to what the server accepts", async () => {
    serve();
    wrap();
    await screen.findByText("Happy birthday Sam");
    expect(box()).toHaveAttribute("type", "search");
    expect(box()).toHaveAttribute("maxlength", "200");
  });

  it("is not offered when there is no history at all", async () => {
    serve([]);
    wrap();
    expect(await screen.findByText(/nothing generated yet/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Search your text")).not.toBeInTheDocument();
  });

  it("waits for typing to pause: one request for the whole word", async () => {
    const asked = serve();
    wrap();
    await screen.findByText("Happy birthday Sam");
    await userEvent.type(box(), "birth");
    await waitFor(() => expect(asked.at(-1)?.q).toBe("birth"));
    expect(asked.filter((a) => a.q !== null).map((a) => a.q)).toEqual(["birth"]);
  });

  it("narrows the list and says how many matched", async () => {
    serve();
    wrap();
    await screen.findByText("The weather today");
    await userEvent.type(box(), "birthday");
    await waitFor(() => expect(screen.queryByText("The weather today")).not.toBeInTheDocument());
    expect(screen.getByText("Happy birthday Sam")).toBeInTheDocument();
    expect(screen.getByText("Birthday cake for Bob")).toBeInTheDocument();
    expect(await screen.findByText("2 generations found.")).toBeInTheDocument();
  });

  it("trims the text, and a blank box searches for nothing", async () => {
    const asked = serve();
    wrap();
    await screen.findByText("Happy birthday Sam");
    await userEvent.type(box(), "   ");
    await new Promise((resolve) => setTimeout(resolve, 450));
    expect(asked.every((a) => a.q === null)).toBe(true);
    await userEvent.clear(box());
    await userEvent.type(box(), "  weather ");
    await waitFor(() => expect(asked.at(-1)?.q).toBe("weather"));
  });

  it("keeps the current list on screen while a new search loads", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    serve();
    server.use(
      mswHttp.get(`${API}/synthesize/history`, async ({ request }) => {
        if (new URL(request.url).searchParams.get("q")) await gate;
        return HttpResponse.json(ROWS, { headers: { "X-Total-Count": String(ROWS.length) } });
      }),
    );
    wrap();
    await screen.findByText("The weather today");
    await userEvent.type(box(), "weather");
    await new Promise((resolve) => setTimeout(resolve, 450));
    expect(screen.getByText("The weather today")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading history")).not.toBeInTheDocument();
    release();
  });

  it("says nothing matched, quoting the search, and Clear search brings everything back", async () => {
    serve();
    wrap();
    await screen.findByText("Happy birthday Sam");
    await userEvent.type(box(), "zebra");
    expect(await screen.findByText(/match “zebra”/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(box()).toHaveValue("");
    expect(await screen.findByText("Happy birthday Sam")).toBeInTheDocument();
    expect(screen.getByText("The weather today")).toBeInTheDocument();
    expect(screen.queryByText(/match “zebra”/)).not.toBeInTheDocument();
  });

  it("does not treat text as markup", async () => {
    serve();
    wrap();
    await screen.findByText("Happy birthday Sam");
    await userEvent.type(box(), "<b>x</b>");
    expect(await screen.findByText(/match “<b>x<\/b>”/)).toBeInTheDocument();
    expect(document.querySelector("main b, body b")).toBeNull();
  });

  it("combines with the voice filter", async () => {
    const asked = serve();
    wrap();
    await screen.findByText("Happy birthday Sam");
    await userEvent.selectOptions(screen.getByLabelText("Voice"), BOB.id);
    await screen.findByText("Birthday cake for Bob");
    await userEvent.type(box(), "birthday");
    await waitFor(() => expect(asked.at(-1)).toEqual({ q: "birthday", voice: BOB.id }));
    expect(screen.queryByText("Happy birthday Sam")).not.toBeInTheDocument();
  });

  it("shows the error state with Try again when the search fails", async () => {
    serve();
    server.use(
      mswHttp.get(`${API}/synthesize/history`, ({ request }) =>
        new URL(request.url).searchParams.get("q")
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json(ROWS, { headers: { "X-Total-Count": "3" } }),
      ),
    );
    wrap();
    await screen.findByText("Happy birthday Sam");
    await userEvent.type(box(), "birthday");
    expect(await screen.findByText(/couldn't load your history/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
