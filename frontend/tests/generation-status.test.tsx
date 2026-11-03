import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  GenerationStatus,
  SLOW_AFTER_SECONDS,
  generationPhase,
} from "@/components/generation-status";

describe("generationPhase", () => {
  it("is working until the slow threshold, then slow", () => {
    expect(generationPhase(0)).toBe("working");
    expect(generationPhase(SLOW_AFTER_SECONDS - 1)).toBe("working");
    expect(generationPhase(SLOW_AFTER_SECONDS)).toBe("slow");
    expect(generationPhase(300)).toBe("slow");
  });
});

describe("GenerationStatus", () => {
  it("is one polite live region with the seconds hidden from screen readers", () => {
    render(<GenerationStatus elapsed={3} />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveTextContent("Generating… 3 s");
    expect(region.querySelector("span")).toHaveAttribute("aria-hidden", "true");
  });

  it("starts with the usual wording and a working icon", () => {
    render(<GenerationStatus elapsed={2} />);
    expect(screen.getByText(/This can take a minute/)).toBeInTheDocument();
    expect(screen.getByTestId("generation-icon")).toHaveAttribute("data-phase", "working");
  });

  it("says plainly when it is taking longer, and offers a way out", () => {
    render(<GenerationStatus elapsed={SLOW_AFTER_SECONDS} />);
    expect(screen.getByRole("status")).toHaveTextContent("Still generating…");
    expect(screen.getByText(/taking longer than usual/)).toBeInTheDocument();
    expect(screen.getByText(/cancel and try again/)).toBeInTheDocument();
    expect(screen.getByTestId("generation-icon")).toHaveAttribute("data-phase", "slow");
  });

  it("keeps the bar's reduced-motion fallback and never invents stages", () => {
    const { container } = render(<GenerationStatus elapsed={5} />);
    expect(container.querySelector(".motion-reduce\\:animate-none")).not.toBeNull();
    expect(screen.queryByText(/synthesizing|preparing/i)).not.toBeInTheDocument();
  });
});
