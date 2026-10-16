/** Delivery choices for POST /synthesize; the values are the backend's `emotion` literals. */
export const EMOTIONS = [
  { value: "auto", label: "Auto (from the text)" },
  { value: "neutral", label: "Neutral" },
  { value: "happy", label: "Happy" },
  { value: "sad", label: "Sad" },
  { value: "angry", label: "Angry" },
  { value: "fearful", label: "Fearful" },
  { value: "surprised", label: "Surprised" },
] as const;

export const DEFAULT_INTENSITY = 0.5;

/** The backend rejects an intensity for `auto` and `neutral`, so only send it for the others. */
export function intensityApplies(emotion: string): boolean {
  return emotion !== "auto" && emotion !== "neutral";
}
