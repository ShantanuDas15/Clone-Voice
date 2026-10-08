import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MobileTabs } from "@/components/mobile-tabs";
import { APP_LINKS } from "@/components/user-menu";

let status = "authenticated";
vi.mock("@/components/auth-provider", () => ({ useAuth: () => ({ status }) }));
vi.mock("next/navigation", () => ({ usePathname: () => "/voices" }));

describe("MobileTabs", () => {
  it("lists every destination as a tab and marks the current one", () => {
    status = "authenticated";
    render(<MobileTabs />);
    const nav = screen.getByRole("navigation", { name: "Mobile" });
    expect(nav).toHaveClass("sm:hidden");
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(APP_LINKS.map((l) => l.label));
    expect(links.filter((l) => l.getAttribute("aria-current") === "page")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Voices" })).toHaveAttribute("aria-current", "page");
    for (const l of links) expect(l.className).toContain("min-h-14");
  });

  it.each(["loading", "unauthenticated"])("renders nothing while %s", (s) => {
    status = s;
    const { container } = render(<MobileTabs />);
    expect(container).toBeEmptyDOMElement();
  });
});
