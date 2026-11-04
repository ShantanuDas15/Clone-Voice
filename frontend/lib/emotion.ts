/** Delivery choices for POST /synthesize; the values are the backend's `emotion` literals. */
export const EMOTIONS = [
  { value: "auto", label: "Auto (from the text)", chip: "Auto" },
  { value: "neutral", label: "Neutral", chip: "Neutral" },
  { value: "happy", label: "Happy", chip: "Happy" },
  { value: "sad", label: "Sad", chip: "Sad" },
  { value: "angry", label: "Angry", chip: "Angry" },
  { value: "fearful", label: "Fearful", chip: "Fearful" },
  { value: "surprised", label: "Surprised", chip: "Surprised" },
] as const;

export const DEFAULT_INTENSITY = 0.5;

/** The backend rejects an intensity for `auto` and `neutral`, so only send it for the others. */
export function intensityApplies(emotion: string): boolean {
  return emotion !== "auto" && emotion !== "neutral";
}
