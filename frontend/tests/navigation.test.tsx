import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NavLink, isCurrent } from "@/components/nav-link";

let pathname = "/generate";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

describe("isCurrent", () => {
  it.each([
    ["/voices", "/voices", true],
    ["/voices/abc", "/voices", true],
    ["/voices-old", "/voices", false],
    ["/history", "/voices", false],
    [null, "/voices", false],
  ])("%s vs %s -> %s", (p, href, expected) => expect(isCurrent(p, href)).toBe(expected));
});

describe("NavLink", () => {
  beforeEach(() => {
    pathname = "/generate";
  });

  it("exposes only the current page with aria-current and a visible marker", () => {
    render(
      <>
        <NavLink href="/generate">Generate</NavLink>
        <NavLink href="/voices">Voices</NavLink>
      </>,
    );
    const here = screen.getByRole("link", { name: "Generate" });
    expect(here).toHaveAttribute("aria-current", "page");
    expect(here).toHaveClass("underline", "font-semibold");
    const other = screen.getByRole("link", { name: "Voices" });
    expect(other).not.toHaveAttribute("aria-current");
    expect(other).not.toHaveClass("font-semibold");
  });
});

describe("route layout", () => {
  const root = path.resolve(__dirname, "..");

  it("has one page per job and none of the old ones", () => {
    for (const route of ["generate", "voices", "history", "account"]) {
      const src = readFileSync(path.join(root, "app/(app)", route, "page.tsx"), "utf8");
      expect(src.match(/<h1\b/g), `${route} has exactly one h1`).toHaveLength(1);
    }
    for (const old of ["dashboard", "profile"]) {
      expect(() => readFileSync(path.join(root, "app/(app)", old, "page.tsx"))).toThrow();
    }
  });

  it("explains the verification gate once, on the pages that need it", () => {
    const read = (rel: string) => readFileSync(path.join(root, rel), "utf8");
    for (const route of ["generate", "voices"]) {
      expect(read(`app/(app)/${route}/page.tsx`)).toContain("<VerifyEmailAlert />");
    }
    for (const rel of ["components/text-to-speech-form.tsx", "components/upload-voice-form.tsx"]) {
      expect(read(rel)).not.toContain("ResendVerification");
    }
    expect(read("components/app-shell.tsx")).not.toMatch(/sticky|VerificationBanner/);
  });

  it("redirects the old routes permanently (308)", async () => {
    // @ts-expect-error -- plain .mjs config without type declarations
    const mod = (await import("../next.config.mjs")) as {
      default: { redirects: () => Promise<Array<Record<string, unknown>>> };
    };
    const rules = await mod.default.redirects();
    expect(rules).toEqual(
      expect.arrayContaining([
        { source: "/dashboard", destination: "/generate", permanent: true },
        { source: "/profile", destination: "/voices", permanent: true },
      ]),
    );
  });
});
