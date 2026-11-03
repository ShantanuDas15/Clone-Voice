"use client";

import { type ReactNode, useState } from "react";

import { HomeBackdrop } from "@/components/home-backdrop";
import { HomeSampleCard } from "@/components/home-sample-card";
import type { HomeSample } from "@/lib/home-sample";

/**
 * The home page's opening: the copy and actions (passed in, so they stay server-rendered) beside a
 * sample the visitor can play, over a decorative background that reacts while it plays. Without a
 * sample the copy simply stands alone. The bottom padding makes room for the ribbon band, which
 * holds no text.
 */
export function HomeHero({ sample, children }: { sample: HomeSample | null; children: ReactNode }) {
  const [playing, setPlaying] = useState(false);
  return (
    <section
      aria-labelledby="home-title"
      data-home-hero
      className={`relative isolate grid gap-10 pb-[9.5rem] pt-6 sm:pt-10 ${
        sample ? "md:grid-cols-[1.05fr_0.95fr] md:items-center md:gap-14" : ""
      }`}
    >
      <HomeBackdrop live={playing} />
      <div className="min-w-0">{children}</div>
      {sample ? (
        <div className="min-w-0">
          <HomeSampleCard sample={sample} onPlayingChange={setPlaying} />
        </div>
      ) : null}
    </section>
  );
}
