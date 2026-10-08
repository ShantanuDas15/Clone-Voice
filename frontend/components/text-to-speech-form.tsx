"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AudioPlayer } from "@/components/audio-player";
import { ResendVerification } from "@/components/resend-verification";
import { VoiceProfileSelect } from "@/components/voice-profile-select";
import { HISTORY_KEY, PROFILES_KEY } from "@/hooks/use-voice-profiles";
import { useDegraded } from "@/hooks/use-health";
import { useObjectUrl } from "@/hooks/use-object-url";
import { useCooldown, useElapsedSeconds } from "@/hooks/use-timers";
import { type SynthesisResult, synthesize } from "@/lib/api/synthesize";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { getDraft, saveDraft } from "@/lib/draft";
import { ApiError } from "@/lib/errors";
import { TEXT_MAX, hasLikelyUnsupportedChars, synthesisTextSchema } from "@/lib/validation/text";

const BUSY_COOLDOWN_S = 15; // no Retry-After on "service busy" (G-05)
const RATE_COOLDOWN_S = 60; // 5/min per IP

/** Message for a failed synthesis by kind (R3). Ambiguous failures never assume the job didn't run (R9). */
function errorMessage(e: ApiError): string {
  switch (e.kind) {
    case "NOT_FOUND":
      return "That voice no longer exists. Pick another one.";
    case "FORBIDDEN":
      return "You can't use that voice.";
    case "PROFILE_NOT_READY":
      return "That voice isn't ready. Pick another one or recreate it.";
    case "EMAIL_UNVERIFIED":
      return "Please verify your email address before generating speech.";
    case "RATE_LIMITED":
      return rateLimitMessage(e);
    case "BUSY":
      return "The service is busy. Please wait a moment and try again.";
    case "TIMEOUT":
    case "NETWORK":
      return "We lost contact before the audio arrived. It may still have been generated: check History before trying again.";
    default:
      return e.message;
  }
}

/** Pick a voice, enter text, generate, then play or download the result. */
export function TextToSpeechForm() {
  const { user } = useAuth();
  const client = useQueryClient();
  const initial = getDraft();
  const [voiceId, setVoiceId] = useState(initial.voiceId);
  const [text, setText] = useState(initial.text);
  const [textError, setTextError] = useState<string>();
  const [formError, setFormError] = useState<string | null>(null);
  const [result, setResult] = useState<(SynthesisResult & { text: string }) | null>(null);
  const controller = useRef<AbortController | null>(null);
  const inFlight = useRef(false);
  const cooldown = useCooldown();
  const degraded = useDegraded();

  const mutation = useMutation({
    mutationFn: (vars: { voiceId: string; text: string; signal: AbortSignal }) =>
      synthesize({ voiceProfileId: vars.voiceId, text: vars.text }, { signal: vars.signal }),
    retry: false, // R5
  });
  const pending = mutation.isPending;
  const elapsed = useElapsedSeconds(pending);
  const audioUrl = useObjectUrl(result?.blob ?? null);

  useEffect(() => saveDraft({ voiceId, text }), [voiceId, text]);

  // R9: warn before leaving mid-generation.
  useEffect(() => {
    if (!pending) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [pending]);

  // Abort the browser request when leaving the page/component.
  useEffect(() => () => controller.current?.abort(), []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (inFlight.current || cooldown.remaining > 0) return; // R4
    setFormError(null);
    const parsed = synthesisTextSchema.safeParse(text);
    setTextError(parsed.success ? undefined : parsed.error.issues[0]?.message);
    if (!voiceId) {
      setFormError("Choose a voice first.");
      return;
    }
    if (!parsed.success) return;

    inFlight.current = true;
    const ctl = new AbortController();
    controller.current = ctl;
    try {
      const out = await mutation.mutateAsync({ voiceId, text: parsed.data, signal: ctl.signal });
      setResult({ ...out, text: parsed.data }); // replaces (and so revokes) the previous blob
      void client.invalidateQueries({ queryKey: HISTORY_KEY });
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      if (err.kind === "CANCELLED") {
        // R7: the server may still finish, so the history can gain a row.
        setFormError(
          "Cancelled. If it had already started, the audio may still appear in History.",
        );
        void client.invalidateQueries({ queryKey: HISTORY_KEY });
        return;
      }
      const field = err.fieldErrors.find((f) => f.field === "text");
      if (err.status === 422 && field) setTextError(field.message);
      else setFormError(errorMessage(err));
      if (
        err.kind === "NOT_FOUND" ||
        err.kind === "PROFILE_NOT_READY" ||
        err.kind === "FORBIDDEN"
      ) {
        void client.invalidateQueries({ queryKey: PROFILES_KEY });
      }
      if (err.kind === "TIMEOUT" || err.kind === "NETWORK") {
        void client.invalidateQueries({ queryKey: HISTORY_KEY });
      }
      if (err.kind === "RATE_LIMITED") cooldown.start(err.retryAfterSec ?? RATE_COOLDOWN_S);
      if (err.kind === "BUSY") cooldown.start(err.retryAfterSec ?? BUSY_COOLDOWN_S);
    } finally {
      inFlight.current = false;
      controller.current = null;
    }
  }

  const unverified = user !== null && !user.email_verified_at;
  const warnChars = hasLikelyUnsupportedChars(text);

  return (
    <div className="space-y-6">
      <form
        onSubmit={onSubmit}
        noValidate
        className="max-w-xl space-y-4"
        aria-label="Generate speech"
      >
        {unverified && (
          <p className="text-sm">
            Verify your email address to generate speech. <ResendVerification />
          </p>
        )}
        <VoiceProfileSelect value={voiceId} onChange={setVoiceId} disabled={pending} />

        <div>
          <label htmlFor="tts-text" className="block text-sm font-medium">
            Text
          </label>
          <textarea
            id="tts-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={TEXT_MAX}
            rows={5}
            disabled={pending}
            aria-invalid={textError ? true : undefined}
            aria-describedby="tts-count tts-hint"
            className="mt-1 block w-full rounded border border-line bg-surface px-3 py-2"
          />
          <p
            id="tts-count"
            className="mt-1 text-right font-mono text-xs tabular-nums text-muted-foreground"
          >
            {text.length} / {TEXT_MAX}
          </p>
          <p id="tts-hint" className="text-xs text-muted-foreground">
            Plain text works best: letters, numbers and basic punctuation.
          </p>
          {warnChars && (
            <p role="status" className="mt-1 text-sm">
              Emoji and symbols can&apos;t be spoken and will be rejected.
            </p>
          )}
          {textError && (
            <p role="alert" className="mt-1 text-sm text-danger">
              {textError}
            </p>
          )}
        </div>

        {pending && (
          <div role="status" aria-live="polite" className="text-sm">
            Generating… {elapsed} s. This can take a minute or more on slow servers; please keep
            this page open.
          </div>
        )}
        {formError && (
          <p role="alert" className="text-sm text-danger">
            {formError}
          </p>
        )}
        {degraded && (
          <p role="status" className="text-sm">
            Generating is paused while the service recovers. This page will update on its own.
          </p>
        )}
        {cooldown.remaining > 0 && (
          <p role="status" className="text-sm">
            You can try again in {cooldown.remaining} s.
          </p>
        )}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={pending || degraded || cooldown.remaining > 0}
            className="min-h-11 rounded bg-primary px-4 py-2 text-primary-foreground disabled:opacity-60"
          >
            {pending ? "Generating…" : "Generate speech"}
          </button>
          {pending && (
            <button
              type="button"
              onClick={() => controller.current?.abort()}
              className="min-h-11 rounded border border-line px-4"
            >
              Cancel
            </button>
          )}
        </div>
      </form>

      {result && audioUrl && (
        <section
          aria-labelledby="result-title"
          className="max-w-xl space-y-2 rounded border border-border p-4"
        >
          <h2 id="result-title" className="font-medium">
            Your audio{" "}
            <span className="text-sm font-normal text-muted-foreground">(AI-generated voice)</span>
          </h2>
          <p className="text-sm text-muted-foreground">“{result.text}”</p>
          <AudioPlayer src={audioUrl} filename={result.filename} label="Generated speech" />
          <p className="text-xs text-muted-foreground">
            If you leave this page, find past audio in History.
          </p>
        </section>
      )}
    </div>
  );
}
