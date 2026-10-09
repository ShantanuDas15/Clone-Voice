import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { FirstRunChecklist } from "@/components/first-run-checklist";
import { StepList } from "@/components/step-list";
import GeneratePage from "@/app/(app)/generate/page";
import { TextToSpeechForm } from "@/components/text-to-speech-form";
import { clearDraft } from "@/lib/draft";
import { firstRun } from "@/lib/first-run";
import { __resetSessionForTests } from "@/lib/auth/session";
import { fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/generate",
}));

const API = "http://api.test/api/v1";

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

function setup({ verified, profiles }: { verified: boolean; profiles: unknown[] }) {
  server.use(
    mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token)),
    mswHttp.get(`${API}/auth/me`, () =>
      HttpResponse.json({
        ...fixtures.user,
        email_verified_at: verified ? "2026-10-01T00:00:00Z" : null,
      }),
    ),
    mswHttp.get(`${API}/voice/profiles`, () => HttpResponse.json(profiles)),
  );
}

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
  clearDraft();
});

describe("firstRun", () => {
  it.each([
    [false, false, ["current", "todo", "todo"], "Verify your email first."],
    [false, true, ["current", "done", "todo"], "Verify your email first."],
    [true, false, ["done", "current", "todo"], "Create a voice first."],
    [true, true, ["done", "done", "current"], null],
  ] as const)("verified=%s ready voice=%s", (emailVerified, hasReadyVoice, steps, blocker) => {
    const s = firstRun({ emailVerified, hasReadyVoice });
    expect([s.verify, s.voice, s.generate]).toEqual(steps);
    expect(s.blocker).toBe(blocker);
  });
});

describe("StepList", () => {
  it("numbers the steps, states each status in words and marks only the next step", () => {
    render(
      <StepList
        label="Steps"
        steps={[
          { id: "a", title: "First", status: "done", detail: "hidden when done" },
          { id: "b", title: "Second", status: "current", detail: "do this" },
          { id: "c", title: "Third", status: "todo" },
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items.map((i) => i.getAttribute("aria-current"))).toEqual([null, "step", null]);
    expect(screen.getByText(/\(Done\)/)).toBeInTheDocument();
    expect(screen.getByText(/\(Next\)/)).toBeInTheDocument();
    expect(screen.getByText(/\(To do\)/)).toBeInTheDocument();
    expect(screen.queryByText("hidden when done")).toBeNull();
    expect(screen.getByText("do this")).toBeInTheDocument();
  });
});

describe("FirstRunChecklist", () => {
  it("unverified with no voice: points at email first and lets the user resend", async () => {
    setup({ verified: false, profiles: [] });
    wrap(<FirstRunChecklist />);
    expect(await screen.findByText(/verify your email address \(/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /resend verification/i })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")[0]).toHaveAttribute("aria-current", "step");
  });

  it("verified with no voice: the next step is a button to create one", async () => {
    setup({ verified: true, profiles: [] });
    wrap(<FirstRunChecklist />);
    const cta = await screen.findByRole("link", { name: "Create a voice" });
    expect(cta).toHaveAttribute("href", "/voices");
    expect(screen.getAllByRole("listitem")[1]).toHaveAttribute("aria-current", "step");
  });

  it("sits below the form on the Generate page, so its late arrival moves nothing above it", async () => {
    setup({ verified: true, profiles: [] });
    wrap(<GeneratePage searchParams={{}} />);
    const heading = await screen.findByRole("heading", { name: "Get your first result" });
    const text = screen.getByLabelText("Text");
    expect(text.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("verified with only a failed voice: says the upload failed", async () => {
    setup({ verified: true, profiles: [{ ...fixtures.profile, status: "failed" }] });
    wrap(<FirstRunChecklist />);
    expect(await screen.findByText(/couldn't be processed/i)).toBeInTheDocument();
  });

  it("is gone once verified with a ready voice", async () => {
    setup({ verified: true, profiles: [fixtures.profile] });
    const { container } = wrap(<FirstRunChecklist />);
    await new Promise((r) => setTimeout(r, 80));
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Generate readiness", () => {
  it("verified with no ready voice: disabled, with the reason linked to the button", async () => {
    setup({ verified: true, profiles: [] });
    wrap(<TextToSpeechForm />);
    const button = await screen.findByRole("button", { name: "Generate speech" });
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAccessibleDescription("Create a voice first.");
  });

  it("verified with a ready voice: enabled and no reason shown", async () => {
    setup({ verified: true, profiles: [fixtures.profile] });
    wrap(<TextToSpeechForm />);
    const select = await screen.findByLabelText("Voice");
    await waitFor(() => expect(select).not.toBeDisabled());
    expect(screen.getByRole("button", { name: "Generate speech" })).toBeEnabled();
    expect(screen.queryByText(/first\.$/)).toBeNull();
  });

  it("preselects the voice named in the link", async () => {
    setup({ verified: true, profiles: [fixtures.profile] });
    wrap(<TextToSpeechForm initialVoiceId={fixtures.profile.id} />);
    const select = (await screen.findByLabelText("Voice")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe(fixtures.profile.id));
  });

  it("ignores a preselected voice that no longer exists", async () => {
    setup({ verified: true, profiles: [fixtures.profile] });
    wrap(<TextToSpeechForm initialVoiceId="99999999-9999-4999-8999-999999999999" />);
    const select = (await screen.findByLabelText("Voice")) as HTMLSelectElement;
    await waitFor(() => expect(select).not.toBeDisabled());
    await waitFor(() => expect(select.value).toBe(""));
    await userEvent.setup().selectOptions(select, fixtures.profile.id);
    expect(select.value).toBe(fixtures.profile.id);
  });
});
