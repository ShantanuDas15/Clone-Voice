"use client";

import { type ReactNode, useState } from "react";

import { HomeSampleCard } from "@/components/home-sample-card";
import { HomeVoiceprint } from "@/components/home-voiceprint";
import type { HomeSample } from "@/lib/home-sample";

/**
 * The home page's opening (owner-approved mock, UX plan §12.25): the headline and actions (passed in,
 * so they stay server-rendered), a drifting aurora behind the page, a full-width voiceprint that
 * follows the pointer, and the sample pill that plays the clip. "Pause motion" holds every endless
 * movement still (WCAG 2.2.2); reduced motion never starts it.
 */
export function HomeHero({ sample, children }: { sample: HomeSample | null; children: ReactNode }) {
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [paused, setPaused] = useState(false);
  return (
    <section
      aria-labelledby="home-title"
      data-home-hero
      data-motion={paused ? "paused" : "on"}
      className="hx-hero relative"
    >
      <div aria-hidden className="hx-aurora">
        <i className="hx-a" />
        <i className="hx-b" />
      </div>
      <div className="min-w-0">{children}</div>
      <div className="hx-print">
        <HomeVoiceprint
          peaks={sample?.peaks ?? []}
          live={playing}
          progress={progress}
          paused={paused}
        />
        <button
          type="button"
          aria-pressed={paused}
          onClick={() => setPaused((p) => !p)}
          className="hx-motion"
        >
          {paused ? "Resume motion" : "Pause motion"}
        </button>
      </div>
      {sample ? (
        <HomeSampleCard sample={sample} onPlayingChange={setPlaying} onProgress={setProgress} />
      ) : null}
    </section>
  );
}
