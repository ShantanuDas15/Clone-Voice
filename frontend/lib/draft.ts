/**
 * In-memory drafts so a user's work survives an expired session: redirect to /login and back (R2).
 * Never persisted (text is private, R16) and tagged with the owner's user id: a different user
 * signing in on the same tab sees nothing, and a deliberate sign-out clears it (`clearDraft`).
 * Consent is deliberately not kept; it must be confirmed again.
 */
export interface Draft {
  voiceId: string;
  text: string;
  voiceName: string;
}

const EMPTY: Draft = { voiceId: "", text: "", voiceName: "" };

let owner: string | null = null;
let draft: Draft = EMPTY;

/** The draft saved by `userId`, or an empty one when it belongs to someone else. */
export function getDraft(userId: string | undefined): Draft {
  return userId !== undefined && owner === userId ? draft : EMPTY;
}

/** Merge `next` into the draft for `userId`; another user's draft is discarded first. */
export function saveDraft(userId: string | undefined, next: Partial<Draft>): void {
  if (userId === undefined) return;
  if (owner !== userId) draft = EMPTY;
  owner = userId;
  draft = { ...draft, ...next };
}

export function clearDraft(): void {
  owner = null;
  draft = EMPTY;
}
