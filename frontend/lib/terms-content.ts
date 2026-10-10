/**
 * The published terms page content. `TERMS_VERSION` must equal the backend's `TERMS_VERSION`
 * (`backend/core/config.py`); `tests/terms-page.test.tsx` fails when they differ, so the text
 * cannot change without the version a user consents to changing with it.
 *
 * Status: DRAFT. Every sentence below describes what the product does by construction (cited in
 * UX plan §11.3); none is a legal commitment drafted by the engineering team. Counsel replaces
 * `status` with "published" and reviews the wording before `TERMS_URL` is set.
 */
export const TERMS_VERSION = "2026-09-30";
export const TERMS_STATUS: "draft" | "published" = "draft";

export interface TermsSection {
  heading: string;
  body: string;
}

export const TERMS_SECTIONS: TermsSection[] = [
  {
    heading: "Only use voices you may use",
    body: "Before a voice sample is accepted you confirm that you have the right to use that voice. Do not clone a voice without the permission of the person it belongs to.",
  },
  {
    heading: "What is stored",
    body: "A voice sample and the voice profile made from it are kept until you delete the voice. Generated audio is kept for a limited time, shown in History; the text and date of each generation stay in your history after the audio expires.",
  },
  {
    heading: "Deleting your data",
    body: "Deleting a voice removes its audio, its voice profile and the speech generated with it. Deleting your account removes all of your data.",
  },
  {
    heading: "AI-generated speech",
    body: "Speech made with CloneVoice is labelled as AI-generated in the app. Do not present it as a real recording of a person.",
  },
];
