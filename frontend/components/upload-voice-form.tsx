"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AudioUploader } from "@/components/audio-uploader";
import { TextField } from "@/components/form-fields";
import { ResendVerification } from "@/components/resend-verification";
import { useDegraded } from "@/hooks/use-health";
import { PROFILES_KEY } from "@/hooks/use-voice-profiles";
import { fetchTerms } from "@/lib/api/terms";
import { uploadProfile } from "@/lib/api/voice";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { ApiError } from "@/lib/errors";
import { detectRecordingSupport } from "@/lib/recording";
import { voiceNameSchema } from "@/lib/validation/audio";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";

// The recorder (MediaRecorder, permissions) loads only when someone chooses to record (§5.10).
const Recorder = dynamic(() => import("@/components/recorder").then((m) => m.Recorder), {
  ssr: false,
  loading: () => <p className="text-sm text-muted-foreground">Loading recorder…</p>,
});

type SampleMode = "file" | "record";

/** Copy for an upload failure, by kind (R3/R8). Network drops mid-upload usually mean a too-large body. */
function uploadErrorMessage(e: ApiError): string {
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

/** Create a voice profile: name, sample and an explicit, versioned consent attestation. */
export function UploadVoiceForm() {
  const { user } = useAuth();
  const client = useQueryClient();
  const terms = useQuery({ queryKey: ["terms"], queryFn: fetchTerms, staleTime: 5 * 60_000 });
  const [name, setName] = useState("");
  const [nameError, setNameError] = useState<string>();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string>();
  const [consent, setConsent] = useState(false);
  const [consentError, setConsentError] = useState<string>();
  const [formError, setFormError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [mode, setMode] = useState<SampleMode>("file");
  const [recorderKey, setRecorderKey] = useState(0);
  const [recordingUnavailable, setRecordingUnavailable] = useState<string | null>(null);
  const inFlight = useRef(false);

  // Feature-detect after mount (R10): the server render cannot know the browser's capabilities.
  useEffect(() => {
    const support = detectRecordingSupport();
    setRecordingUnavailable(support.supported ? null : support.reason);
  }, []);

  const upload = useMutation({
    mutationFn: () =>
      uploadProfile(
        {
          name: voiceNameSchema.parse(name),
          file: file as File,
          termsVersion: terms.data?.version ?? null,
        },
        { onProgress: setProgress },
      ),
    retry: false, // R5: never auto-retry an upload
  });

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
    setFileError(file ? undefined : "Choose an audio file");
    setConsentError(consent ? undefined : "Confirm you have the right to use this voice");
    if (!parsed.success || !file || !consent) return;

    inFlight.current = true;
    setProgress(0);
    try {
      const profile = await upload.mutateAsync();
      void client.invalidateQueries({ queryKey: PROFILES_KEY }); // show the new voice (found by e2e)
      setCreated(profile.name);
      setName("");
      setFile(null);
      setRecorderKey((k) => k + 1); // a fresh recorder for the next voice
      setConsent(false);
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      if (err.kind === "TERMS_CHANGED") {
        // The wording changed under the user: refetch it and ask for consent again.
        setConsent(false);
        void client.invalidateQueries({ queryKey: ["terms"] });
        setFormError("The terms have changed. Please review them and confirm again.");
      } else if (err.status === 422 && err.fieldErrors.length > 0) {
        for (const fe of err.fieldErrors) {
          if (fe.field === "name") setNameError(fe.message);
          else if (fe.field === "file") setFileError(fe.message);
          else setFormError(fe.message);
        }
      } else setFormError(uploadErrorMessage(err));
      // Failed attempts can leave a `failed` profile behind (G-11): resync the list.
      void client.invalidateQueries({ queryKey: PROFILES_KEY });
    } finally {
      inFlight.current = false;
      setProgress(null);
    }
  }

  const unverified = user !== null && !user.email_verified_at;
  const pending = upload.isPending;
  const degraded = useDegraded();

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-4" aria-label="Create a voice">
      {unverified && (
        <p className="text-sm">
          Verify your email address to upload a voice. <ResendVerification />
        </p>
      )}
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
          <div role="radiogroup" aria-label="How to add a sample" className="flex gap-2 text-sm">
            {(["file", "record"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => {
                  setMode(m);
                  setFile(null);
                  setFileError(undefined);
                }}
                className={`min-h-11 rounded border px-4 ${mode === m ? "border-primary bg-muted font-medium" : "border-line"}`}
              >
                {m === "file" ? "Upload a file" : "Record now"}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{recordingUnavailable}</p>
        )}
        {mode === "record" && recordingUnavailable === null ? (
          <>
            <Recorder key={recorderKey} onChange={setFile} disabled={pending} />
            {fileError && <Alert tone="danger">{fileError}</Alert>}
          </>
        ) : (
          <AudioUploader file={file} onChange={setFile} disabled={pending} error={fileError} />
        )}
      </fieldset>

      <div>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            disabled={pending}
            className="mt-1 h-4 w-4"
          />
          <span>
            I confirm I have the right to use this voice sample and will follow the acceptable-use
            terms
            {terms.data && (
              <>
                {" "}
                (version {terms.data.version}
                {terms.data.url ? (
                  <>
                    ,{" "}
                    <a
                      href={terms.data.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      read the terms
                    </a>
                  </>
                ) : (
                  <>; the full terms page is not published yet</>
                )}
                )
              </>
            )}
            .
          </span>
        </label>
        {consentError && (
          <Alert tone="danger" className="mt-1">
            {consentError}
          </Alert>
        )}
      </div>

      {pending && (
        <div role="status" aria-live="polite" className="text-sm">
          {progress !== null && progress < 1 ? (
            <>
              <progress value={progress} max={1} className="w-full" aria-label="Upload progress" />
              <span>Uploading… {Math.round(progress * 100)}%</span>
            </>
          ) : (
            <span>Analysing the voice. This can take a minute; please keep this page open.</span>
          )}
        </div>
      )}
      {formError && <Alert tone="danger">{formError}</Alert>}
      {created && (
        <p role="status" className="text-sm">
          Voice “{created}” created.
        </p>
      )}
      {degraded && (
        <p role="status" className="text-sm">
          Uploading is paused while the service recovers. This page will update on its own.
        </p>
      )}
      <Button type="submit" disabled={pending || degraded} loading={pending}>
        {pending ? "Working…" : "Create voice"}
      </Button>
    </form>
  );
}
