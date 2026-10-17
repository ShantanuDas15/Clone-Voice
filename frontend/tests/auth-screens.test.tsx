import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { HttpResponse, http as mswHttp } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, __resetBootstrapForTests } from "@/components/auth-provider";
import { LoginForm } from "@/components/login-form";
import { SignupForm } from "@/components/signup-form";
import { SiteFooter } from "@/components/site-footer";
import ForgotPasswordPage from "@/app/(public)/forgot-password/page";
import { UserMenu } from "@/components/user-menu";
import { __resetSessionForTests } from "@/lib/auth/session";
import { server } from "@/mocks/server";

let pathname = "/login";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => pathname,
  useSearchParams: () => new URLSearchParams(""),
}));

const API = "http://api.test/api/v1";

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  pathname = "/login";
  __resetSessionForTests();
  __resetBootstrapForTests();
  server.use(
    mswHttp.post(`${API}/auth/refresh`, () =>
      HttpResponse.json({ detail: "Invalid" }, { status: 401 }),
    ),
  );
});

describe("sign-in and sign-up screens", () => {
  it("puts Forgot password on the Password label row, as a 44 px target before the field", () => {
    wrap(<LoginForm />);
    const field = screen.getByLabelText("Password");
    const forgot = screen.getByRole("link", { name: "Forgot your password?" });
    expect(forgot).toHaveAttribute("href", "/forgot-password");
    expect(forgot).toHaveClass("min-h-11");
    // same row as the label, ahead of the input
    expect(forgot.parentElement).toBe(screen.getByText("Password").parentElement);
    expect(forgot.compareDocumentPosition(field) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByRole("link", { name: "Forgot your password?" })).toHaveLength(1);
  });

  it("asks phone keyboards not to capitalise or correct an email address", () => {
    wrap(<LoginForm />);
    const email = screen.getByLabelText("Email");
    expect(email).toHaveAttribute("autocapitalize", "none");
    expect(email).toHaveAttribute("spellcheck", "false");
  });

  it("sign-up sets the same email hints, capitalises the name, and still allows paste", () => {
    wrap(<SignupForm />);
    expect(screen.getByLabelText("Email")).toHaveAttribute("autocapitalize", "none");
    expect(screen.getByLabelText("Name")).toHaveAttribute("autocapitalize", "words");
    expect(screen.getByLabelText("Password")).not.toHaveAttribute("onpaste");
  });

  it("sign-up says a verification email follows and links the terms", () => {
    wrap(<SignupForm />);
    expect(screen.getByText(/email you a link to verify your address/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "terms of use" })).toHaveAttribute("href", "/terms");
  });
});

describe("forgot-password copy", () => {
  it("explains the link once, including the Google case", () => {
    wrap(<ForgotPasswordPage />);
    expect(screen.getAllByText(/email you a link/i)).toHaveLength(1);
    expect(screen.getByText(/set one if you signed up with google/i)).toBeInTheDocument();
    expect(screen.queryByText(/we will send you a link/i)).toBeNull();
  });
});

describe("header and footer on the account screens", () => {
  it("marks Sign in as the current page on /login, and only that", async () => {
    wrap(<UserMenu />);
    const signIn = await screen.findByRole("link", { name: "Sign in" });
    expect(signIn).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Create account" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("marks Create account as the current page on /signup", async () => {
    pathname = "/signup";
    wrap(<UserMenu />);
    expect(await screen.findByRole("link", { name: "Create account" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Sign in" })).not.toHaveAttribute("aria-current");
  });

  it("steps the header's Create account back to secondary on the account and password-reset forms only", async () => {
    pathname = "/login";
    const login = wrap(<UserMenu />);
    expect((await screen.findByRole("link", { name: "Create account" })).className).not.toMatch(
      /bg-primary/,
    );
    login.unmount();
    pathname = "/signup";
    const signup = wrap(<UserMenu />);
    expect((await screen.findByRole("link", { name: "Create account" })).className).not.toMatch(
      /bg-primary/,
    );
    signup.unmount();
    for (const path of ["/forgot-password", "/reset-password"]) {
      pathname = path;
      const page = wrap(<UserMenu />);
      expect((await screen.findByRole("link", { name: "Create account" })).className).not.toMatch(
        /bg-primary/,
      );
      page.unmount();
    }
    pathname = "/";
    wrap(<UserMenu />);
    expect((await screen.findByRole("link", { name: "Create account" })).className).toMatch(
      /bg-primary/,
    );
  });

  it("gives the footer Terms link a 44 px target without growing the footer", () => {
    render(<SiteFooter />);
    const footer = screen.getByRole("contentinfo");
    const terms = within(footer).getByRole("link", { name: "Terms" });
    expect(terms).toHaveClass("min-h-11");
    expect(terms).toHaveClass("-my-3"); // the target overlaps the footer padding
    expect(footer).toHaveClass("text-sm"); // the consent notice is no longer 12 px
    expect(within(footer).getByText(/only voices you have consent to clone/i)).toBeInTheDocument();
  });
});
