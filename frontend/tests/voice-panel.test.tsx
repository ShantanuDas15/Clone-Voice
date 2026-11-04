import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AuthCard } from "@/components/auth-card";
import { panelBars } from "@/lib/auth-panel";
import { addEnergy, decayEnergy, pulseVoice, swollenHeight } from "@/lib/voice-energy";

const copy = { headline: "Welcome back.", accent: "Your voices are waiting.", lead: "Pick up." };

describe("panelBars", () => {
  it("is deterministic, in range, and highlights one short run", () => {
    const a = panelBars(56);
    expect(panelBars(56)).toEqual(a);
    expect(a).toHaveLength(56);
    expect(a.every((b) => b.height >= 0.05 && b.height <= 1)).toBe(true);
    const lit = a.map((b, i) => (b.accent ? i : -1)).filter((i) => i >= 0);
    expect(lit.length).toBeGreaterThanOrEqual(6);
    expect(lit.length).toBeLessThanOrEqual(10);
    expect(lit[lit.length - 1]! - lit[0]! + 1).toBe(lit.length); // contiguous
    expect(new Set(a.map((b) => b.height)).size).toBeGreaterThan(10); // a voice, not a flat line
  });
});

describe("AuthCard with a voice panel", () => {
  const renderSplit = () =>
    render(
      <AuthCard title="Sign in" lead="Welcome back." panel={copy}>
        <p>form</p>
      </AuthCard>,
    );

  it("keeps one h1 and the form, and adds a panel that assistive technology skips", () => {
    renderSplit();
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText("form")).toBeInTheDocument();
    const panel = screen.getByTestId("voice-panel");
    expect(panel).toHaveAttribute("aria-hidden", "true");
    expect(panel).toHaveTextContent("Welcome back. Your voices are waiting.");
    expect(panel).toHaveTextContent("Consent first");
    // Hidden below lg: the strip takes its place there.
    expect(panel.className).toContain("hidden");
    expect(panel.className).toContain("lg:flex");
  });

  it("draws the full wave in the panel and a thin one above the card, only below lg", () => {
    renderSplit();
    const waves = screen.getAllByTestId("voice-wave");
    expect(waves.map((w) => w.querySelectorAll("rect").length)).toEqual([56, 44]);
    expect(waves[1]!.getAttribute("class")).toContain("lg:hidden");
    for (const wave of waves) {
      expect(wave).toHaveAttribute("aria-hidden", "true");
      expect(wave.querySelectorAll("rect.fill-primary").length).toBeGreaterThan(0);
    }
  });

  it("draws once, only where motion is allowed, with no inline style", () => {
    const { container } = renderSplit();
    const bars = [...container.querySelectorAll("[data-testid='voice-wave'] rect")];
    for (const bar of bars) {
      const cls = bar.getAttribute("class")!;
      expect(cls).toContain("motion-safe:animate-bar-in");
      expect(cls).toContain("[transform-box:fill-box]");
    }
    expect(container.querySelector("[style]")).toBeNull(); // the site's CSP forbids them
    // Nothing is endless: no looping animation class anywhere in the panel.
    expect(container.innerHTML).not.toMatch(/animate-(drift|indeterminate)/);
  });

  it("leaves the plain card alone when no panel is given", () => {
    render(
      <AuthCard title="Reset">
        <p>form</p>
      </AuthCard>,
    );
    expect(screen.queryByTestId("voice-panel")).toBeNull();
    expect(screen.queryByTestId("voice-wave")).toBeNull();
  });
});

describe("voice energy", () => {
  it("adds, caps and decays to rest", () => {
    expect(addEnergy(0.8, 0.5)).toBe(1);
    expect(addEnergy(0, 0.5)).toBe(0.5);
    let e = 1;
    let frames = 0;
    while (e > 0) {
      e = decayEnergy(e);
      frames += 1;
    }
    expect(frames).toBeLessThan(120); // about 2 s at 60 fps: settles well inside WCAG 2.2.2's 5 s
  });

  it("swells a bar only while there is energy, and never past the box", () => {
    expect(swollenHeight(0.4, 0, 3, 1000)).toBeCloseTo(0.4);
    expect(swollenHeight(0.4, 1, 3, 1000)).toBeGreaterThanOrEqual(0.4);
    expect(swollenHeight(0.9, 1, 0, 0)).toBeLessThanOrEqual(1);
  });
});

describe("the wave reacting to the form beside it", () => {
  it("swells bars on a pulse, then settles back to rest, with no inline style", () => {
    vi.useFakeTimers();
    const raf = vi
      .spyOn(window, "requestAnimationFrame")
      .mockImplementation((cb) => setTimeout(() => cb(performance.now()), 16) as unknown as number);
    const { container } = render(
      <AuthCard title="Sign in" panel={copy}>
        <p>form</p>
      </AuthCard>,
    );
    const rect = container.querySelector("[data-testid='voice-wave'] rect")!;
    const rest = rect.getAttribute("height");
    act(() => pulseVoice(1));
    act(() => vi.advanceTimersByTime(48));
    expect(rect.getAttribute("height")).not.toBe(rest);
    act(() => vi.advanceTimersByTime(4000));
    expect(rect.getAttribute("height")).toBe(rest);
    expect(container.querySelector("[style]")).toBeNull();
    raf.mockRestore();
    vi.useRealTimers();
  });

  it("labels the state: listening after a pulse, idle again after a moment", () => {
    vi.useFakeTimers();
    render(
      <AuthCard title="Sign in" panel={copy}>
        <p>form</p>
      </AuthCard>,
    );
    const state = screen.getByTestId("voice-state");
    expect(state).toHaveTextContent("voiceprint · idle");
    act(() => pulseVoice(0.5));
    expect(state).toHaveTextContent("listening");
    act(() => vi.advanceTimersByTime(1500));
    expect(state).toHaveTextContent("idle");
    vi.useRealTimers();
  });
});
