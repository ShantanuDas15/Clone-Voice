/**
 * In-memory draft of the generate form so the user's voice and text survive a mid-flow
 * redirect to /login and back (R2). Deliberately not persisted: text is private (R16).
 */
export interface SynthesisDraft {
  voiceId: string;
  text: string;
}

let draft: SynthesisDraft = { voiceId: "", text: "" };

export function getDraft(): SynthesisDraft {
  return draft;
}

export function saveDraft(next: Partial<SynthesisDraft>): void {
  draft = { ...draft, ...next };
}

export function clearDraft(): void {
  draft = { voiceId: "", text: "" };
}
