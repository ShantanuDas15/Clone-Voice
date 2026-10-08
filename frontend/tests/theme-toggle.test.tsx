import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "@/components/theme-toggle";
import { THEME_COOKIE } from "@/lib/theme";

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.removeAttribute("data-theme");
    document.cookie = `${THEME_COOKIE}=; Max-Age=0; Path=/`;
  });

  it("names the current mode and the next one", () => {
    render(<ThemeToggle initial="system" />);
    expect(screen.getByRole("button", { name: "Theme: System. Switch to light." })).toBeVisible();
  });

  it("cycles system → light → dark → system, applying and announcing each", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle initial="system" />);
    const button = () => screen.getByRole("button", { name: /^Theme:/ });

    await user.click(button());
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(button()).toHaveAccessibleName("Theme: Light. Switch to dark.");
    expect(screen.getByRole("status")).toHaveTextContent("Theme set to light.");

    await user.click(button());
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.cookie).toContain(`${THEME_COOKIE}=dark`);

    await user.click(button());
    expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
    expect(document.cookie).not.toContain(THEME_COOKIE);
    expect(screen.getByRole("status")).toHaveTextContent("Theme set to system.");
  });

  it("starts from the server-provided theme without announcing anything", () => {
    render(<ThemeToggle initial="dark" />);
    expect(screen.getByRole("button", { name: "Theme: Dark. Switch to system." })).toBeVisible();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});
