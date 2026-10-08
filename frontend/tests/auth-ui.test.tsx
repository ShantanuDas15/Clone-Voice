import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http as mswHttp } from "msw";
import { StrictMode, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGate } from "@/components/auth-gate";
import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { LoginForm } from "@/components/login-form";
import { SignupForm } from "@/components/signup-form";
import { UserMenu } from "@/components/user-menu";
import { __resetSessionForTests, getAccessToken } from "@/lib/auth/session";
import { server } from "@/mocks/server";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/generate",
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

function signedOut() {
  server.use(
    mswHttp.post(`${API}/auth/refresh`, () =>
      HttpResponse.json({ detail: "Invalid" }, { status: 401 }),
    ),
  );
}

beforeEach(() => {
  replace.mockReset();
  search = "";
  __resetSessionForTests();
  __resetBootstrapForTests();
});

describe("session bootstrap", () => {
  it("restores the session via /auth/refresh then /auth/me", async () => {
    wrap(<UserMenu />);
    expect(await screen.findByText("Ada")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("issues a single refresh under React Strict Mode's double effect", async () => {
    let refreshes = 0;
    server.use(
      mswHttp.post(`${API}/auth/refresh`, () => {
        refreshes += 1;
        return HttpResponse.json({ access_token: "t", token_type: "bearer" });
      }),
    );
    wrap(<UserMenu />, true);
    await screen.findByText("Ada");
    expect(refreshes).toBe(1);
  });

  it("shows signed-out UI silently (no alert) when refresh is 401", async () => {
    signedOut();
    wrap(<UserMenu />);
    expect(await screen.findByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("falls back to signed-out UI when the API is unreachable", async () => {
    server.use(mswHttp.post(`${API}/auth/refresh`, () => HttpResponse.error()));
    wrap(<UserMenu />);
    expect(await screen.findByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });

  it("never persists the token to browser storage", async () => {
    wrap(<UserMenu />);
    await screen.findByText("Ada");
    expect(getAccessToken()).toBe("test-access-token");
    const dump =
      JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }) + document.cookie;
    expect(dump).not.toContain("test-access-token");
  });
});

describe("AuthGate", () => {
  it("redirects signed-out users to /login with next", async () => {
    signedOut();
    wrap(
      <AuthGate>
        <p>secret</p>
      </AuthGate>,
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2Fgenerate"));
    expect(screen.queryByText("secret")).toBeNull();
  });

  it("shows a skeleton, then content, when signed in", async () => {
    wrap(
      <AuthGate>
        <p>secret</p>
      </AuthGate>,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(await screen.findByText("secret")).toBeInTheDocument();
  });
});

describe("logout", () => {
  it("signs out even when the API call fails, and clears the session", async () => {
    server.use(mswHttp.post(`${API}/auth/logout`, () => HttpResponse.error()));
    wrap(<UserMenu />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
    expect(replace).toHaveBeenCalledWith("/");
  });
});

describe("LoginForm", () => {
  async function submit(email = "ada@example.com", password = "secret-pass") {
    signedOut();
    return { user: userEvent.setup(), email, password };
  }

  it("signs in and follows a sanitized next", async () => {
    search = "next=%2Fprofile";
    signedOut();
    server.use(
      mswHttp.post(`${API}/auth/refresh`, () =>
        HttpResponse.json({ detail: "x" }, { status: 401 }),
      ),
    );
    wrap(<LoginForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "secret-pass");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/voices"));
  });

  it("ignores an external next target", async () => {
    search = "next=https%3A%2F%2Fevil.test";
    signedOut();
    wrap(<LoginForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "secret-pass");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/generate"));
  });

  it("shows one generic message on 401 (G-19)", async () => {
    const { user } = await submit();
    server.use(
      mswHttp.post(`${API}/auth/login`, () =>
        HttpResponse.json({ detail: "Incorrect email or password" }, { status: 401 }),
      ),
    );
    wrap(<LoginForm />);
    await user.type(await screen.findByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/incorrect email or password/i);
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows a Retry-After countdown on 429", async () => {
    const { user } = await submit();
    server.use(
      mswHttp.post(`${API}/auth/login`, () =>
        HttpResponse.json(
          { detail: "Too many failed attempts" },
          { status: 429, headers: { "Retry-After": "120" } },
        ),
      ),
    );
    wrap(<LoginForm />);
    await user.type(await screen.findByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("2 minutes");
  });

  it("validates before calling the API and sends exactly one request per submit", async () => {
    signedOut();
    let logins = 0;
    server.use(
      mswHttp.post(`${API}/auth/login`, async () => {
        logins += 1;
        await new Promise((r) => setTimeout(r, 30));
        return HttpResponse.json({ access_token: "t", token_type: "bearer" });
      }),
    );
    wrap(<LoginForm />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email")).toBeInTheDocument();
    expect(logins).toBe(0);
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "pw{Enter}{Enter}");
    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(logins).toBe(1);
  });
});

describe("SignupForm", () => {
  async function fill(user: ReturnType<typeof userEvent.setup>, password = "long-enough-pw") {
    await user.type(await screen.findByLabelText("Name"), "Ada");
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), password);
    await user.click(screen.getByRole("button", { name: "Create account" }));
  }

  it("creates the account and goes to the generator", async () => {
    signedOut();
    wrap(<SignupForm />);
    await fill(userEvent.setup());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/generate"));
  });

  it("maps 409 to an email field error with a sign-in link", async () => {
    signedOut();
    server.use(
      mswHttp.post(`${API}/auth/signup`, () =>
        HttpResponse.json({ detail: "Email already registered" }, { status: 409 }),
      ),
    );
    wrap(<SignupForm />);
    await fill(userEvent.setup());
    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in instead" })).toHaveAttribute("href", "/login");
  });

  it("maps server 422 detail to fields", async () => {
    signedOut();
    server.use(
      mswHttp.post(`${API}/auth/signup`, () =>
        HttpResponse.json(
          {
            detail: [{ loc: ["body", "name"], msg: "Name must not be blank", type: "value_error" }],
          },
          { status: 422 },
        ),
      ),
    );
    wrap(<SignupForm />);
    await fill(userEvent.setup());
    expect(await screen.findByText("Name must not be blank")).toBeInTheDocument();
  });

  it("rejects a short password client-side without a request", async () => {
    signedOut();
    let calls = 0;
    server.use(
      mswHttp.post(
        `${API}/auth/signup`,
        () => ((calls += 1), HttpResponse.json({}, { status: 201 })),
      ),
    );
    wrap(<SignupForm />);
    await fill(userEvent.setup(), "short");
    expect(await screen.findByText(/at least 8 characters/)).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("shows a cooldown on 429", async () => {
    signedOut();
    server.use(
      mswHttp.post(`${API}/auth/signup`, () =>
        HttpResponse.json({ error: "Rate limit exceeded: 5 per 1 minute" }, { status: 429 }),
      ),
    );
    wrap(<SignupForm />);
    await fill(userEvent.setup());
    expect(await screen.findByRole("alert")).toHaveTextContent(/too many attempts/i);
  });
});
