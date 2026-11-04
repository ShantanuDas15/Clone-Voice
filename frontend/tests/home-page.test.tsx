import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HomeConsentGate } from "@/components/home-consent-gate";
import { HomeEraseDemo } from "@/components/home-erase-demo";
import { HomeHowItWorks } from "@/components/home-how-it-works";
import { DRAW_DELAY_CLASSES, drawDelay } from "@/lib/home-backdrop";
import { miniBars } from "@/lib/home-demo";
import { HOME_BARS, barHeight, peakAt, pointerNear, sweepNear } from "@/lib/home-voiceprint";

vi.mock("@/components/auth-provider", () => ({ useAuth: () => ({ status: "unauthenticated" }) }));

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

describe("voiceprint geometry", () => {
  it("reads the clip's peak at any position, and tolerates a missing or out-of-range clip", () => {
    expect(peakAt([0, 50, 100], 0)).toBe(0);
    expect(peakAt([0, 50, 100], 1)).toBe(1);
    expect(peakAt([], 0.3)).toBe(0.5);
    expect(peakAt([250], 0.5)).toBe(1);
  });

  it("swells bars near the pointer and the playhead, and only then", () => {
    expect(pointerNear(500, 500, 1000)).toBe(1);
    expect(pointerNear(900, 500, 1000)).toBeLessThan(0.01);
    expect(pointerNear(500, -1, 1000)).toBe(0); // no pointer over the stage
    expect(sweepNear(0.5, 0.5, true)).toBe(1);
    expect(sweepNear(0.5, 0.5, false)).toBe(0); // nothing plays
  });

  it("keeps every bar inside the stage, whatever the inputs", () => {
    for (let i = 0; i < HOME_BARS; i += 1) {
      for (const [peak, pointer, sweep] of [
        [0, 0, 0],
        [1, 1, 1],
        [0.5, 1, 0],
      ] as const) {
        const h = barHeight(i, peak, 7.3, pointer, sweep);
        expect(h).toBeGreaterThanOrEqual(0.04);
        expect(h).toBeLessThanOrEqual(0.96);
      }
    }
  });

  it("makes the little illustrations from deterministic heights", () => {
    expect(miniBars(40, 3)).toEqual(miniBars(40, 3));
    expect(miniBars(40, 3).every((v) => v >= 0.1 && v <= 1)).toBe(true);
    expect(miniBars(40, 3)).not.toEqual(miniBars(40, 5));
  });
});

describe("HomeConsentGate", () => {
  it("stays locked until the right to use the voice is confirmed, then unlocks and un-confirms", async () => {
    render(<HomeConsentGate />);
    const create = screen.getByRole("button", { name: "Create voice" });
    expect(create).toHaveAttribute("aria-disabled", "true");
    await userEvent.click(create);
    expect(screen.getByRole("status")).toHaveTextContent("Locked until you confirm.");

    const box = screen.getByRole("checkbox", { name: "I have the right to use this voice." });
    await userEvent.click(box);
    expect(create).toHaveAttribute("aria-disabled", "false");
    expect(screen.getByTestId("consent-gate").className).toContain("hx-on");
    await userEvent.click(create);
    expect(screen.getByRole("status")).toHaveTextContent("Voice created (example)");

    await userEvent.click(box); // taking the confirmation back locks it again
    expect(create).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("status")).toHaveTextContent("Locked until you confirm.");
  });
});

describe("HomeEraseDemo", () => {
  afterEach(() => vi.useRealTimers());

  it("erases the takes, then the voice, says so, and can start over", async () => {
    vi.useFakeTimers();
    render(<HomeEraseDemo />);
    const items = () => screen.getAllByRole("listitem");
    expect(items().filter((li) => li.className.includes("hx-gone"))).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Delete voice" }));
    act(() => vi.advanceTimersByTime(260));
    expect(items()[3]!.className).toContain("hx-gone"); // the last take first
    expect(items()[0]!.className).not.toContain("hx-gone"); // the voice goes last
    act(() => vi.advanceTimersByTime(260 * 3));
    expect(items().every((li) => li.className.includes("hx-gone"))).toBe(true);
    expect(screen.getByRole("status")).toHaveTextContent("Voice and 3 takes erased (example).");

    fireEvent.click(screen.getByRole("button", { name: "Start over" }));
    expect(items().some((li) => li.className.includes("hx-gone"))).toBe(false);
    expect(screen.getByRole("button", { name: "Delete voice" })).toBeEnabled();
  });
});

describe("HomeHowItWorks", () => {
  it("lists the three real steps, with the first in view and a decorative picture", () => {
    const { container } = render(<HomeHowItWorks />);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Add a sample",
      "Type your text",
      "Play or download",
    ]);
    expect(container.querySelector(".hx-pic")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelectorAll(".hx-step")[0]!.className).toContain("hx-on");
    expect(container.querySelectorAll(".hx-step")[1]!.className).not.toContain("hx-on");
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

  it("keeps the whole copy: the headline, the lede, the demos and the single closing action", async () => {
    const { default: HomePage } = await import("@/app/page");
    render(<HomePage />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Clone a voice. Say anything.",
    );
    expect(screen.getByText(/Upload or record 10 to 30 seconds/)).toBeInTheDocument();
    expect(screen.getByTestId("consent-gate")).toBeInTheDocument();
    expect(screen.getByTestId("erase-demo")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Try it with your own voice." }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Create account" })).toHaveLength(2);
  });
});
