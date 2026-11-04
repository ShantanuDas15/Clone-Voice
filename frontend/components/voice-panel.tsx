import { VoiceCanvas } from "@/components/voice-canvas";
import { TypedLine, VoiceState, Wave } from "@/components/voice-wave";

/** Words for the panel beside a sign-in or sign-up form. */
export interface PanelCopy {
  /** The first, plain part of the headline. */
  headline: string;
  /** The second part, in the accent colour. */
  accent: string;
  /** Other second lines to type out in turn after `accent` (sign-in only). */
  phrases?: readonly string[];
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
      className="hidden min-w-0 flex-col justify-between gap-8 py-2 lg:flex"
    >
      <div>
        <p className="flex items-center gap-2.5 font-mono text-sm text-muted-foreground">
          <span className="vx-dot" />
          Voice cloning, with consent
        </p>
        <p className="mt-4 text-balance text-6xl font-bold leading-[1.04] tracking-tight">
          {copy.headline} <TypedLine phrases={[copy.accent, ...(copy.phrases ?? [])]} />
        </p>
        <p className="mt-4 max-w-[46ch] text-lg text-muted-foreground">{copy.lead}</p>
      </div>
      <div>
        <VoiceCanvas className="h-52 w-full" />
        <p
          data-testid="voice-state"
          className="mt-3 flex flex-wrap justify-between gap-x-3 border-t border-border pt-2.5 font-mono text-xs text-muted-foreground"
        >
          <span>
            voiceprint · <VoiceState />
          </span>
          <span>private to your account</span>
        </p>
      </div>
      <dl className="grid grid-cols-3 gap-5 text-sm">
        {PROMISES.map(([term, detail]) => (
          <div key={term}>
            <dt className="font-semibold">{term}</dt>
            <dd className="text-muted-foreground">{detail}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}
