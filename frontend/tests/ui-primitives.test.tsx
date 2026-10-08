import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";

describe("Button", () => {
  it("defaults to type=button so it never submits a form by accident", () => {
    render(<Button>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("type", "button");
  });

  it("keeps an explicit submit type", () => {
    render(<Button type="submit">Go</Button>);
    expect(screen.getByRole("button", { name: "Go" })).toHaveAttribute("type", "submit");
  });

  it("marks a loading button busy and keeps its label", () => {
    render(<Button loading>Generating…</Button>);
    expect(screen.getByRole("button", { name: "Generating…" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("is not busy by default", () => {
    render(<Button>Idle</Button>);
    expect(screen.getByRole("button")).not.toHaveAttribute("aria-busy");
  });

  it("does not fire onClick while disabled", async () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Nope
      </Button>,
    );
    await userEvent.click(screen.getByRole("button"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("gives each variant a distinct look and every size a 44 px target", () => {
    const looks = (["primary", "secondary", "quiet", "danger"] as const).map((variant) =>
      buttonVariants({ variant }),
    );
    expect(new Set(looks).size).toBe(4);
    expect(buttonVariants({ size: "sm" })).toContain("min-h-11");
    expect(buttonVariants({ variant: "danger" })).toContain("bg-danger");
  });

  it("merges a caller class last so layout tweaks win", () => {
    render(<Button className="mt-6">Spaced</Button>);
    expect(screen.getByRole("button")).toHaveClass("mt-6");
  });
});

describe("Alert", () => {
  it("announces danger assertively and everything else politely", () => {
    render(
      <>
        <Alert tone="danger">Broke</Alert>
        <Alert tone="success">Saved</Alert>
        <Alert>Note</Alert>
      </>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Broke");
    expect(screen.getAllByRole("status").map((n) => n.textContent)).toEqual(["Saved", "Note"]);
  });

  it("lets the caller override the role and pass an id", () => {
    render(
      <Alert tone="danger" role="status" id="x">
        Soft
      </Alert>,
    );
    expect(screen.getByRole("status")).toHaveAttribute("id", "x");
  });
});

describe("Badge", () => {
  it("renders its text, which carries the meaning", () => {
    render(<Badge tone="success">Ready</Badge>);
    expect(screen.getByText("Ready")).toBeVisible();
  });
});
