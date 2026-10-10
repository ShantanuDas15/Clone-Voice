import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthCard } from "@/components/auth-card";
import { SiteFooter } from "@/components/site-footer";
import { PageHeader } from "@/components/ui/page-header";
import { BRAND_NAME } from "@/lib/brand";

describe("PageHeader", () => {
  it("renders exactly one h1, with the lead and action beside it", () => {
    render(
      <PageHeader title="History" action={<button>Act</button>}>
        Replay what you made.
      </PageHeader>,
    );
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "History" })).toBeInTheDocument();
    expect(screen.getByText("Replay what you made.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Act" })).toBeInTheDocument();
  });
});

describe("AuthCard", () => {
  it("renders one h1 and its children, and the lead only when given", () => {
    const { rerender } = render(
      <AuthCard title="Sign in" lead="Welcome back.">
        <p>form</p>
      </AuthCard>,
    );
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByText("Welcome back.")).toBeInTheDocument();
    expect(screen.getByText("form")).toBeInTheDocument();
    rerender(
      <AuthCard title="Sign in">
        <p>form</p>
      </AuthCard>,
    );
    expect(screen.queryByText("Welcome back.")).toBeNull();
  });
});

describe("SiteFooter", () => {
  it("keeps the AI-content notice, names the product and links the terms", () => {
    render(<SiteFooter />);
    const footer = screen.getByRole("contentinfo");
    expect(
      within(footer).getByText(
        "Generated voices are AI-synthesized. Use only voices you have consent to clone.",
      ),
    ).toBeInTheDocument();
    expect(within(footer).getByText(BRAND_NAME)).toBeInTheDocument();
    expect(within(footer).getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
  });
});
