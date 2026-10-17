import type { VoiceProfileUpload } from "@/lib/api/voice";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";

const RATING_LABEL: Readonly<Record<string, string>> = {
  good: "Good recording",
  fair: "Fair recording",
  poor: "Poor recording",
};

/**
 * What the upload learned about the recording: an overall rating with the fixes it suggests, and a
 * warning when one of several clips may be a different speaker. Advice only; the voice was created.
 */
export function VoiceQualityReport({ profile }: { profile: VoiceProfileUpload }) {
  const quality = profile.quality;
  const mismatched = (profile.samples ?? []).filter((s) => s.mismatch);
  if (!quality && mismatched.length === 0) return null;
  return (
    <section aria-label="Recording quality" className="space-y-2 text-sm">
      {quality && (
        <>
          <p className="flex items-center gap-2">
            <Badge tone={quality.rating === "good" ? "success" : "notice"}>
              {RATING_LABEL[quality.rating] ?? quality.rating}
            </Badge>
            {quality.hints.length > 0 && (
              <span className="text-muted-foreground">
                A cleaner recording usually sounds closer to the real voice.
              </span>
            )}
          </p>
          {quality.hints.length > 0 && (
            <ul className="list-disc space-y-1 pl-5">
              {quality.hints.map((h) => (
                <li key={h.code}>{h.message}</li>
              ))}
            </ul>
          )}
        </>
      )}
      {mismatched.length > 0 && (
        <Alert tone="neutral">
          {mismatched.length === 1
            ? `Clip ${(mismatched[0]?.position ?? 0) + 1} may be a different speaker from the others.`
            : `Clips ${mismatched.map((s) => s.position + 1).join(", ")} may be different speakers from the others.`}{" "}
          Mixing speakers makes the voice less accurate; remove or re-record{" "}
          {mismatched.length === 1 ? "it" : "them"} if that is not intended.
        </Alert>
      )}
    </section>
  );
}
