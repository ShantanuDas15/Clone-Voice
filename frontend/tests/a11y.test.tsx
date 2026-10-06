import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AccountSection } from "@/components/account-section";
import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { ForgotPasswordForm } from "@/components/forgot-password-form";
import { HistoryList } from "@/components/history-list";
import { LoginForm } from "@/components/login-form";
import { Recorder } from "@/components/recorder";
import { SignupForm } from "@/components/signup-form";
import { TextToSpeechForm } from "@/components/text-to-speech-form";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { VoiceProfileList } from "@/components/voice-profile-list";
import { __resetSessionForTests } from "@/lib/auth/session";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  );
}

/** Serious/critical axe violations in the rendered DOM. jsdom has no layout, so colour-contrast
 *  (which needs real rendering) is checked separately in the browser audit, not here. */
async function violations(container: HTMLElement) {
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
  });
  return result.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
});

describe("accessibility (axe, serious/critical)", () => {
  it("detector is live: flags an unlabeled input", async () => {
    const { container } = render(<input type="text" />);
    expect((await violations(container)).join()).toContain("label");
  });

  it("login form", async () => {
    const { container } = wrap(<LoginForm />);
    expect(await violations(container)).toEqual([]);
  });

  it("signup form", async () => {
    const { container } = wrap(<SignupForm />);
    expect(await violations(container)).toEqual([]);
  });

  it("forgot-password form", async () => {
    const { container } = wrap(<ForgotPasswordForm />);
    expect(await violations(container)).toEqual([]);
  });

  it("upload form, file mode", async () => {
    const { container } = wrap(<UploadVoiceForm />);
    await screen.findByLabelText("Voice name");
    expect(await violations(container)).toEqual([]);
  });

  it("upload form with validation errors", async () => {
    const { container } = wrap(<UploadVoiceForm />);
    await userEvent.click(await screen.findByRole("button", { name: "Create voice" }));
    await screen.findByText("Enter a name for this voice");
    expect(await violations(container)).toEqual([]);
  });

  it("recorder, idle", async () => {
    const { container } = render(<Recorder onChange={() => {}} />);
    expect(await violations(container)).toEqual([]);
  });

  it("voice profile list", async () => {
    const { container } = wrap(<VoiceProfileList />);
    await screen.findByText("My voice");
    expect(await violations(container)).toEqual([]);
  });

  it("voice profile list with the delete confirmation open", async () => {
    const { container } = wrap(<VoiceProfileList />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete My voice" }));
    await screen.findByRole("alertdialog");
    expect(await violations(container)).toEqual([]);
  });

  it("text-to-speech form", async () => {
    const { container } = wrap(<TextToSpeechForm />);
    await screen.findByLabelText("Text");
    expect(await violations(container)).toEqual([]);
  });

  it("history list", async () => {
    const { container } = wrap(<HistoryList />);
    await screen.findByText("Hello there.");
    expect(await violations(container)).toEqual([]);
  });

  it("account section with the delete dialog open", async () => {
    const { container } = wrap(<AccountSection />);
    await userEvent.click(await screen.findByRole("button", { name: /delete my account/i }));
    expect(await violations(container)).toEqual([]);
  });
});
