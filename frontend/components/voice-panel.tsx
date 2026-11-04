import { VoiceState, Wave } from "@/components/voice-wave";

/** Words for the panel beside a sign-in or sign-up form. */
export interface PanelCopy {
  /** The first, plain part of the headline. */
  headline: string;
  /** The second part, in the accent colour. */
  accent: string;
  lead: string;
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
      className="relative hidden min-w-0 flex-col justify-between gap-8 py-2 lg:flex"
    >
      <Glow />
      <div className="relative">
        <p className="flex items-center gap-2.5 font-mono text-sm text-muted-foreground">
          <span className="size-2 rounded-full bg-primary" />
          Voice cloning, with consent
        </p>
        <p className="mt-3 text-balance text-5xl font-bold leading-[1.05] tracking-tight">
          {copy.headline} <span className="text-primary">{copy.accent}</span>
        </p>
        <p className="mt-4 max-w-md text-lg text-muted-foreground">{copy.lead}</p>
      </div>
      <div className="relative">
        <Wave count={56} className="h-56 w-full" />
        <p
          data-testid="voice-state"
          className="mt-3 border-t border-border pt-2 font-mono text-xs text-muted-foreground"
        >
          voiceprint · <VoiceState />
        </p>
      </div>
      <dl className="relative space-y-3 text-sm">
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

/**
 * A still teal glow behind the wave: three stacked, very faint discs. The flat style (UX plan §4)
 * keeps surfaces flat, so the soft edge comes from the stacking. Never animates.
 */
function Glow() {
  return (
    <div
      data-testid="voice-glow"
      className="pointer-events-none absolute -left-24 top-1/4 -z-10 size-[34rem] max-w-none"
    >
      <span className="absolute inset-0 rounded-full bg-primary/[0.03]" />
      <span className="absolute inset-12 rounded-full bg-primary/[0.04]" />
      <span className="absolute inset-24 rounded-full bg-primary/[0.05]" />
    </div>
  );
}
