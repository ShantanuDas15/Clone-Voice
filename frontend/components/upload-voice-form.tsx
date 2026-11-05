"use client";

import { getDraft, saveDraft } from "@/lib/draft";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AudioUploader } from "@/components/audio-uploader";
import { TextField } from "@/components/form-fields";
import { useFocusFirstInvalid } from "@/hooks/use-focus-first-invalid";
import { useDegraded } from "@/hooks/use-health";
import { useOnline } from "@/hooks/use-online";
import { PROFILES_KEY } from "@/hooks/use-voice-profiles";
import { fetchTerms } from "@/lib/api/terms";
import { type VoiceProfileUpload, uploadProfile } from "@/lib/api/voice";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";
import { detectRecordingSupport } from "@/lib/recording";
import { voiceNameSchema } from "@/lib/validation/audio";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { VoiceStage, type VoiceStageState } from "@/components/voice-stage";

// The recorder (MediaRecorder, permissions) loads only when someone chooses to record (§5.10).
const Recorder = dynamic(() => import("@/components/recorder").then((m) => m.Recorder), {
  ssr: false,
  loading: () => <p className="text-sm text-muted-foreground">Loading recorder…</p>,
});

type SampleMode = "file" | "record";
const SAMPLE_MODES: readonly SampleMode[] = ["file", "record"];

/** Copy for an upload failure, by kind (R3/R8). Network drops mid-upload usually mean a too-large body. */
export function uploadErrorMessage(e: ApiError): string {
  switch (e.kind) {
    case "EMAIL_UNVERIFIED":
      return "Please verify your email address before uploading a voice.";
    case "NETWORK":
      return "The upload was interrupted. The file may be too large, or your connection dropped. Check your voices below, then try again.";
    case "TIMEOUT":
      return "Analysing the voice took too long. Check your voices below before trying again.";
    case "RATE_LIMITED":
      return rateLimitMessage(e);
    case "BUSY":
      return "The service is busy analysing other voices. Please try again in a moment.";
    default:
      return e.message;
  }
}

function MicGlyph() {
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="currentColor"
    >
      <path d="M12 15a4 4 0 0 0 4-4V6a4 4 0 0 0-8 0v5a4 4 0 0 0 4 4Zm6-4a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.9V19H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-2.1A6 6 0 0 0 18 11Z" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg
      aria-hidden
      focusable="false"
      viewBox="0 0 16 16"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 11V3m0 0L5 6m3-3 3 3M3 13h10" />
    </svg>
  );
}

/** Create a voice profile: name, sample and an explicit, versioned consent attestation. */
export function UploadVoiceForm({ children }: { children?: ReactNode }) {
  const client = useQueryClient();
  const terms = useQuery({ queryKey: ["terms"], queryFn: fetchTerms, staleTime: 5 * 60_000 });
  const { user } = useAuth();
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string>();
  const [files, setFiles] = useState<File[]>([]);
  const [fileError, setFileError] = useState<string>();
  const [consent, setConsent] = useState(false);
  const [consentError, setConsentError] = useState<string>();
  const [adult, setAdult] = useState(false);
  const [adultError, setAdultError] = useState<string>();
  const [formError, setFormError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [created, setCreated] = useState<VoiceProfileUpload | null>(null);
  const [mode, setMode] = useState<SampleMode>("file");
  const [recorderKey, setRecorderKey] = useState(0);
  const [recordingUnavailable, setRecordingUnavailable] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [peaks, setPeaks] = useState<number[] | null>(null);
  const [lockedPeaks, setLockedPeaks] = useState<number[] | null>(null);
  const inFlight = useRef(false);
  const { ref: formRef, focusFirstInvalid } = useFocusFirstInvalid<HTMLFormElement>();

  // Feature-detect after mount (R10): the server render cannot know the browser's capabilities.
  useEffect(() => {
    const support = detectRecordingSupport();
    setRecordingUnavailable(support.supported ? null : support.reason);
  }, []);

  // The first clip's own shape, decoded in the browser for the stage (a nicety: no decode, no shape).
  useEffect(() => {
    setPeaks(null);
    const first = files[0];
    if (!first) return;
    let live = true;
    void import("@/lib/audio-peaks").then(async ({ computePeaks }) => {
      const result = await computePeaks(first, 64);
      if (live) setPeaks(result);
    });
    return () => {
      live = false;
    };
  }, [files]);

  const unverified = user !== null && !user.email_verified_at;
  // Restore this user's draft name once the session is known, then keep saving it (see
  // `lib/draft.ts`; consent is never kept).
  const draftReady = useRef<string | null>(null);
  useEffect(() => {
    if (!user || draftReady.current === user.id) return;
    draftReady.current = user.id;
    setName((n) => n || getDraft(user.id).voiceName);
  }, [user]);
  useEffect(() => {
    if (user && draftReady.current === user.id) saveDraft(user.id, { voiceName: name });
  }, [user, name]);
  const upload = useMutation({
    mutationFn: () =>
      uploadProfile(
        {
          name: voiceNameSchema.parse(name),
          files,
          termsVersion: terms.data?.version ?? null,
        },
        { onProgress: setProgress },
      ),
    retry: false, // R5: never auto-retry an upload
  });

  function selectMode(m: SampleMode) {
    setMode(m);
    setFiles([]);
    setFileError(undefined);
  }

  // U6.1: WAI-ARIA radio keyboard model: arrows move and select, Home/End jump, one tab stop.
  function onModeKeyDown(e: React.KeyboardEvent, current: SampleMode) {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    let next: SampleMode | undefined;
    if (step !== undefined) {
      const i = SAMPLE_MODES.indexOf(current);
      next = SAMPLE_MODES[(i + step + SAMPLE_MODES.length) % SAMPLE_MODES.length];
    } else if (e.key === "Home") next = SAMPLE_MODES[0];
    else if (e.key === "End") next = SAMPLE_MODES[SAMPLE_MODES.length - 1];
    if (!next) return;
    e.preventDefault();
    if (next !== current) selectMode(next);
    document.getElementById(`sample-mode-${next}`)?.focus();
  }

  // R9: warn before leaving while an upload/analysis is running.
  useEffect(() => {
    if (!upload.isPending) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [upload.isPending]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (inFlight.current) return; // R4
    setFormError(null);
    setCreated(null);
    const parsed = voiceNameSchema.safeParse(name);
    setNameError(parsed.success ? undefined : parsed.error.issues[0]?.message);
    setFileError(files.length > 0 ? undefined : "Choose an audio file");
    setConsentError(consent ? undefined : "Confirm you have the right to use this voice");
    setAdultError(adult ? undefined : "Confirm the speaker is 18 or older");
    if (!parsed.success || files.length === 0 || !consent || !adult) {
      focusFirstInvalid();
      return;
    }

    inFlight.current = true;
    setLockedPeaks(peaks);
    setProgress(0);
    try {
      const profile = await upload.mutateAsync();
      void client.invalidateQueries({ queryKey: PROFILES_KEY }); // show the new voice (found by e2e)
      setCreated(profile);
      setName("");
      setFiles([]);
      setRecorderKey((k) => k + 1); // a fresh recorder for the next voice
      setConsent(false);
      setAdult(false);
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      if (err.kind === "TERMS_CHANGED") {
        // The wording changed under the user: refetch it and ask for consent again.
        setConsent(false);
        setAdult(false);
        void client.invalidateQueries({ queryKey: ["terms"] });
        setFormError("The terms have changed. Please review them and confirm again.");
      } else if (err.status === 422 && err.fieldErrors.length > 0) {
        for (const fe of err.fieldErrors) {
          if (fe.field === "name") setNameError(fe.message);
          else if (fe.field === "file") setFileError(fe.message);
          else setFormError(fe.message);
        }
        focusFirstInvalid();
      } else setFormError(uploadErrorMessage(err));
      // Failed attempts can leave a `failed` profile behind (G-11): resync the list.
      void client.invalidateQueries({ queryKey: PROFILES_KEY });
    } finally {
      inFlight.current = false;
      setProgress(null);
    }
  }

  const pending = upload.isPending;
  const degraded = useDegraded();
  const online = useOnline();
  const blocker = !online ? "You're offline." : unverified ? "Verify your email first." : null;

  const stageState: VoiceStageState = created
    ? "created"
    : pending
      ? progress !== null && progress < 1
        ? "uploading"
        : "analysing"
      : "ready";

  return (
    <div className="bx-root" data-motion={paused ? "paused" : "on"}>
      <div aria-hidden className="bx-aurora">
        <i className="bx-a" />
        <i className="bx-b" />
      </div>
      <div className="grid gap-5 lg:grid-cols-[1.05fr_0.95fr] lg:items-start">
        <section aria-labelledby="new-voice" className="bx-card bx-glow">
          <h2 id="new-voice" className="mb-5 text-xl font-semibold">
            Create a voice
          </h2>
          <form
            ref={formRef}
            onSubmit={onSubmit}
            noValidate
            className="bx-form space-y-5"
            aria-label="Create a voice"
          >
            <TextField
              label="Voice name"
              name="voice-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={255}
              disabled={pending}
              error={nameError}
            />
            <fieldset className="space-y-3" disabled={pending}>
              <legend className="sr-only">Sample source</legend>
              {recordingUnavailable === null ? (
                <div role="radiogroup" aria-label="How to add a sample" className="bx-seg">
                  {SAMPLE_MODES.map((m) => (
                    <button
                      key={m}
                      id={`sample-mode-${m}`}
                      type="button"
                      role="radio"
                      aria-checked={mode === m}
                      tabIndex={mode === m ? 0 : -1}
                      onClick={() => selectMode(m)}
                      onKeyDown={(e) => onModeKeyDown(e, m)}
                      className="bx-seg-btn forced-colors:aria-checked:underline"
                    >
                      {m === "file" ? <UploadIcon /> : <MicGlyph />}
                      {m === "file" ? "Upload a file" : "Record now"}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">{recordingUnavailable}</p>
              )}
              {mode === "record" && recordingUnavailable === null ? (
                <>
                  <Recorder
                    key={recorderKey}
                    onChange={(f) => setFiles(f ? [f] : [])}
                    disabled={pending}
                  />
                  {fileError && <Alert tone="danger">{fileError}</Alert>}
                </>
              ) : (
                <AudioUploader
                  files={files}
                  onChange={setFiles}
                  disabled={pending}
                  error={fileError}
                />
              )}
              {files.length === 1 && (
                <p className="text-sm text-muted-foreground">
                  Tip: add 2 or 3 more clips of the same person. Voices made from several clips have
                  fewer garbled or missing words. You can also add them later under Clips.
                </p>
              )}
            </fieldset>

            <div>
              <label className="bx-seal">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                  disabled={pending}
                  aria-invalid={consentError ? true : undefined}
                  className="bx-seal-box"
                />
                <span>
                  I confirm I have the right to use this voice sample and will follow the
                  acceptable-use terms
                  {terms.data?.url && (
                    <>
                      {" "}
                      (version {terms.data.version},{" "}
                      <a
                        href={terms.data.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="underline"
                      >
                        read the terms
                      </a>
                      )
                    </>
                  )}
                  .
                </span>
              </label>
              <p className="mt-1 text-sm text-muted-foreground">
                Your sample is kept until you delete this voice.
                {terms.data && !terms.data.url && " Terms are being finalised."}
              </p>
              {consentError && (
                <Alert tone="danger" className="mt-1">
                  {consentError}
                </Alert>
              )}
            </div>

            <div>
              <label className="bx-seal">
                <input
                  type="checkbox"
                  checked={adult}
                  onChange={(e) => setAdult(e.target.checked)}
                  disabled={pending}
                  aria-invalid={adultError ? true : undefined}
                  className="bx-seal-box"
                />
                <span>I confirm the speaker is 18 or older.</span>
              </label>
              {adultError && (
                <Alert tone="danger" className="mt-1">
                  {adultError}
                </Alert>
              )}
            </div>

            {formError && <Alert tone="danger">{formError}</Alert>}
            {degraded && (
              <p id="upload-paused" role="status" className="text-sm">
                Uploading is paused while the service recovers. This page will update on its own.
              </p>
            )}
            <div className="bx-actions flex flex-wrap items-center gap-3">
              <Button
                type="submit"
                disabled={degraded || blocker !== null}
                aria-describedby={
                  [blocker && "upload-blocked", degraded && "upload-paused"]
                    .filter(Boolean)
                    .join(" ") || undefined
                }
                loading={pending}
              >
                {pending ? "Creating voice…" : "Create voice"}
              </Button>
              {blocker && (
                <p id="upload-blocked" className="text-sm text-muted-foreground">
                  {blocker}
                </p>
              )}
            </div>
          </form>
        </section>
        <div className="min-w-0 space-y-5">
          <VoiceStage
            state={stageState}
            progress={progress ?? 0}
            peaks={pending || created ? lockedPeaks : peaks}
            created={created}
          />
          {children}
        </div>
      </div>
      <div className="mt-2 flex justify-end">
        <button
          type="button"
          aria-pressed={paused}
          onClick={() => setPaused((p) => !p)}
          className="bx-motion"
        >
          {paused ? "Resume motion" : "Pause motion"}
        </button>
      </div>
    </div>
  );
}
