import { drawDelay } from "@/lib/home-backdrop";
import { panelBars } from "@/lib/auth-panel";

/** Words for the panel beside a sign-in or sign-up form. */
export interface PanelCopy {
  /** The first, plain part of the headline. */
  headline: string;
  /** The second part, in the accent colour. */
  accent: string;
  lead: string;
}

/**
 * One row of voice bars, drawn once, left to right, and then still. Presentation attributes and
 * classes only: the site's Content-Security-Policy forbids inline styles. `motion-safe` keeps the
 * draw-in off under `prefers-reduced-motion`, which shows the finished row at once. Decorative.
 */
function Wave({ count, className }: { count: number; className: string }) {
  const bars = panelBars(count);
  return (
    <svg
      aria-hidden
      focusable="false"
      data-testid="voice-wave"
      viewBox={`0 0 ${count * 8} 100`}
      preserveAspectRatio="none"
      className={className}
    >
      {bars.map((bar, i) => {
        const h = bar.height * 100;
        return (
          <rect
            key={i}
            x={i * 8 + 1}
            y={50 - h / 2}
            width={6}
            height={h}
            rx={3}
            className={`origin-center [transform-box:fill-box] motion-safe:animate-bar-in ${drawDelay(i, 4)} ${
              bar.accent ? "fill-primary" : "fill-line/60"
            }`}
          />
        );
      })}
    </svg>
  );
}

/** The thin version of the wave that sits above the card on screens too narrow for the panel. */
export function VoiceStrip() {
  return <Wave count={44} className="mb-6 h-11 w-full lg:hidden" />;
}

const PROMISES: ReadonlyArray<readonly [string, string]> = [
  ["Consent first", "A voice can only be created once you confirm the right to use it."],
  ["Deleting is complete", "Delete a voice and everything made with it is erased."],
  ["Always labelled", "Generated speech is marked AI-generated in the app."],
];

/**
 * The left half of the sign-in and sign-up screens from `lg` up: a quiet voice panel with one wave
 * and the product's three promises (the same ones the home page makes). It repeats what other pages
 * say and carries no controls, so it is hidden from assistive technology; the form is the page.
 */
export function VoicePanel({ copy }: { copy: PanelCopy }) {
  return (
    <aside
      aria-hidden
      data-testid="voice-panel"
      className="hidden min-w-0 flex-col justify-between gap-8 py-2 lg:flex"
    >
      <div>
        <p className="font-mono text-sm text-muted-foreground">Voice cloning, with consent</p>
        <p className="mt-2 text-balance text-4xl font-semibold leading-[1.1] tracking-tight">
          {copy.headline} <span className="text-primary">{copy.accent}</span>
        </p>
        <p className="mt-4 max-w-md text-muted-foreground">{copy.lead}</p>
      </div>
      <Wave count={56} className="h-56 w-full" />
      <dl className="space-y-3 border-t border-border pt-5 text-sm">
        {PROMISES.map(([term, detail]) => (
          <div key={term} className="grid grid-cols-[9.5rem_1fr] gap-3">
            <dt className="font-medium">{term}</dt>
            <dd className="text-muted-foreground">{detail}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}
