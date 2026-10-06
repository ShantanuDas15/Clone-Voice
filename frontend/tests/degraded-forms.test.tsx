import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { HttpResponse, http as mswHttp } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { TextToSpeechForm } from "@/components/text-to-speech-form";
import { UploadVoiceForm } from "@/components/upload-voice-form";
import { __resetSessionForTests } from "@/lib/auth/session";
import { server } from "@/mocks/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/dashboard",
}));

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  );
}

const health = (status: number) =>
  server.use(mswHttp.get("http://api.test/health/ready", () => HttpResponse.json({}, { status })));

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
});

describe("degraded service (R17)", () => {
  it("disables Generate and explains why while /health/ready is 503", async () => {
    health(503);
    wrap(<TextToSpeechForm />);
    expect(await screen.findByText(/generating is paused/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate speech" })).toBeDisabled();
  });

  it("disables Create voice and explains why while /health/ready is 503", async () => {
    health(503);
    wrap(<UploadVoiceForm />);
    expect(await screen.findByText(/uploading is paused/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create voice" })).toBeDisabled();
  });

  it("stays enabled when healthy, and when the probe itself fails", async () => {
    server.use(mswHttp.get("http://api.test/health/ready", () => HttpResponse.error()));
    wrap(<UploadVoiceForm />);
    await screen.findByLabelText("Voice name");
    expect(screen.getByRole("button", { name: "Create voice" })).toBeEnabled();
    expect(screen.queryByText(/paused/i)).not.toBeInTheDocument();
  });
});
