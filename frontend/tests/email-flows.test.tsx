import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { ForgotPasswordForm } from "@/components/forgot-password-form";
import { GoogleCallback } from "@/components/google-callback";
import { LoginForm } from "@/components/login-form";
import { ResetPasswordForm } from "@/components/reset-password-form";
import { VerifyEmailAlert } from "@/components/verify-email-alert";
import { VerifyEmailView } from "@/components/verify-email-view";
import { __resetSessionForTests, getAccessToken, handleChannelMessage } from "@/lib/auth/session";
import { fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(search),
}));

const API = "http://api.test/api/v1";

function wrap(ui: ReactNode, strict = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (
    <QueryClientProvider client={client}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}
const signedOut = () =>
  server.use(
    mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json({ detail: "x" }, { status: 401 })),
  );
const unverifiedUser = () =>
  server.use(
    mswHttp.get(`${API}/auth/me`, () =>
      HttpResponse.json({ ...fixtures.user, email_verified_at: null }),
    ),
  );

beforeEach(() => {
  replace.mockReset();
  search = "";
  __resetSessionForTests();
  __resetBootstrapForTests();
  signedOut();
});
afterEach(() => window.history.replaceState(null, "", "/"));

describe("VerifyEmailView", () => {
  it("verifies from the fragment, strips it, and posts once under Strict Mode", async () => {
    window.history.replaceState(null, "", "/verify-email#token=tok123");
    const bodies: unknown[] = [];
    server.use(
      mswHttp.post(`${API}/auth/verify-email`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ detail: "Email verified" });
      }),
    );
    wrap(<VerifyEmailView />, true);
    expect(await screen.findByText(/is verified/i)).toBeInTheDocument();
    expect(bodies).toEqual([{ token: "tok123" }]);
    expect(window.location.hash).toBe("");
  });

  it("shows an 'incomplete link' state without calling the API", async () => {
    let calls = 0;
    server.use(
      mswHttp.post(`${API}/auth/verify-email`, () => ((calls += 1), HttpResponse.json({}))),
    );
    wrap(<VerifyEmailView />);
    expect(await screen.findByText(/looks incomplete/i)).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("handles 400 expired/used tokens, offering resend only when signed in", async () => {
    window.history.replaceState(null, "", "/verify-email#token=old");
    server.use(
      mswHttp.post(`${API}/auth/verify-email`, () =>
        HttpResponse.json({ detail: "Invalid or expired token" }, { status: 400 }),
      ),
    );
    wrap(<VerifyEmailView />);
    expect(await screen.findByText(/invalid or has expired/i)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /sign in to request/i })).toBeInTheDocument();
  });

  it("offers resend when expired and signed in", async () => {
    window.history.replaceState(null, "", "/verify-email#token=old");
    server.use(
      mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token)),
      mswHttp.post(`${API}/auth/verify-email`, () =>
        HttpResponse.json({ detail: "Invalid or expired token" }, { status: 400 }),
      ),
    );
    unverifiedUser();
    wrap(<VerifyEmailView />);
    expect(await screen.findByRole("button", { name: /resend verification/i })).toBeInTheDocument();
  });

  const verifyOk = () =>
    server.use(
      mswHttp.post(`${API}/auth/verify-email`, () =>
        HttpResponse.json({ detail: "Email verified" }),
      ),
    );
  const signedInSession = () =>
    server.use(mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token)));

  it("says 'Email verified' and offers Sign in as a button-sized primary action when signed out", async () => {
    window.history.replaceState(null, "", "/verify-email#token=ok");
    verifyOk();
    wrap(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: "Email verified" })).toBeInTheDocument();
    const next = screen.getByRole("link", { name: "Sign in" });
    expect(next).toHaveAttribute("href", "/login");
    expect(next.className).toMatch(/bg-primary/);
    expect(next.className).toMatch(/min-h-11/);
  });

  it("sends a signed-in user on to Generate, not a 'dashboard'", async () => {
    window.history.replaceState(null, "", "/verify-email#token=ok");
    verifyOk();
    signedInSession();
    wrap(<VerifyEmailView />);
    const next = await screen.findByRole("link", { name: "Start generating" });
    expect(next).toHaveAttribute("href", "/generate");
    expect(screen.queryByText(/dashboard/i)).toBeNull();
  });

  it("keeps the plain heading until the link has worked", async () => {
    wrap(<VerifyEmailView />);
    expect(await screen.findByRole("heading", { name: "Verify email" })).toBeInTheDocument();
  });

  it("an incomplete link points a signed-out visitor to sign in, and a signed-in one to Resend", async () => {
    const out = wrap(<VerifyEmailView />);
    expect(
      await screen.findByRole("link", { name: /sign in to request a new link/i }),
    ).toHaveAttribute("href", "/login");
    out.unmount();
    __resetSessionForTests();
    __resetBootstrapForTests();
    signedInSession();
    unverifiedUser();
    wrap(<VerifyEmailView />);
    expect(await screen.findByRole("button", { name: /resend verification/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /sign in to request/i })).toBeNull();
  });

  it("on a server error shows a danger alert and Try again, which re-sends the same token", async () => {
    window.history.replaceState(null, "", "/verify-email#token=again");
    const bodies: unknown[] = [];
    let fail = true;
    server.use(
      mswHttp.post(`${API}/auth/verify-email`, async ({ request }) => {
        bodies.push(await request.json());
        return fail
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json({ detail: "Email verified" });
      }),
    );
    wrap(<VerifyEmailView />);
    const alert = await screen.findByRole("alert");
    expect(alert.closest('[role="status"]')).toBeNull(); // announced once, not inside a live region
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Email verified" })).toBeInTheDocument();
    expect(bodies).toEqual([{ token: "again" }, { token: "again" }]);
  });
});

describe("VerifyEmailAlert / resend", () => {
  beforeEach(() =>
    server.use(mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token))),
  );

  it("is hidden for verified users", async () => {
    const { container } = wrap(<VerifyEmailAlert />);
    await new Promise((r) => setTimeout(r, 60));
    expect(container).toBeEmptyDOMElement();
  });

  it("shows for unverified users and resends (202 and 200 both succeed)", async () => {
    unverifiedUser();
    server.use(
      mswHttp.post(`${API}/auth/resend-verification`, () =>
        HttpResponse.json({ detail: "Email already verified" }, { status: 200 }),
      ),
    );
    wrap(<VerifyEmailAlert />);
    await userEvent.click(await screen.findByRole("button", { name: /resend verification/i }));
    expect(await screen.findByText(/email sent/i)).toBeInTheDocument();
  });

  it("explains a 429 cooldown", async () => {
    unverifiedUser();
    server.use(
      mswHttp.post(`${API}/auth/resend-verification`, () =>
        HttpResponse.json({ error: "Rate limit exceeded: 5 per 1 hour" }, { status: 429 }),
      ),
    );
    wrap(<VerifyEmailAlert />);
    await userEvent.click(await screen.findByRole("button", { name: /resend verification/i }));
    expect(await screen.findByText(/too many attempts/i)).toBeInTheDocument();
  });

  it("re-reads /me on window focus and hides once verified elsewhere", async () => {
    unverifiedUser();
    wrap(<VerifyEmailAlert />);
    await screen.findByRole("button", { name: /resend verification/i });
    server.use(mswHttp.get(`${API}/auth/me`, () => HttpResponse.json(fixtures.user)));
    window.dispatchEvent(new Event("focus"));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /resend verification/i })).toBeNull(),
    );
  });
});

describe("ForgotPasswordForm", () => {
  it("shows the same neutral confirmation on success", async () => {
    wrap(<ForgotPasswordForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "anyone@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));
    expect(await screen.findByText(/if an account exists/i)).toBeInTheDocument();
  });

  it("states the link lifetime the server publishes, not a fixed one", async () => {
    server.use(
      mswHttp.get(`${API}/terms`, () =>
        HttpResponse.json({ version: "1", url: null, password_reset_expire_minutes: 90 }),
      ),
    );
    wrap(<ForgotPasswordForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "anyone@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));
    expect(await screen.findByText(/it expires in 90 minutes/i)).toBeInTheDocument();
  });

  it("states no lifetime when the server gave none", async () => {
    server.use(mswHttp.get(`${API}/terms`, () => HttpResponse.json({ version: "1", url: null })));
    wrap(<ForgotPasswordForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "anyone@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));
    const confirmation = await screen.findByText(/if an account exists/i);
    expect(confirmation).not.toHaveTextContent(/expires/i);
  });

  it("validates the email client-side", async () => {
    wrap(<ForgotPasswordForm />);
    await userEvent.click(await screen.findByRole("button", { name: /send reset link/i }));
    expect(await screen.findByText("Enter your email")).toBeInTheDocument();
  });

  it("shows a cooldown on 429 and does not claim the email was sent", async () => {
    server.use(
      mswHttp.post(`${API}/auth/forgot-password`, () =>
        HttpResponse.json({ error: "Rate limit exceeded" }, { status: 429 }),
      ),
    );
    wrap(<ForgotPasswordForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "a@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
    expect(screen.queryByText(/if an account exists/i)).toBeNull();
  });
});

describe("ResetPasswordForm", () => {
  async function fill(pw: string, confirm = pw) {
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("New password"), pw);
    await user.type(screen.getByLabelText("Confirm new password"), confirm);
    await user.click(screen.getByRole("button", { name: /set new password/i }));
  }

  it("resets with the fragment token, strips it, and clears the local session", async () => {
    window.history.replaceState(null, "", "/reset-password#token=rt1");
    handleChannelMessage({ type: "token", token: "live" });
    const bodies: unknown[] = [];
    server.use(
      mswHttp.post(`${API}/auth/reset-password`, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({ detail: "Password updated" });
      }),
    );
    wrap(<ResetPasswordForm />);
    await fill("brand-new-password");
    expect(await screen.findByText(/password has been changed/i)).toBeInTheDocument();
    expect(bodies).toEqual([{ token: "rt1", new_password: "brand-new-password" }]);
    expect(getAccessToken()).toBeNull();
    expect(window.location.hash).toBe("");
  });

  it("rejects mismatched and short passwords without a request", async () => {
    window.history.replaceState(null, "", "/reset-password#token=rt1");
    let calls = 0;
    server.use(
      mswHttp.post(`${API}/auth/reset-password`, () => ((calls += 1), HttpResponse.json({}))),
    );
    wrap(<ResetPasswordForm />);
    await fill("long-enough-pw", "different-pw-xx");
    expect(await screen.findByText("Passwords don't match")).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("offers a new link on 400 (reused or expired token)", async () => {
    window.history.replaceState(null, "", "/reset-password#token=used");
    server.use(
      mswHttp.post(`${API}/auth/reset-password`, () =>
        HttpResponse.json({ detail: "Invalid or expired token" }, { status: 400 }),
      ),
    );
    wrap(<ResetPasswordForm />);
    await fill("long-enough-pw");
    expect(await screen.findByText(/invalid or has expired/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /request a new link/i })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("shows 'incomplete' when the fragment is missing", async () => {
    wrap(<ResetPasswordForm />);
    expect(await screen.findByText(/looks incomplete/i)).toBeInTheDocument();
  });
});

describe("Google flow", () => {
  it("callback routes to the dashboard when the session was established", async () => {
    server.use(mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.json(fixtures.token)));
    wrap(<GoogleCallback />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/generate"));
  });

  it("callback sends cookie-less browsers to login with cookie help", async () => {
    wrap(<GoogleCallback />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?error=session_unavailable"));
  });

  it("login renders each backend error code, and starts Google by plain link", async () => {
    search = "error=google_account_conflict";
    wrap(<LoginForm />);
    expect(await screen.findByText(/can't be linked automatically/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /continue with google/i })).toHaveAttribute(
      "href",
      "http://api.test/api/v1/auth/google",
    );
    expect(screen.getByRole("link", { name: /forgot your password/i })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });

  it("login shows generic copy for an unknown error code", async () => {
    search = "error=weird";
    wrap(<LoginForm />);
    expect(await screen.findByText("Sign-in failed. Please try again.")).toBeInTheDocument();
  });
});
