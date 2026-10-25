"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ExpandableText } from "@/components/expandable-text";
import { Take } from "@/components/take";
import { useAuth } from "@/components/auth-provider";
import { VoiceProfileSelect } from "@/components/voice-profile-select";
import { HISTORY_KEY, PROFILES_KEY, useProfiles } from "@/hooks/use-voice-profiles";
import { useCapabilities } from "@/hooks/use-capabilities";
import { useFocusFirstInvalid } from "@/hooks/use-focus-first-invalid";
import { useDegraded } from "@/hooks/use-health";
import { useOnline } from "@/hooks/use-online";
import { useObjectUrl } from "@/hooks/use-object-url";
import { useCooldown, useElapsedSeconds } from "@/hooks/use-timers";
import { type SynthesisInput, type SynthesisResult, synthesize } from "@/lib/api/synthesize";
import { rateLimitMessage } from "@/lib/auth/form-errors";
import { getDraft, saveDraft } from "@/lib/draft";
import { ApiError } from "@/lib/errors";
import { describeEngine } from "@/lib/engine-names";
import { firstRun } from "@/lib/first-run";
import {
  TEXT_MAX,
  countWords,
  hasLikelyUnsupportedChars,
  synthesisTextSchema,
} from "@/lib/validation/text";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { Select, Textarea } from "@/components/ui/field";
import { EMOTIONS, DEFAULT_INTENSITY, intensityApplies } from "@/lib/emotion";

const BUSY_COOLDOWN_S = 15; // no Retry-After on "service busy" (G-05)
const RATE_COOLDOWN_S = 60; // 5/min per IP
const QUOTE_PREVIEW_CHARS = 160; // the result card quotes the text; long text is cut

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
export function TextToSpeechForm({ initialVoiceId }: { initialVoiceId?: string }) {
  const { user } = useAuth();
  const profiles = useProfiles();
  const client = useQueryClient();
  const [voiceId, setVoiceId] = useState(initialVoiceId ?? "");
  const [text, setText] = useState("");
  const [emotion, setEmotion] = useState("auto");
  const [intensity, setIntensity] = useState(DEFAULT_INTENSITY);
  const [textError, setTextError] = useState<string>();
  const [formError, setFormError] = useState<string | null>(null);
  const [result, setResult] = useState<(SynthesisResult & { text: string }) | null>(null);
  const engineNote = result ? describeEngine(result.engine, result.engineFallbackFrom) : null;
  const controller = useRef<AbortController | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const { ref: formRef, focusFirstInvalid } = useFocusFirstInvalid<HTMLFormElement>();
  const resultRef = useRef<HTMLElement>(null);
  const inFlight = useRef(false);
  const autoPicked = useRef(false);
  const [announcement, setAnnouncement] = useState("");
  const cooldown = useCooldown();
  const degraded = useDegraded();
  const capabilities = useCapabilities();
  const showDelivery = capabilities.data?.emotion_control === true;
  const online = useOnline();

  const mutation = useMutation({
    mutationFn: (vars: SynthesisInput & { signal: AbortSignal }) =>
      synthesize(vars, { signal: vars.signal }),
    retry: false, // R5
  });
  const pending = mutation.isPending;
  const elapsed = useElapsedSeconds(pending);
  const audioUrl = useObjectUrl(result?.blob ?? null);

  // Restore this user's draft once the session is known (it is empty for anyone else), and only
  // then start saving, so the empty initial state never overwrites it.
  const draftReady = useRef<string | null>(null);
  useEffect(() => {
    if (!user || draftReady.current === user.id) return;
    draftReady.current = user.id;
    const saved = getDraft(user.id);
    setVoiceId((v) => v || saved.voiceId);
    setText((t) => t || saved.text);
  }, [user]);
  useEffect(() => {
    if (user && draftReady.current === user.id) saveDraft(user.id, { voiceId, text });
  }, [user, voiceId, text]);

  // A preselected or remembered voice that is gone (deleted, or not ready) must not linger as an
  // invisible selection: clear it once the list is known.
  useEffect(() => {
    if (!voiceId || !profiles.data) return;
    if (!profiles.data.some((p) => p.id === voiceId && p.status === "ready")) setVoiceId("");
  }, [voiceId, profiles.data]);

  // One ready voice is the only choice: select it, once, unless a voice is already chosen.
  useEffect(() => {
    if (autoPicked.current || !profiles.data || !user || draftReady.current !== user.id) return;
    autoPicked.current = true;
    const ready = profiles.data.filter((p) => p.status === "ready");
    const only = ready.length === 1 ? ready[0] : undefined;
    if (only) setVoiceId((v) => v || only.id);
  }, [profiles.data, user]);

  // A finished take can land below the fold on a phone: bring it into view (no-op when visible).
  useEffect(() => {
    if (!result) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    resultRef.current?.scrollIntoView?.({
      block: "nearest",
      behavior: reduced ? "auto" : "smooth",
    });
  }, [result]);

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

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    void run(text);
  }

  async function run(source: string) {
    if (inFlight.current || cooldown.remaining > 0) return; // R4
    setFormError(null);
    setAnnouncement(""); // cleared first, so the same message is announced again next time
    const parsed = synthesisTextSchema.safeParse(source);
    setTextError(parsed.success ? undefined : parsed.error.issues[0]?.message);
    if (!parsed.success) focusFirstInvalid();
    if (!voiceId) {
      setFormError("Choose a voice first.");
      return;
    }
    if (!parsed.success) return;

    inFlight.current = true;
    const ctl = new AbortController();
    controller.current = ctl;
    try {
      const out = await mutation.mutateAsync({
        voiceProfileId: voiceId,
        text: parsed.data,
        emotion: showDelivery ? emotion : undefined,
        intensity: showDelivery && intensityApplies(emotion) ? intensity : undefined,
        signal: ctl.signal,
      });
      setResult({ ...out, text: parsed.data }); // replaces (and so revokes) the previous blob
      setAnnouncement("Your audio is ready.");
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
      if (err.status === 422 && field) {
        setTextError(field.message);
        focusFirstInvalid();
      } else {
        // The cooldown line below counts the wait down, so the message only says why.
        setFormError(
          err.kind === "RATE_LIMITED" ? "You've sent too many requests." : errorMessage(err),
        );
      }
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
      // Generate is about to be disabled for the cooldown; keep focus somewhere useful.
      if (err.kind === "RATE_LIMITED" || err.kind === "BUSY") textRef.current?.focus();
    } finally {
      inFlight.current = false;
      controller.current = null;
    }
  }

  const warnChars = hasLikelyUnsupportedChars(text);
  const over = text.trim().length - TEXT_MAX; // > 0: that many characters too many
  // The server's speed-based limit (S3.5i); an estimate, so it warns but never blocks.
  const maxWords = capabilities.data?.max_words ?? null;
  const words = maxWords != null ? countWords(text) : 0;
  const overWords = maxWords != null && words > maxWords;

  // Why Generate is unavailable, shown next to the button (UR4). While the list loads we don't
  // block; the server still enforces both rules.
  const steps =
    user && !profiles.isPending
      ? firstRun({
          emailVerified: Boolean(user.email_verified_at),
          hasReadyVoice: (profiles.data ?? []).some((p) => p.status === "ready"),
        })
      : null;
  const blocker = !online ? "You're offline." : (steps?.blocker ?? null);
  const stepsBelow = online && steps?.blocker != null; // the checklist under the form has them
  // UR4: every visible reason the generate buttons are disabled is linked to them.
  const whyDisabled =
    [blocker && "tts-blocked", degraded && "tts-paused", cooldown.remaining > 0 && "tts-cooldown"]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <div className="grid gap-8 lg:grid-cols-2 lg:items-start">
      <form
        ref={formRef}
        onSubmit={onSubmit}
        noValidate
        className="max-w-xl space-y-4"
        aria-label="Generate speech"
      >
        <VoiceProfileSelect value={voiceId} onChange={setVoiceId} disabled={pending} />

        <div>
          <label htmlFor="tts-text" className="block text-sm font-medium">
            Text
          </label>
          <Textarea
            id="tts-text"
            ref={textRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={5}
            readOnly={pending} // stays selectable and copyable while generating
            className="read-only:bg-muted"
            aria-invalid={textError || over > 0 ? true : undefined}
            aria-describedby={`tts-count tts-hint${over > 0 ? " tts-over" : ""}${overWords ? " tts-words" : ""}`}
          />
          <p
            id="tts-count"
            className={`mt-1 text-right font-mono text-xs tabular-nums ${over > 0 || overWords ? "font-semibold text-danger" : "text-muted-foreground"}`}
          >
            {text.length} / {TEXT_MAX}
            {over > 0 && ` (${over} too many)`}
            {maxWords != null && ` · ${words} / about ${maxWords} words`}
          </p>
          {overWords && over <= 0 && (
            <Alert tone="neutral" id="tts-words" className="mt-1">
              This server speaks about {maxWords} words at a time, so this may be refused. Shorten
              it or split it into parts.
            </Alert>
          )}
          {over > 0 && (
            <Alert tone="danger" id="tts-over" className="mt-1">
              That&apos;s over the {TEXT_MAX}-character limit. Shorten the text to generate it.
            </Alert>
          )}
          <p id="tts-hint" className="text-xs text-muted-foreground">
            Plain text works best: letters, numbers and basic punctuation.
          </p>
          {warnChars && (
            <p role="status" className="mt-1 text-sm">
              Emoji and symbols can&apos;t be spoken and will be rejected.
            </p>
          )}
          {textError && (
            <Alert tone="danger" className="mt-1">
              {textError}
            </Alert>
          )}
        </div>

        {showDelivery && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="tts-emotion" className="block text-sm font-medium">
                Delivery
              </label>
              <Select
                id="tts-emotion"
                value={emotion}
                onChange={(e) => setEmotion(e.target.value)}
                disabled={pending}
                aria-describedby="tts-emotion-hint"
              >
                {EMOTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <label htmlFor="tts-intensity" className="block text-sm font-medium">
                Strength{" "}
                {intensityApplies(emotion) ? (
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {Math.round(intensity * 100)}%
                  </span>
                ) : (
                  <span className="text-xs font-normal text-muted-foreground">
                    (choose a delivery to adjust)
                  </span>
                )}
              </label>
              <input
                id="tts-intensity"
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={intensity}
                onChange={(e) => setIntensity(Number(e.target.value))}
                disabled={pending || !intensityApplies(emotion)}
                aria-describedby="tts-emotion-hint"
                className="range mt-1 block min-h-11 w-full disabled:opacity-60"
              />
            </div>
            <p id="tts-emotion-hint" className="text-xs text-muted-foreground sm:col-span-2">
              Auto picks the delivery from your text. Choose one to apply it to every sentence; the
              strength applies only to a named emotion.
            </p>
          </div>
        )}

        {showDelivery && (
          <details className="text-sm">
            <summary className="min-h-11 cursor-pointer py-2 underline underline-offset-2">
              Tips for expressive speech
            </summary>
            <div className="space-y-2 pb-2 text-muted-foreground">
              <p>
                Set the delivery for part of the text by wrapping it in a tag, for example{" "}
                <code className="font-mono">[happy]Great news![/happy]</code>. The tags are{" "}
                <code className="font-mono">neutral</code>, <code className="font-mono">happy</code>
                , <code className="font-mono">sad</code>, <code className="font-mono">angry</code>,{" "}
                <code className="font-mono">fearful</code> and{" "}
                <code className="font-mono">surprised</code>.
              </p>
              <p>
                Some voice engines can also make a sound where you write{" "}
                <code className="font-mono">[laugh]</code>,{" "}
                <code className="font-mono">[chuckle]</code> or{" "}
                <code className="font-mono">[cough]</code>. Where one can&apos;t, the sound is left
                out and you are told.
              </p>
            </div>
          </details>
        )}

        <span role="status" aria-live="polite" className="sr-only">
          {announcement}
        </span>

        {pending && (
          <div role="status" aria-live="polite" className="space-y-2 text-sm">
            <p>
              Generating…{" "}
              {/* Hidden from assistive tech so the ticking seconds are not announced every second. */}
              <span aria-hidden className="font-mono tabular-nums">
                {elapsed} s
              </span>
            </p>
            <p className="text-muted-foreground">
              This can take a minute or more on slow servers; please keep this page open.
            </p>
            <div aria-hidden className="h-1 overflow-hidden rounded bg-muted">
              <div className="h-full w-1/3 animate-indeterminate rounded bg-primary motion-reduce:w-full motion-reduce:animate-none" />
            </div>
          </div>
        )}
        {formError && <Alert tone="danger">{formError}</Alert>}
        {degraded && (
          <p id="tts-paused" role="status" className="text-sm">
            Generating is paused while the service recovers. This page will update on its own.
          </p>
        )}
        {cooldown.remaining > 0 && (
          <p id="tts-cooldown" role="status" className="text-sm">
            You can try again in {cooldown.remaining} s.
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            className="whitespace-nowrap"
            disabled={degraded || cooldown.remaining > 0 || blocker !== null}
            aria-describedby={whyDisabled}
            loading={pending}
          >
            {pending ? "Generating…" : "Generate speech"}
          </Button>
          {blocker && (
            <p id="tts-blocked" className="self-center text-sm text-muted-foreground">
              {blocker}
              {stepsBelow && (
                <>
                  {" "}
                  <a href="#first-run-title" className="underline">
                    See the steps below.
                  </a>
                </>
              )}
            </p>
          )}
          {pending && (
            <Button variant="secondary" onClick={() => controller.current?.abort()}>
              Cancel
            </Button>
          )}
        </div>
      </form>

      {result && audioUrl && (
        <section
          ref={resultRef}
          aria-labelledby="result-title"
          className="max-w-xl space-y-2 rounded border border-border p-4"
        >
          <h2 id="result-title" className="font-medium">
            Your audio{" "}
            <span className="text-sm font-normal text-muted-foreground">(AI-generated voice)</span>
          </h2>
          <Take
            src={audioUrl}
            blob={result.blob}
            filename={result.filename}
            label="Generated speech"
            animateIn
          />
          <ExpandableText
            text={`“${result.text}”`}
            limit={QUOTE_PREVIEW_CHARS}
            className="text-sm text-muted-foreground"
          />
          {engineNote && (
            <p
              role={result.engineFallbackFrom ? "status" : undefined}
              className={result.engineFallbackFrom ? "text-sm" : "text-xs text-muted-foreground"}
            >
              {engineNote}.
            </p>
          )}
          {result.styleApplied === false && (
            <p role="status" className="text-sm">
              The chosen delivery could not be applied with this voice engine, so the audio uses its
              default delivery.
            </p>
          )}
          {result.emotions.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Delivery by sentence: {result.emotions.join(", ")}.
            </p>
          )}
          {result.tagsDropped.length > 0 && (
            <p role="status" className="text-sm">
              This engine can&apos;t make these sounds, so they were left out:{" "}
              {result.tagsDropped.join(", ")}.
            </p>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                textRef.current?.focus();
                textRef.current?.select();
              }}
            >
              Edit text
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={pending || degraded || cooldown.remaining > 0 || blocker !== null}
              aria-describedby={whyDisabled}
              onClick={() => {
                setText(result.text);
                void run(result.text);
              }}
            >
              Generate again
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            If you leave this page, find past audio in History.
          </p>
        </section>
      )}
    </div>
  );
}
