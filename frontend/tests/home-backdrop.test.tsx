import { readFileSync } from "node:fs";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HomeBackdrop } from "@/components/home-backdrop";
import {
  DRAW_DELAY_CLASSES,
  RIBBON_WIDTH,
  SIDE_BAR_COUNT,
  drawDelay,
  ribbons,
  sideBars,
} from "@/lib/home-backdrop";

vi.mock("@/components/auth-provider", () => ({ useAuth: () => ({ status: "unauthenticated" }) }));

describe("backdrop geometry", () => {
  it("is deterministic, so the server and the browser draw the same thing", () => {
    expect(sideBars()).toEqual(sideBars());
    expect(ribbons()).toEqual(ribbons());
  });

  it("keeps every bar inside its range and fades them outward from the content", () => {
    const bars = sideBars();
    expect(bars).toHaveLength(SIDE_BAR_COUNT);
    for (const b of bars) {
      expect(b.height).toBeGreaterThanOrEqual(10);
      expect(b.height).toBeLessThanOrEqual(88);
      expect(b.opacity).toBeGreaterThanOrEqual(0.12);
      expect(b.opacity).toBeLessThanOrEqual(0.5);
    }
    expect(bars[0]!.opacity).toBeGreaterThan(bars[bars.length - 1]!.opacity);
  });

  it("draws ribbons that loop seamlessly: the second half repeats the first", () => {
    for (const r of ribbons()) {
      const ys = [...r.path.matchAll(/[ML]([\d.]+) ([\d.]+)/g)].map((m) => Number(m[2]));
      expect(ys).toHaveLength(241);
      const half = 120; // 2400 wide, two whole periods: the middle point equals the first
      expect(ys[half]).toBeCloseTo(ys[0]!, 0);
      expect(ys[240]).toBeCloseTo(ys[0]!, 0);
      expect(r.path.startsWith("M0.0")).toBe(true);
      expect(RIBBON_WIDTH).toBe(2400);
    }
  });
});

describe("draw-in stagger", () => {
  it("steps up by 12 ms from 160 ms, one literal class each, so Tailwind can generate them", () => {
    const ms = DRAW_DELAY_CLASSES.map((c) => Number(/animation-delay:(\d+)ms/.exec(c)?.[1]));
    expect(ms[0]).toBe(160);
    expect(ms.slice(1).every((v, i) => v === (ms[i] as number) + 12)).toBe(true);
    expect(DRAW_DELAY_CLASSES.every((c) => c.startsWith("motion-safe:"))).toBe(true);
  });

  it("delays later bars more, and holds the last step for any bars beyond it", () => {
    expect(drawDelay(0, 4)).toBe(DRAW_DELAY_CLASSES[0]);
    expect(drawDelay(7, 4)).toBe(DRAW_DELAY_CLASSES[1]);
    expect(drawDelay(10_000, 4)).toBe(DRAW_DELAY_CLASSES[DRAW_DELAY_CLASSES.length - 1]);
  });
});

describe("HomeBackdrop", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is decorative: hidden from assistive technology and ignored by the pointer", () => {
    render(<HomeBackdrop live={false} />);
    const root = screen.getByTestId("home-backdrop");
    expect(root).toHaveAttribute("aria-hidden", "true");
    expect(root.className).toContain("pointer-events-none");
    expect(root.querySelectorAll("a, button, input, [tabindex]")).toHaveLength(0);
  });

  it("draws three ribbons and two margins of bars", () => {
    const { container } = render(<HomeBackdrop live={false} />);
    expect(container.querySelectorAll("path")).toHaveLength(3);
    expect(screen.getAllByTestId("home-bars")).toHaveLength(2);
    expect(container.querySelectorAll("line")).toHaveLength(2 * SIDE_BAR_COUNT);
  });

  it("ripples the side bars outward: every bar draws itself, later ones a little after", () => {
    render(<HomeBackdrop live={false} />);
    const [left] = screen.getAllByTestId("home-bars");
    const lines = [...(left as Element).querySelectorAll("line")];
    expect(
      lines.every((l) => l.getAttribute("class")!.includes("motion-safe:animate-bar-in")),
    ).toBe(true);
    expect(lines[0]!.getAttribute("class")).toContain(DRAW_DELAY_CLASSES[0]);
    expect(lines[lines.length - 1]!.getAttribute("class")).toContain(
      drawDelay(lines.length - 1, 4),
    );
    expect(drawDelay(lines.length - 1, 4)).not.toBe(DRAW_DELAY_CLASSES[0]);
  });

  it("swells while the sample plays and settles after", () => {
    const { rerender } = render(<HomeBackdrop live={false} />);
    expect(screen.getByTestId("home-wave")).toHaveAttribute("data-live", "false");
    expect(screen.getByTestId("home-wave").querySelector(".scale-y-\\[0\\.7\\]")).not.toBeNull();
    rerender(<HomeBackdrop live />);
    expect(screen.getByTestId("home-wave")).toHaveAttribute("data-live", "true");
    expect(screen.getByTestId("home-wave").querySelector(".scale-y-\\[1\\.25\\]")).not.toBeNull();
  });

  it("only moves where the user allows motion (every animation class is a motion-safe one)", () => {
    const { container } = render(<HomeBackdrop live={false} />);
    const animated = [...container.querySelectorAll("[class*='animate-']")];
    expect(animated.length).toBeGreaterThan(0);
    for (const el of animated) {
      for (const token of el
        .getAttribute("class")!
        .split(/\s+/)
        .filter((t) => t.includes("animate-"))) {
        expect(token.startsWith("motion-safe:")).toBe(true);
      }
    }
  });

  it("pauses the drift while it is off screen, and resumes when it is back", () => {
    let notify: (entries: Array<{ isIntersecting: boolean }>) => void = () => {};
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: typeof notify) {
          notify = cb;
        }
        observe() {}
        disconnect() {}
      },
    );
    const { container } = render(<HomeBackdrop live={false} />);
    const svg = screen.getByTestId("home-wave").querySelector("svg") as SVGElement;
    expect(screen.getByTestId("home-wave")).toHaveAttribute("data-paused", "false");
    act(() => notify([{ isIntersecting: false }]));
    expect(screen.getByTestId("home-wave")).toHaveAttribute("data-paused", "true");
    expect(svg).toBeInTheDocument();
    act(() => notify([{ isIntersecting: true }]));
    expect(screen.getByTestId("home-wave")).toHaveAttribute("data-paused", "false");
    // The pause itself is a global rule (see below), not a class that the animation shorthand can undo.
    expect(readFileSync("app/globals.css", "utf8")).toMatch(
      /\.home-wave\[data-paused="true"\] svg\s*\{\s*animation-play-state:\s*paused/,
    );
  });
});

describe("Content-Security-Policy", () => {
  // The site's policy forbids inline `style` attributes (lib/csp.ts), and it is meant to be enforced:
  // anything that depended on one would break. The home page must not use any.
  it("leaves no inline style attribute anywhere on the home page", async () => {
    const { default: HomePage } = await import("@/app/page");
    const { container } = render(<HomePage />);
    expect(container.querySelectorAll("[style]")).toHaveLength(0);
  });
});
