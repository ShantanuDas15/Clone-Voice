import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NavLink } from "@/components/nav-link";
import { StepList } from "@/components/step-list";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/field";

let path = "/voices";
vi.mock("next/navigation", () => ({ usePathname: () => path }));

/**
 * The state matrix of UX plan §4.7 (§9.1 item 7), one row per component. Tailwind variants are
 * how hover, active and disabled are expressed, so they are asserted on the class list; focus
 * comes from the global `:focus-visible` rule, asserted in theme.test.ts and the keyboard e2e.
 */
describe("Button states", () => {
  const variants = ["primary", "secondary", "quiet", "danger"] as const;

  it.each(variants)("%s has hover, active and a disabled style", (variant) => {
    const cls = buttonVariants({ variant });
    expect(cls).toMatch(/hover:/);
    expect(cls).toMatch(/active:/);
    expect(cls).toMatch(/disabled:cursor-not-allowed/);
    expect(cls).toMatch(/disabled:opacity-60/);
  });

  it.each(["primary", "secondary", "danger"] as const)(
    "%s does not change colour on hover while disabled",
    (variant) => {
      expect(buttonVariants({ variant })).toMatch(/disabled:hover:/);
    },
  );

  it("exposes disabled and loading to assistive technology together", () => {
    render(
      <Button disabled loading aria-describedby="why">
        Save
      </Button>,
    );
    render(<p id="why">Nothing to save.</p>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAccessibleDescription("Nothing to save.");
  });
});

describe("Field states", () => {
  it.each([
    ["input", <Input key="i" aria-label="x" />],
    ["select", <Select key="s" aria-label="x" />],
    ["textarea", <Textarea key="t" aria-label="x" />],
  ])("%s has hover, disabled and invalid styles and honours disabled", (_n, el) => {
    const { container } = render(el);
    const control = container.firstElementChild as HTMLElement;
    expect(control.className).toMatch(/hover:border-/);
    expect(control.className).toMatch(/disabled:opacity-60/);
    expect(control.className).toMatch(/aria-\[invalid=true\]:border-danger/);
  });

  it("a disabled control cannot be focused by the keyboard", () => {
    render(<Input aria-label="Name" disabled />);
    expect(screen.getByLabelText("Name")).toBeDisabled();
  });
});

describe("Alert states", () => {
  it("covers danger, success and neutral with text that carries the meaning", () => {
    render(
      <>
        <Alert tone="danger">Could not save.</Alert>
        <Alert tone="success">Saved.</Alert>
        <Alert>Heads up.</Alert>
      </>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Could not save.");
    expect(screen.getAllByRole("status").map((n) => n.textContent)).toEqual([
      "Saved.",
      "Heads up.",
    ]);
  });
});

describe("Badge states", () => {
  it.each(["neutral", "success", "notice"] as const)("%s always renders its text", (tone) => {
    render(<Badge tone={tone}>Label {tone}</Badge>);
    expect(screen.getByText(`Label ${tone}`)).toBeVisible();
  });
});

describe("NavLink states", () => {
  it("marks the current page, and a sub-route of it, but not a sibling", () => {
    path = "/voices";
    const { rerender } = render(<NavLink href="/voices">Voices</NavLink>);
    expect(screen.getByRole("link", { name: "Voices" })).toHaveAttribute("aria-current", "page");
    path = "/voices/new";
    rerender(<NavLink href="/voices">Voices</NavLink>);
    expect(screen.getByRole("link", { name: "Voices" })).toHaveAttribute("aria-current", "page");
    path = "/history";
    rerender(<NavLink href="/voices">Voices</NavLink>);
    expect(screen.getByRole("link", { name: "Voices" })).not.toHaveAttribute("aria-current");
  });

  it("is visibly different when current and has a hover state when not", () => {
    path = "/voices";
    render(
      <>
        <NavLink href="/voices">Voices</NavLink>
        <NavLink href="/history">History</NavLink>
      </>,
    );
    expect(screen.getByRole("link", { name: "Voices" }).className).toMatch(/font-semibold/);
    expect(screen.getByRole("link", { name: "History" }).className).toMatch(/hover:underline/);
    expect(screen.getByRole("link", { name: "History" }).className).not.toMatch(/font-semibold/);
  });
});

describe("StepList states", () => {
  it("states each step in words, and only the next step is current", () => {
    render(
      <StepList
        label="Getting started"
        steps={[
          { id: "a", title: "Verify email", status: "done", detail: "hidden when done" },
          { id: "b", title: "Create a voice", status: "current", detail: "shown" },
          { id: "c", title: "Generate", status: "todo" },
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("(Done)");
    expect(items[1]).toHaveTextContent("(Next)");
    expect(items[2]).toHaveTextContent("(To do)");
    expect(items.map((i) => i.getAttribute("aria-current"))).toEqual([null, "step", null]);
    expect(screen.queryByText("hidden when done")).not.toBeInTheDocument();
    expect(screen.getByText("shown")).toBeInTheDocument();
  });
});
