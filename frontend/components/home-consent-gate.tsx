"use client";

import { useId, useState } from "react";

import { miniBars } from "@/lib/home-demo";

const BARS = miniBars(40, 3);

/** A small bar illustration; `live` ripples it (the ripple is CSS, with no inline style). */
export function MiniBars({ bars, live = false }: { bars: readonly number[]; live?: boolean }) {
  const pitch = 240 / bars.length;
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox="0 0 240 84"
      preserveAspectRatio="none"
      className={`hx-bars ${live ? "hx-on" : ""}`}
    >
      {bars.map((v, i) => (
        <rect
          key={i}
          x={i * pitch + 1}
          y={42 - (v * 84) / 2}
          width={Math.max(1.5, pitch - 2.5)}
          height={v * 84}
          rx={1.5}
        />
      ))}
    </svg>
  );
}

/**
 * The consent promise you can try (owner-approved mock): the example "Create voice" button stays
 * locked, and the bars stay grey, until the box is ticked. It mirrors the real upload, where a voice
 * can only be created once the right to use it is confirmed. Nothing is sent anywhere.
 */
export function HomeConsentGate() {
  const [ok, setOk] = useState(false);
  const [made, setMade] = useState(false);
  const id = useId();
  return (
    <div className={`hx-card hx-gate ${ok ? "hx-on" : ""}`} data-testid="consent-gate">
      <h3 className="font-semibold">New voice from a sample</h3>
      <p className="text-sm text-muted-foreground">An example screen. Nothing is uploaded.</p>
      <div className="mt-4">
        <MiniBars bars={BARS} live={ok} />
      </div>
      <label htmlFor={id} className="hx-gate-row">
        <input
          id={id}
          type="checkbox"
          checked={ok}
          onChange={(e) => {
            setOk(e.target.checked);
            setMade(false);
          }}
        />
        <span>I have the right to use this voice.</span>
      </label>
      <button
        type="button"
        aria-disabled={!ok}
        onClick={() => ok && setMade(true)}
        className="hx-gate-btn"
      >
        Create voice
      </button>
      <p role="status" className="mt-3 min-h-[1.25rem] font-mono text-xs text-muted-foreground">
        {made
          ? "Voice created (example). Your confirmation is kept with it."
          : ok
            ? "Unlocked. Press Create voice."
            : "Locked until you confirm."}
      </p>
    </div>
  );
}
