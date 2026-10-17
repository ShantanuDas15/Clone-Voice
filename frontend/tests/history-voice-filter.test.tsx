import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
  gen({ id: "a1", input_text: "Ada says hi" }),
  gen({
    id: "b1",
    input_text: "Bob says hi",
    voice_profile_id: BOB.id,
    voice_profile_name: "Bob",
  }),
];

/** Serves profiles and a history that honours `voice_profile_id`; returns the ids it was asked for. */
function serve(profiles: unknown[], rows: Generation[] = ROWS) {
  const asked: (string | null)[] = [];
  server.use(
    mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json(profiles)),
    mswHttp.get(`${API}/synthesize/history`, ({ request }) => {
      const id = new URL(request.url).searchParams.get("voice_profile_id");
      asked.push(id);
      const shown = id ? rows.filter((r) => r.voice_profile_id === id) : rows;
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

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
});

describe("fetchHistory voice filter", () => {
  it("sends voice_profile_id only when one is given", async () => {
    const asked = serve([ADA, BOB]);
    await fetchHistory(0);
    await fetchHistory(0, undefined, undefined, BOB.id);
    expect(asked).toEqual([null, BOB.id]);
  });
});

describe("History voice filter", () => {
  it("is hidden with one voice", async () => {
    serve([ADA]);
    wrap();
    expect(await screen.findByText("Ada says hi")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /voice/i })).toBeNull();
  });

  it("narrows the list and its count to the chosen voice, and back to all", async () => {
    const asked = serve([ADA, BOB]);
    wrap();
    const user = userEvent.setup();
    expect(await screen.findByText("2 generations.")).toBeInTheDocument();
    const select = await screen.findByRole("combobox", { name: /voice/i });
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["All voices", "My voice", "Bob"]);

    await user.selectOptions(select, BOB.id);
    expect(await screen.findByText("1 generation.")).toBeInTheDocument();
    expect(screen.getByText("Bob says hi")).toBeInTheDocument();
    expect(screen.queryByText("Ada says hi")).toBeNull();
    expect(asked).toContain(BOB.id);

    await user.selectOptions(select, "");
    expect(await screen.findByText("2 generations.")).toBeInTheDocument();
  });

  it("says so when the chosen voice has no generations, and keeps the filter usable", async () => {
    serve([ADA, BOB], ROWS.slice(0, 1));
    wrap();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByRole("combobox", { name: /voice/i }), BOB.id);
    expect(await screen.findByText(/no generations with this voice yet/i)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /voice/i })).toHaveValue(BOB.id);
  });
});
