import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { GenerateStage } from "@/components/generate-stage";
import { TextToSpeechForm } from "@/components/text-to-speech-form";
import { __resetSessionForTests } from "@/lib/auth/session";
import { clearDraft } from "@/lib/draft";
import { fixtures } from "@/mocks/handlers";
import { chooseDelivery, pickVoice, voiceRadio, voicesLoaded } from "./voice-pick";
import { server } from "@/mocks/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/generate",
}));

const API = "http://api.test/api/v1";
const wav = () =>
  new HttpResponse(new Uint8Array([82, 73, 70, 70]), { headers: { "Content-Type": "audio/wav" } });

describe("GenerateStage (UX plan §12.21)", () => {
  it("ready: the live voiceprint, the three steps, and the region named for what it will hold", () => {
    render(<GenerateStage state="ready" elapsed={0} />);
    const region = screen.getByRole("region", { name: "Your audio appears here" });
    expect(region).toHaveAttribute("data-state", "ready");
    expect(region).toHaveTextContent("Choose a voice.");
    expect(region).toHaveTextContent("Press Generate speech, then play or download.");
    expect(screen.getByTestId("stage-voiceprint").querySelector("canvas")).not.toBeNull();
    expect(screen.getByTestId("stage-tag")).toHaveTextContent("Ready");
    expect(screen.queryByText(/^Voice:/)).not.toBeInTheDocument();
  });

  it("ready is hidden below the large breakpoint, where the form is the whole page", () => {
    render(<GenerateStage state="ready" elapsed={0} />);
    const cls = screen.getByRole("region").className.split(/\s+/);
    expect(cls).toContain("hidden");
    expect(cls).toContain("lg:flex");
  });

  it("working and done are shown at every width", () => {
    const { rerender } = render(<GenerateStage state="working" elapsed={3} />);
    expect(screen.getByRole("region").className.split(/\s+/)).not.toContain("hidden");
    rerender(<GenerateStage state="done" elapsed={0} />);
    expect(screen.getByRole("region").className.split(/\s+/)).not.toContain("hidden");
  });

  it("working: the real status and a big clock, over the same voiceprint, with the voice named", () => {
    render(<GenerateStage state="working" voiceName="My voice" elapsed={12} />);
    expect(screen.getByRole("region", { name: "Your audio" })).toHaveAttribute(
      "data-state",
      "working",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Generating… 12 s");
    expect(screen.getByTestId("stage-voiceprint")).toBeInTheDocument();
    expect(screen.getByTestId("stage-clock")).toHaveTextContent("0:12");
    expect(screen.getByText("My voice")).toBeInTheDocument();
    expect(screen.getByTestId("stage-tag")).toHaveTextContent("Generating");
  });

  it("done: the take replaces the voiceprint and the heading says the voice is AI-generated", () => {
    render(
      <GenerateStage state="done" voiceName="My voice" elapsed={0}>
        <p>the take</p>
      </GenerateStage>,
    );
    expect(screen.getByRole("region", { name: /Your audio.*AI-generated voice/ })).toBeVisible();
    expect(screen.getByText("the take")).toBeInTheDocument();
    expect(screen.queryByTestId("stage-voiceprint")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByTestId("stage-tag")).toHaveTextContent("Done");
  });

  it("leaves nothing for assistive technology to read twice: the tag, voiceprint and clock are hidden", () => {
    render(<GenerateStage state="working" elapsed={1} />);
    expect(screen.getByTestId("stage-tag")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByTestId("stage-voiceprint")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByTestId("stage-clock")).toHaveAttribute("aria-hidden", "true");
  });

  it.each(["ready", "working", "done"] as const)(
    "%s: no inline style anywhere (the site's CSP forbids it)",
    (state) => {
      const { container } = render(
        <GenerateStage state={state} voiceName="V" elapsed={25}>
          <p>x</p>
        </GenerateStage>,
      );
      expect(container.querySelectorAll("[style]")).toHaveLength(0);
    },
  );
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
});

async function pickVoiceAndType(text = "Hello there.") {
  const user = userEvent.setup();
  await pickVoice(user, fixtures.profile.id);
  await user.type(screen.getByLabelText("Text"), text);
  return user;
}

describe("the stage inside the Generate form", () => {
  it("moves ready, working, done, naming the voice that was used", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, async () => {
        await new Promise((r) => setTimeout(r, 200));
        return wav();
      }),
    );
    wrap(<TextToSpeechForm />);
    const stage = () => document.querySelector("section[data-state]") as HTMLElement;
    await voicesLoaded();
    expect(stage()).toHaveAttribute("data-state", "ready");

    const user = await pickVoiceAndType();
    expect(await within(stage()).findByText("My voice")).toBeInTheDocument(); // chosen, not yet used
    await user.click(screen.getByRole("button", { name: "Generate speech" }));
    await waitFor(() => expect(stage()).toHaveAttribute("data-state", "working"));
    expect(within(stage()).getByRole("status")).toHaveTextContent("Generating");
    expect(within(stage()).getByText("My voice")).toBeInTheDocument();

    await waitFor(() => expect(stage()).toHaveAttribute("data-state", "done"));
    expect(within(stage()).getByRole("button", { name: "Play Generated speech" })).toBeVisible();
    expect(within(stage()).getByText("My voice")).toBeInTheDocument();
  });

  it("keeps naming the voice the take was made with after the choice is changed", async () => {
    server.use(
      mswHttp.get(`${API}/voice/profiles`, () =>
        HttpResponse.json([
          fixtures.profile,
          { ...fixtures.profile, id: "44444444-4444-4444-8444-444444444444", name: "Other" },
        ]),
      ),
      mswHttp.post(`${API}/synthesize`, () => wav()),
    );
    wrap(<TextToSpeechForm />);
    const user = await pickVoiceAndType();
    await user.click(screen.getByRole("button", { name: "Generate speech" }));
    const stage = () => document.querySelector("section[data-state]") as HTMLElement;
    await waitFor(() => expect(stage()).toHaveAttribute("data-state", "done"));
    await user.click(await voiceRadio("44444444-4444-4444-8444-444444444444"));
    expect(within(stage()).getByText("My voice")).toBeInTheDocument();
    expect(within(stage()).queryByText("Other")).not.toBeInTheDocument();
  });

  it("keeps the keyboard on the Generate button when Generate again swaps the take for the status", async () => {
    server.use(
      mswHttp.post(`${API}/synthesize`, async () => {
        await new Promise((r) => setTimeout(r, 150));
        return wav();
      }),
    );
    wrap(<TextToSpeechForm />);
    const user = await pickVoiceAndType();
    await user.click(screen.getByRole("button", { name: "Generate speech" }));
    const again = await screen.findByRole("button", { name: "Generate again" });
    again.focus();
    expect(again).toHaveFocus();
    await user.click(again);
    // The button that had focus is gone with the take; focus must not fall back to the page.
    await waitFor(() =>
      expect(document.querySelector("section[data-state]")).toHaveAttribute(
        "data-state",
        "working",
      ),
    );
    expect(screen.getByRole("button", { name: /Generating/ })).toHaveFocus();
  });

  it("shows how much of the limit the text uses, and turns red past it", async () => {
    wrap(<TextToSpeechForm />);
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Text");
    const meter = screen.getByTestId("length-meter") as HTMLProgressElement;
    expect(meter).toHaveAttribute("aria-hidden", "true");
    expect(meter.value).toBe(0);
    expect(meter.max).toBe(500);
    await user.type(box, "hello");
    expect(meter.value).toBe(5);
    expect(meter).toHaveAttribute("data-over", "false");
    await user.clear(box);
    await user.click(box);
    await user.paste("x".repeat(520));
    expect(meter.value).toBe(500);
    expect(meter).toHaveAttribute("data-over", "true");
    expect(screen.getByText("520 / 500 (20 too many)")).toBeInTheDocument();
  });

  it("has no inline style on the stage or the meter in any state", async () => {
    server.use(mswHttp.post(`${API}/synthesize`, () => wav()));
    const { container } = wrap(<TextToSpeechForm />);
    const user = await pickVoiceAndType();
    expect(container.querySelectorAll("section[data-state] [style], progress[style]")).toHaveLength(
      0,
    );
    await user.click(screen.getByRole("button", { name: "Generate speech" }));
    await waitFor(() =>
      expect(document.querySelector("section[data-state]")).toHaveAttribute("data-state", "done"),
    );
    expect(container.querySelectorAll("section[data-state] [style]")).toHaveLength(0);
  });
});

describe("the voice cards and delivery chips (UX plan §12.26)", () => {
  it("draws voices as a native radio group, one card per ready voice, named by the voice", async () => {
    wrap(<TextToSpeechForm />);
    const group = await screen.findByRole("radiogroup", { name: "Voice" });
    const radio = within(group).getByRole("radio", { name: fixtures.profile.name });
    expect(radio).toHaveAttribute("type", "radio");
    expect(radio).toBeChecked(); // the only ready voice is chosen for the user
    expect(document.querySelectorAll(".gx-glyph")).toHaveLength(1);
  });

  it("draws delivery as chips, and keeps Strength off until a named emotion is chosen", async () => {
    wrap(<TextToSpeechForm />);
    const user = userEvent.setup();
    const group = await screen.findByRole("radiogroup", { name: "Delivery" });
    expect(within(group).getAllByRole("radio")).toHaveLength(7);
    expect(within(group).getByRole("radio", { name: "Auto (from the text)" })).toBeChecked();
    expect(screen.getByLabelText(/Strength/)).toBeDisabled();
    await chooseDelivery(user, "sad");
    expect(within(group).getByRole("radio", { name: "Sad" })).toBeChecked();
    expect(screen.getByLabelText(/Strength/)).toBeEnabled();
  });

  it("counts the sentences as you type, for the eye only", async () => {
    wrap(<TextToSpeechForm />);
    const user = userEvent.setup();
    const count = await screen.findByTestId("sentence-count");
    expect(count).toHaveTextContent("0 sentences");
    expect(count).toHaveAttribute("aria-hidden", "true");
    await user.type(screen.getByLabelText("Text"), "Hello there. How are you");
    expect(count).toHaveTextContent("2 sentences");
  });

  it("offers Pause motion, which holds the page's endless movement still", async () => {
    wrap(<TextToSpeechForm />);
    const user = userEvent.setup();
    const root = document.querySelector(".gx-root") as HTMLElement;
    expect(root).toHaveAttribute("data-motion", "on");
    await user.click(await screen.findByRole("button", { name: "Pause motion" }));
    expect(root).toHaveAttribute("data-motion", "paused");
    await user.click(screen.getByRole("button", { name: "Resume motion" }));
    expect(root).toHaveAttribute("data-motion", "on");
  });
});
