import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PasswordField, TextField } from "@/components/form-fields";
import HomePage from "@/app/page";

describe("landing page", () => {
  it("has one h1, a primary and a secondary action, and the three plain statements", () => {
    render(<HomePage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("publishes no retention figure (it is a server setting, UX plan §11.3)", () => {
    const { container } = render(<HomePage />);
    expect(container.textContent).not.toMatch(/\b\d+\s*days?\b/i);
    expect(container.textContent).not.toMatch(/kept for/i);
  });
});

describe("TextField hint", () => {
  it("is announced with the field, and joined by the error when there is one", () => {
    const { rerender } = render(<TextField label="Name" hint="Use your real name" />);
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Use your real name");
    rerender(<TextField label="Name" hint="Use your real name" error="Enter your name" />);
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(
      "Use your real name Enter your name",
    );
  });
});

describe("PasswordField", () => {
  it("hides the password until asked, then shows and hides it again", async () => {
    render(<PasswordField label="Password" hint="8 to 128 characters" />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAccessibleDescription("8 to 128 characters");
    const toggle = screen.getByRole("checkbox", { name: "Show password" });
    await userEvent.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    await userEvent.click(toggle);
    expect(input).toHaveAttribute("type", "password");
  });
});

describe("copy rules (UX plan §7 U2 exit criteria)", () => {
  const ROOT = path.resolve(__dirname, "..");
  const files = (dir: string): string[] =>
    readdirSync(path.join(ROOT, dir)).flatMap((n) => {
      const rel = path.join(dir, n);
      return statSync(path.join(ROOT, rel)).isDirectory()
        ? files(rel)
        : /\.tsx$/.test(n)
          ? [rel]
          : [];
    });
  const sources = [...files("app"), ...files("components")];

  it.each([
    ['"Working…"', /Working…/],
    ['"Get started" as an action', /Get started/],
    ['"Sign up" as an action name', />\s*Sign up\s*</],
    ["a bare Loading… label", /"Loading…"/],
    ["internal state in the consent line", /not published yet/],
  ])("has no %s", (_name, pattern) => {
    expect(sources.filter((f) => pattern.test(readFileSync(path.join(ROOT, f), "utf8")))).toEqual(
      [],
    );
  });
});
