/** Where a new user is on the way to a first generated take (UX plan §5.3). */
export type StepStatus = "done" | "current" | "todo";

export interface FirstRun {
  verify: StepStatus;
  voice: StepStatus;
  generate: StepStatus;
  /** Why Generate cannot be used yet, in the user's words; null when it can. */
  blocker: string | null;
}

/** Derive the checklist and the Generate blocker from two facts. The first unmet step is current. */
export function firstRun(input: { emailVerified: boolean; hasReadyVoice: boolean }): FirstRun {
  const verify: StepStatus = input.emailVerified ? "done" : "current";
  const voice: StepStatus = input.hasReadyVoice ? "done" : input.emailVerified ? "current" : "todo";
  const ready = input.emailVerified && input.hasReadyVoice;
  return {
    verify,
    voice,
    generate: ready ? "current" : "todo",
    blocker: !input.emailVerified
      ? "Verify your email first."
      : !input.hasReadyVoice
        ? "Create a voice first."
        : null,
  };
}
