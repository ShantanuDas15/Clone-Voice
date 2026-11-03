import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WaveformPreview } from "@/components/waveform-preview";

describe("WaveformPreview", () => {
  it("draws one bar per peak, hidden from assistive technology", () => {
    const { container } = render(<WaveformPreview peaks={[10, 50, 100]} />);
    const svg = screen.getByTestId("waveform-preview");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelectorAll("rect")).toHaveLength(3);
  });

  it("scales bar height with the peak and keeps a visible minimum", () => {
    const { container } = render(<WaveformPreview peaks={[0, 100]} />);
    const [quiet, loud] = Array.from(container.querySelectorAll("rect"));
    expect(Number(quiet?.getAttribute("height"))).toBe(2);
    expect(Number(loud?.getAttribute("height"))).toBe(30);
  });

  it("clamps out-of-range values instead of drawing outside the box", () => {
    const { container } = render(<WaveformPreview peaks={[-5, 400]} />);
    const heights = Array.from(container.querySelectorAll("rect")).map((r) =>
      Number(r.getAttribute("height")),
    );
    expect(heights).toEqual([2, 30]);
  });

  it("renders nothing without peaks", () => {
    for (const peaks of [null, undefined, []]) {
      const { container, unmount } = render(<WaveformPreview peaks={peaks} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });
});
