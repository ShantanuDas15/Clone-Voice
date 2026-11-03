/**
 * The clip the home page plays (UX plan §12.19). It is the site owner's own voice, used with their
 * consent: made by the app's own SV2TTS pipeline (preprocess, embed, synthesize, vocode, level and
 * watermark) from an 8-second recording that is not in the repository. `text` is what the clip says;
 * the file was checked by speech-to-text to say exactly this. Replace the three together.
 */
export interface HomeSample {
  /** Public path of the WAV. Loaded only when the visitor presses Play (`preload="none"`). */
  src: string;
  /** What the clip says, shown as the quote. */
  text: string;
  /** Length in seconds, so the clock reads right before any audio is fetched. */
  durationSeconds: number;
  /** Bar heights 0..100 of the clip (the backend's `compute_waveform_peaks`), so it can be drawn unplayed. */
  peaks: readonly number[];
  /** Where the voice came from, in a short factual line. */
  note: string;
}

export const HOME_SAMPLE: HomeSample | null = {
  src: "/samples/home-sample.wav",
  text: "Hello, this is a voice made from a short sample.",
  durationSeconds: 2.9,
  peaks: [
    33, 51, 98, 100, 83, 72, 80, 97, 51, 47, 26, 14, 17, 2, 2, 2, 48, 34, 23, 19, 53, 97, 46, 87,
    56, 59, 89, 93, 94, 54, 21, 8, 6, 30, 48, 37, 24, 18, 12, 3, 4, 7, 41, 24, 26, 25, 8, 6, 7, 60,
    57, 40, 10, 8, 6, 34, 37, 37, 14, 6, 19, 3, 2, 1,
  ],
  note: "Cloned from an 8-second recording, with the speaker's consent.",
};
