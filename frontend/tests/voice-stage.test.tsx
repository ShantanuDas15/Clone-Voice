import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VoiceStage } from "@/components/voice-stage";
import type { VoiceProfileUpload } from "@/lib/api/voice";

const created: VoiceProfileUpload = {
  id: "v1",
  name: "Studio narrator",
  status: "ready",
  consent_confirmed_at: "2026-11-04T00:00:00Z",
  terms_version: "1",
  created_at: "2026-11-04T00:00:00Z",
  samples: [],
  quality: { rating: "good", hints: [] },
};
const peaks = Array.from({ length: 40 }, (_, i) => (i % 5) / 5);

const bars = () => [...screen.getByTestId("voice-shape").querySelectorAll("rect")];
const accent = () => bars().filter((b) => b.getAttribute("class")!.includes("fill-primary"));

describe("VoiceStage", () => {
  it("rests as a flat line with the steps, hidden below lg, when nothing is chosen", () => {
    const { container } = render(
      <VoiceStage state="ready" progress={0} peaks={null} created={null} />,
    );
    expect(bars()).toHaveLength(64);
    expect(bars().every((b) => b.getAttribute("height") === "2")).toBe(true);
    expect(accent()).toHaveLength(0);
    expect(container.querySelector("section")!.className).toContain("hidden");
    expect(screen.getByTestId("voice-stage-tag")).toHaveTextContent("Ready");
  });

  it("draws the chosen clip's own shape", () => {
    render(<VoiceStage state="ready" progress={0} peaks={peaks} created={null} />);
    const heights = new Set(bars().map((b) => b.getAttribute("height")));
    expect(heights.size).toBeGreaterThan(2);
  });

  it("fills the shape with the real upload progress and says the percentage", () => {
    render(<VoiceStage state="uploading" progress={0.5} peaks={peaks} created={null} />);
    expect(accent()).toHaveLength(32);
    expect(screen.getByRole("progressbar", { name: "Upload progress" })).toHaveValue(0.5);
    expect(screen.getByText("Uploading… 50%")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("analyses with no invented steps, and shows the panel on small screens", () => {
    const { container } = render(
      <VoiceStage state="analysing" progress={1} peaks={peaks} created={null} />,
    );
    expect(screen.getByText(/Analysing the voice/)).toBeInTheDocument();
    expect(accent()).toHaveLength(0);
    expect(container.querySelector("section")!.className).not.toMatch(/(^| )hidden/);
    // The only motion is the indeterminate bar, and it stops under reduced motion.
    expect(container.querySelector(".animate-indeterminate")!.className).toContain(
      "motion-reduce:animate-none",
    );
  });

  it("shows the created voice, draws it in once, and offers the next step", () => {
    render(<VoiceStage state="created" progress={1} peaks={peaks} created={created} />);
    expect(accent()).toHaveLength(64);
    expect(screen.getByTestId("voice-shape").getAttribute("class")).toContain(
      "motion-safe:animate-draw-in",
    );
    expect(screen.getByText("Voice “Studio narrator” created.")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Generate speech with “Studio narrator”" }),
    ).toHaveAttribute("href", "/generate?voice=v1");
  });

  it("uses no inline style anywhere (the site's CSP forbids it)", () => {
    for (const state of ["ready", "uploading", "analysing", "created"] as const) {
      const { container, unmount } = render(
        <VoiceStage state={state} progress={0.3} peaks={peaks} created={created} />,
      );
      expect(container.querySelector("[style]")).toBeNull();
      unmount();
    }
  });
});
