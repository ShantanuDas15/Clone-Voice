import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NotFound from "@/app/not-found";
import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { TextToSpeechForm } from "@/components/text-to-speech-form";
import { Button } from "@/components/ui/button";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { __resetSessionForTests } from "@/lib/auth/session";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/generate",
}));

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

afterEach(() => vi.unstubAllGlobals());

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
});

describe("a busy Button (live audit: focus was dropped to the page)", () => {
  it("stays focusable, says it is busy, and ignores clicks", async () => {
    const onClick = vi.fn();
    render(
      <Button loading onClick={onClick}>
        Saving…
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Saving…" });
    button.focus();
    await userEvent.setup().click(button);
    expect(button).toHaveFocus();
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("does not submit its form again while busy, and does when idle", async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    const { rerender } = render(
      <form onSubmit={onSubmit}>
        <Button type="submit" loading>
          Go
        </Button>
      </form>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Go" }));
    expect(onSubmit).not.toHaveBeenCalled();
    rerender(
      <form onSubmit={onSubmit}>
        <Button type="submit">Go</Button>
      </form>,
    );
    await user.click(screen.getByRole("button", { name: "Go" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("is not busy by default: aria-busy and aria-disabled are absent", () => {
    render(<Button>Go</Button>);
    const button = screen.getByRole("button", { name: "Go" });
    expect(button).not.toHaveAttribute("aria-busy");
    expect(button).not.toHaveAttribute("aria-disabled");
  });
});

describe("invalid submit moves focus to the first invalid field", () => {
  it("generate: the empty text box", async () => {
    wrap(<TextToSpeechForm />);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Generate speech" }));
    const text = await screen.findByLabelText("Text");
    expect(text).toHaveAttribute("aria-invalid", "true");
    expect(text).toHaveFocus();
  });

  it("voices: the voice name, not the submit button", async () => {
    wrap(<UploadVoiceForm />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Create voice" }));
    const name = await screen.findByLabelText("Voice name");
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveFocus();
  });

  it("voices: the consent checkbox is marked invalid when it is the only problem", async () => {
    wrap(<UploadVoiceForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Voice name"), "Ada");
    await user.upload(
      document.querySelector('input[type="file"]') as HTMLInputElement,
      new File([new Uint8Array(2000)], "a.wav", { type: "audio/wav" }),
    );
    await user.click(screen.getByRole("button", { name: "Create voice" }));
    const consent = screen.getByRole("checkbox", { name: /I confirm I have the right/ });
    expect(consent).toHaveAttribute("aria-invalid", "true");
    expect(consent).toHaveFocus();
  });
});

describe("create-voice form polish", () => {
  it("shows the Upload/Record choice as a segmented control with one selected option", async () => {
    // The choice only exists where the browser can record (jsdom cannot).
    vi.stubGlobal(
      "MediaRecorder",
      class {
        static isTypeSupported = () => true;
      },
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn() },
    });
    wrap(<UploadVoiceForm />);
    const group = await screen.findByRole("radiogroup", { name: "How to add a sample" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => r.getAttribute("aria-checked"))).toEqual(["true", "false"]);
    expect(radios[0]).toHaveClass("bg-primary");
    expect(radios[1]).not.toHaveClass("bg-primary");
  });

  it("keeps the retention note and the terms status in one line under the consent box", () => {
    wrap(<UploadVoiceForm />);
    const note = screen.getByText(/Your sample is kept until you delete this voice/);
    expect(note.tagName).toBe("P");
    expect(note.querySelectorAll("p")).toHaveLength(0);
  });
});

describe("not found page", () => {
  it("has one h1 and a way home (the stock Next.js page has neither)", () => {
    render(<NotFound />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
  });
});
