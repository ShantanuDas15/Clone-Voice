"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { AudioUploader } from "@/components/audio-uploader";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { uploadErrorMessage } from "@/components/upload-voice-form";
import { useAddClips, useRemoveClip } from "@/hooks/use-voice-profiles";
import { fetchTerms } from "@/lib/api/terms";
import type { VoiceProfile } from "@/lib/api/voice";
import { ApiError } from "@/lib/errors";
import { notify } from "@/lib/toast";
import { MAX_CLIPS } from "@/lib/validation/audio";

const RATING_LABEL: Readonly<Record<string, string>> = { good: "Good", fair: "Fair", poor: "Poor" };

/**
 * The clips behind one voice: how each was recorded and how well it agrees with the others, with
 * removing a clip and adding more. Adding re-attests consent, as the first upload did.
 */
export function ProfileClips({ profile }: { profile: VoiceProfile }) {
  const samples = profile.samples ?? [];
  const remove = useRemoveClip();
  const add = useAddClips();
  const terms = useQuery({ queryKey: ["terms"], queryFn: fetchTerms, staleTime: 5 * 60_000 });
  const [files, setFiles] = useState<File[]>([]);
  const [consent, setConsent] = useState(false);
  const [adult, setAdult] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const room = MAX_CLIPS - samples.length;
  const busy = add.isPending || remove.isPending;

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    if (add.isPending) return;
    setError(null);
    if (files.length === 0) return setError("Choose an audio file");
    if (!consent) return setError("Confirm you have the right to use this voice");
    if (!adult) return setError("Confirm the speaker is 18 or older");
    if (files.length > room) return setError(`This voice can take ${room} more clip(s).`);
    setProgress(0);
    try {
      await add.mutateAsync({
        id: profile.id,
        files,
        termsVersion: terms.data?.version ?? null,
        onProgress: setProgress,
      });
      notify.success(`Added to “${profile.name}”.`);
      setFiles([]);
      setConsent(false);
      setAdult(false);
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
      if (err.kind === "TERMS_CHANGED") {
        setConsent(false);
        setAdult(false);
        setError("The terms have changed. Please review them and confirm again.");
      } else setError(uploadErrorMessage(err));
    } finally {
      setProgress(null);
    }
  }

  return (
    <details className="w-full text-sm">
      <summary className="min-h-11 cursor-pointer py-2 underline underline-offset-2">
        Clips{samples.length > 0 ? ` (${samples.length})` : ""}
      </summary>
      <div className="space-y-3 pb-2">
        {samples.length === 0 ? (
          <p className="text-muted-foreground">
            This voice was made before clips were tracked. Add more clips of the same person to
            improve it.
          </p>
        ) : (
          <ul className="space-y-2" aria-label={`Clips of ${profile.name}`}>
            {samples.map((s) => (
              <li key={s.position} className="flex flex-wrap items-start justify-between gap-2">
                <div className="space-y-1">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">Clip {s.position + 1}</span>
                    {s.quality && (
                      <Badge tone={s.quality.rating === "good" ? "success" : "notice"}>
                        {RATING_LABEL[s.quality.rating] ?? s.quality.rating}
                      </Badge>
                    )}
                    {s.mismatch && <Badge tone="notice">May be a different speaker</Badge>}
                    {samples.length > 1 && (
                      <span className="text-muted-foreground">
                        Matches the others {Math.round(s.agreement * 100)}%
                      </span>
                    )}
                  </p>
                  {s.quality && s.quality.hints.length > 0 && (
                    <ul className="list-disc pl-5 text-muted-foreground">
                      {s.quality.hints.map((h) => (
                        <li key={h.code}>{h.message}</li>
                      ))}
                    </ul>
                  )}
                </div>
                {samples.length > 1 && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={busy}
                    aria-label={`Remove clip ${s.position + 1} of ${profile.name}`}
                    onClick={() =>
                      remove.mutate(
                        { id: profile.id, position: s.position },
                        {
                          onError: (e) =>
                            notify.error(
                              e instanceof ApiError ? e.message : "Couldn't remove that clip.",
                            ),
                          onSuccess: () => notify.success(`Removed clip ${s.position + 1}.`),
                        },
                      )
                    }
                  >
                    Remove
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {room > 0 ? (
          <form
            onSubmit={onAdd}
            noValidate
            className="space-y-2"
            aria-label={`Add clips to ${profile.name}`}
          >
            <AudioUploader files={files} onChange={setFiles} disabled={busy} />
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                disabled={busy}
                className="mt-1 h-4 w-4"
              />
              <span>I confirm I have the right to use these samples of this voice.</span>
            </label>
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={adult}
                onChange={(e) => setAdult(e.target.checked)}
                disabled={busy}
                className="mt-1 h-4 w-4"
              />
              <span>I confirm the speaker is 18 or older.</span>
            </label>
            {progress !== null && (
              <p role="status">
                {progress < 1
                  ? `Uploading… ${Math.round(progress * 100)}%`
                  : "Updating the voice. Please keep this page open."}
              </p>
            )}
            {error && <Alert tone="danger">{error}</Alert>}
            <Button type="submit" disabled={busy || !!progress} loading={add.isPending}>
              Add clips
            </Button>
          </form>
        ) : (
          <p className="text-muted-foreground">This voice has the most clips it can hold.</p>
        )}
      </div>
    </details>
  );
}
