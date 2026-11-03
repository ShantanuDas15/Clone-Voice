import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MicOrb } from "@/components/mic-orb";

describe("MicOrb", () => {
  it("is decorative: hidden from assistive technology", () => {
    render(<MicOrb level={0.5} />);
    expect(screen.getByTestId("mic-orb")).toHaveAttribute("aria-hidden", "true");
  });

  it("rests at scale 1 and a dim ring when nothing is heard", () => {
    render(<MicOrb level={0} />);
    const ring = screen.getByTestId("mic-orb-ring");
    expect(ring.style.transform).toBe("scale(1)");
    expect(ring.style.opacity).toBe("0.25");
  });

  it("swells the ring with the level, using transform and opacity only", () => {
    render(<MicOrb level={1} />);
    const ring = screen.getByTestId("mic-orb-ring");
    expect(ring.style.transform).toBe("scale(1.5)");
    expect(ring.style.opacity).toBe("1");
  });

  it("looks off, not live, while the microphone is silent", () => {
    render(<MicOrb level={0.8} silent />);
    expect(screen.getByTestId("mic-orb")).toHaveAttribute("data-silent", "true");
    expect(screen.getByTestId("mic-orb-ring").style.transform).toBe("scale(1)");
  });

  it("drops the scaling under reduced motion", () => {
    render(<MicOrb level={1} />);
    expect(screen.getByTestId("mic-orb-ring").className).toContain("motion-reduce:!transform-none");
  });
});
