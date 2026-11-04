"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";

import { MiniBars } from "@/components/home-consent-gate";
import { miniBars } from "@/lib/home-demo";

const SAMPLE_BARS = miniBars(48, 5);
const TAKE_BARS = miniBars(48, 9);

const STEPS = [
  { title: "Add a sample", body: "Upload an audio file, or record with your microphone." },
  { title: "Type your text", body: "Choose the voice and write what it should say." },
  { title: "Play or download", body: "Listen right away, replay it later from your history." },
] as const;

function Meta({ left, right }: { left: ReactNode; right: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 font-mono text-xs text-muted-foreground">
      <span>{left}</span>
      <span>{right}</span>
    </div>
  );
}

/** The picture for step `i`; the same three are used beside the steps and, on narrow screens, inside each. */
function Picture({ i }: { i: number }) {
  if (i === 0) {
    return (
      <div className="grid gap-3">
        <Meta left="sample.wav" right="8.0 s · 1 clip" />
        <MiniBars bars={SAMPLE_BARS} live />
        <Meta left="Consent confirmed" right="ready" />
      </div>
    );
  }
  if (i === 1) {
    return (
      <div className="grid gap-3">
        <Meta left="Voice: My voice" right="Delivery: Auto" />
        <p className="hx-typed">Welcome back to the show.</p>
        <Meta left="26 / 500" right="Generate speech" />
      </div>
    );
  }
  return (
    <div className="grid gap-3">
      <Meta left="Take · 0:04" right="AI-generated" />
      <MiniBars bars={TAKE_BARS} live />
      <Meta left="Play" right="Download · replay from history" />
    </div>
  );
}

/**
 * How it works (owner-approved mock): a sticky picture that changes with the step in view. Below
 * `md` the picture sits inside each step instead. The picture is decorative (the steps say it all).
 */
export function HomeHowItWorks() {
  const [active, setActive] = useState(0);
  const steps = useRef<Array<HTMLLIElement | null>>([]);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.step));
        }
      },
      { rootMargin: "-45% 0px -45% 0px" },
    );
    steps.current.forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, []);

  return (
    <div className="hx-how">
      <div aria-hidden className="hx-card hx-pic">
        {STEPS.map((s, i) => (
          <div key={s.title} className={`hx-layer ${active === i ? "hx-on" : ""}`}>
            <Picture i={i} />
          </div>
        ))}
      </div>
      <ol className="hx-steps">
        {STEPS.map((s, i) => (
          <li
            key={s.title}
            data-step={i}
            ref={(el) => {
              steps.current[i] = el;
            }}
            className={`hx-step ${active === i ? "hx-on" : ""}`}
          >
            <span className="font-mono text-sm text-primary">Step {i + 1}</span>
            <h3>{s.title}</h3>
            <p>{s.body}</p>
            <div aria-hidden className="hx-card hx-inline">
              <Picture i={i} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
