"use client";

import { useEffect, useRef, useState } from "react";

const ITEMS = [
  ["Voice profile", "1 clip"],
  ["Take: “Welcome back to the show…”", "0:07"],
  ["Take: “Your appointment is confirmed…”", "0:04"],
  ["Take: “Chapter three…”", "0:06"],
] as const;

/**
 * The deletion promise you can try (owner-approved mock): press Delete and the example voice and
 * everything made with it fade out. It mirrors the real behaviour, where deleting a voice erases its
 * takes too. Nothing is sent anywhere; Start over puts the example back.
 */
export function HomeEraseDemo() {
  const [gone, setGone] = useState(0);
  const [running, setRunning] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  useEffect(() => () => clearInterval(timer.current), []);

  function erase() {
    setRunning(true);
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return setGone(ITEMS.length);
    timer.current = setInterval(() => {
      setGone((g) => {
        if (g + 1 >= ITEMS.length) clearInterval(timer.current);
        return g + 1;
      });
    }, 260);
  }

  function reset() {
    clearInterval(timer.current);
    setGone(0);
    setRunning(false);
  }

  const done = gone >= ITEMS.length;
  return (
    <div className="hx-card" data-testid="erase-demo">
      <h3 className="font-semibold">My voice</h3>
      <p className="text-sm text-muted-foreground">
        An example voice and what was made with it. Nothing is deleted.
      </p>
      <ul className="hx-items">
        {ITEMS.map(([label, meta], i) => (
          // Items go from the last to the first, as the takes then the voice.
          <li key={label} className={ITEMS.length - 1 - i < gone ? "hx-gone" : ""}>
            <span>{label}</span>
            <small>{meta}</small>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" onClick={erase} disabled={running} className="hx-danger">
          Delete voice
        </button>
        {done ? (
          <button type="button" onClick={reset} className="hx-link">
            Start over
          </button>
        ) : null}
      </div>
      <p role="status" className="mt-3 min-h-[1.25rem] font-mono text-xs text-muted-foreground">
        {done ? "Voice and 3 takes erased (example)." : ""}
      </p>
    </div>
  );
}
