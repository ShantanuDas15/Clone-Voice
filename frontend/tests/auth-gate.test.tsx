import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "@/components/auth-gate";
import { AuthProvider, __resetBootstrapForTests, useAuth } from "@/components/auth-provider";
import { __resetSessionForTests } from "@/lib/auth/session";
import { server } from "@/mocks/server";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/voices",
}));

function SignOut() {
  const { logout } = useAuth();
  return (
    <button type="button" onClick={() => void logout()}>
      sign out
    </button>
  );
}

function wrap() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <AuthGate>
          <SignOut />
        </AuthGate>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  __resetSessionForTests();
  __resetBootstrapForTests();
  replace.mockClear();
});

describe("AuthGate", () => {
  it("sends an expired or missing session to sign-in with a return path", async () => {
    server.use(
      mswHttp.post("http://api.test/api/v1/auth/refresh", () =>
        HttpResponse.json({ detail: "no session" }, { status: 401 }),
      ),
    );
    wrap();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2Fvoices"));
  });

  it("sends a deliberate sign-out home, not to sign-in (found by the e2e run)", async () => {
    wrap();
    await userEvent.click(await screen.findByRole("button", { name: "sign out" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(replace).not.toHaveBeenCalledWith(expect.stringContaining("/login"));
  });

  it("says the session ended when it ends while the page is open (e.g. signed out in another tab)", async () => {
    wrap();
    await screen.findByRole("button", { name: "sign out" });
    // Another tab signing out reaches this tab as a cleared session, not a deliberate sign-out.
    const { clearSession } = await import("@/lib/auth/session");
    clearSession();
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/login?reason=expired&next=%2Fvoices"),
    );
  });
});
